#!/usr/bin/env python3
"""The ChatGPT picture MCP server (mcp_server/chatgpt_images.py), run as a host runs it: a subprocess
over stdio, driven by the SDK's own Client, against a fake /v1 that records what it was sent.

    ~/.venvs/aip-mcp/bin/python tests/test_mcp_chatgpt_images.py

Needs the server's own venv (mcp_server/requirements.txt). No platform, no worker, no account.
Prints N/N PASSED.
"""

import anyio
import base64
import email.parser
import http.server
import io
import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from mcp import Client, StdioServerParameters
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp_server" / "chatgpt_images.py"
KEY = "aip_test-key-" + "x" * 30


def png(width, height):
    out = io.BytesIO()
    Image.new("RGB", (width, height), (200, 40, 40)).save(out, "PNG")
    return out.getvalue()


# A real picture, wider than tall, so its preview's size can be checked; and bytes that only claim to be one.
PICTURE = png(1200, 800)
BROKEN = b"\x89PNG\r\n\x1a\n" + b"fake picture bytes" * 20

results = []


def record(name, ok, detail=""):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class FakeV1:
    """/v1/images as the platform answers it. A prompt names its fate: "refuse" answers 402, "fail"
    ends failed, "slow" stays running until `finish` is called (or until it is cancelled), "broken"
    ends done with a picture no decoder can read, anything else ends done with one picture after one
    running read. /v1/account answers ACCOUNT, and /v1/providers serves chatgpt while `served`."""

    ACCOUNT = {"credits_left": 7, "credits_daily": 100, "refills_at": "2026-10-30T00:00:00Z"}

    def __init__(self):
        self.posts, self.requests, self.served = [], {}, True
        self.account_broken = self.providers_broken = self.sessions_broken = False
        self.sessions = []
        self.scripts, self.script_posts = {}, []
        fake = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def answer(self, status, body, ctype="application/json"):
                raw = json.dumps(body).encode() if ctype == "application/json" else body
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                message = email.parser.BytesParser().parsebytes(
                    b"Content-Type: " + self.headers.get("Content-Type", "").encode() + b"\r\n\r\n" + body)
                fields, images = {}, []
                for part in message.get_payload() if message.is_multipart() else []:
                    name = part.get_param("name", header="content-disposition")
                    fields[name] = part.get_payload(decode=True)
                    if name == "image":
                        images.append(fields[name])
                fake.posts.append({"path": self.path, "auth": self.headers.get("Authorization"), "fields": fields,
                                   "images": images})
                parts = self.path.strip("/").split("/")
                if self.path == "/v1/scripts":
                    asked = json.loads(body)
                    fake.script_posts.append(asked)
                    if asked["target"] == "nosuch":
                        return self.answer(400, {"detail": "unknown target 'nosuch'; one of flow, minimax_h3, wan"})
                    rid = uuid.uuid4().hex
                    fake.scripts[rid] = dict(asked, reads=0)
                    return self.answer(202, {"id": rid, "status": "queued"})
                if len(parts) == 4 and parts[:2] == ["v1", "images"] and parts[3] == "cancel":
                    state = fake.requests.get(parts[2])
                    if not state:
                        return self.answer(404, {"detail": "image request not found"})
                    if "slow" in state["prompt"] and not state["finished"]:
                        state["cancelled"] = True
                    return self.answer(200, fake.status(parts[2], read=False))
                if self.path != "/v1/images":
                    return self.answer(404, {"detail": "Not Found"})
                prompt = (fields.get("prompt") or b"").decode()
                if "refuse" in prompt:
                    return self.answer(402, {"detail": "quota exhausted"})
                rid = uuid.uuid4().hex
                named = fields.get("session")
                fake.requests[rid] = {"prompt": prompt, "reads": 0, "finished": False,
                                      "session": named.decode().strip().casefold() if named else None}
                self.answer(202, {"id": rid, "status": "queued"})

            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer " + KEY:
                    return self.answer(401, {"detail": "invalid api key"})
                parts = self.path.strip("/").split("/")
                if self.path == "/v1/script-targets":
                    return self.answer(200, {"targets": [{"name": "flow", "label": "Google Flow (Veo)", "min_seconds": 8, "max_seconds": 8,
                                                          "dialogue": True, "negative_prompt": False, "source": "a page"}]})
                if len(parts) == 3 and parts[:2] == ["v1", "scripts"]:
                    held = fake.scripts.get(parts[2])
                    if held is None:
                        return self.answer(404, {"detail": "script request not found"})
                    held["reads"] += 1
                    state = {"id": parts[2], "target": held["target"], "session": held.get("session"), "script": None, "error": None}
                    if "badscript" in held["brief"]:
                        return self.answer(200, dict(state, status="failed", error="the script does not fit: scene 1 lasts 99s"))
                    if "slowscript" in held["brief"]:
                        return self.answer(200, dict(state, status="running"))
                    if held["reads"] < 2:
                        return self.answer(200, dict(state, status="running"))
                    if held["target"] == "production":
                        return self.answer(200, dict(state, status="done", script={
                            "title": "Một tay", "target": "production", "total_seconds": 2.5,
                            "concept": {"idea": "IDEA-M", "audience": "AUDIENCE-M", "message": "MESSAGE-M", "tone": "TONE-M", "visual_style": "STYLE-M", "palette": "PALETTE-M", "synopsis": "SYNOPSIS-M"},
                            "characters": [{"name": "Linh", "description": "LOOK-M"}], "settings": [{"name": "Lề đường", "description": "SETTING-M"}],
                            "scenes": [{"number": 1, "title": "SCENE-M", "location": "LOCATION-M", "purpose": "PURPOSE-M", "description": "DESCRIPTION-M", "shots": [
                                {"number": 1, "duration_seconds": 2.5, "start_seconds": 0, "end_seconds": 2.5, "shot_size": "SIZE-M", "angle": "ANGLE-M", "lens": "LENS-M", "movement": "MOVE-M",
                                 "composition": "FRAME-M", "action": "ACTION-M", "lighting": "LIGHT-M", "color": "COLOR-M", "sound": "SOUND-M", "transition": "CUT-M", "dialogue": "LINE-M",
                                 "voice_over": "VO-M", "on_screen_text": "TEXT-M"}]}],
                            "post": {"pacing": "PACE-M", "transitions": "TRANS-M", "color_grade": "GRADE-M", "music": "MUSIC-M", "sound_mix": "MIX-M", "subtitles": "SUBS-M", "format": "FORMAT-M"}}))
                    if "oldscript" in held["brief"]:
                        return self.answer(200, dict(state, status="done", script={
                            "title": "Old", "target": held["target"], "total_seconds": 8, "characters": [],
                            "scenes": [{"number": 1, "duration_seconds": 8, "description": "a shot", "camera": "dolly in", "dialogue": "",
                                        "image_prompt": "a still", "video_prompt": "An old walk"}]}))
                    return self.answer(200, dict(state, status="done", script={
                        "title": "Về nhà", "target": held["target"], "total_seconds": 8, "characters": [{"name": "Lan", "description": "a red coat"}],
                        "direction": {"concept": "a coat that remembers", "hook": "she walks out of a painting", "visual_style": "35mm handheld", "palette": "teal and amber"},
                        "scenes": [{"number": 1, "duration_seconds": 8, "description": "a shot", "camera": "dolly in", "color": "teal shadows", "lighting": "low golden sun",
                                    "sound": "soft wind", "dialogue": "Xin chào",
                                    "image_prompt": "a still of Lan", "video_prompt": "Lan walks home", "negative_prompt": "blurry"}]}))
                if self.path == "/v1/account":
                    if fake.account_broken:
                        return self.answer(500, {"detail": "account broken"})
                    return self.answer(200, FakeV1.ACCOUNT)
                if self.path == "/v1/sessions?provider=chatgpt":
                    if fake.sessions_broken:
                        return self.answer(500, {"detail": "sessions broken"})
                    return self.answer(200, {"sessions": fake.sessions})
                if self.path == "/v1/providers":
                    if fake.providers_broken:
                        return self.answer(500, {"detail": "providers broken"})
                    return self.answer(200, {"providers": [
                        {"name": "chatgpt", "served": fake.served, "makes_pictures": True, "takes_reference": True},
                        {"name": "grok", "served": True, "makes_pictures": True, "takes_reference": False}]})
                if len(parts) == 5 and parts[3] == "files":
                    held = fake.requests.get(parts[2], {})
                    shown = held.get("prompt", "")
                    if "nofile" in shown:
                        return self.answer(404, {"detail": "picture not found"})
                    if "flakyfile" in shown and held.get("file_tries", 0) < 3:
                        held["file_tries"] = held.get("file_tries", 0) + 1
                        return self.answer(500, {"detail": "not yet"})
                    return self.answer(200, BROKEN if "broken" in shown else PICTURE, ctype="image/png")
                rid = parts[2] if len(parts) == 3 else None
                if rid not in fake.requests:
                    return self.answer(404, {"detail": "image request not found"})
                held = fake.requests[rid]
                if "vanishes" in held["prompt"]:
                    return self.answer(404, {"detail": "image request not found"})
                if "flakyread" in held["prompt"] and held.get("read_tries", 0) < 3:
                    held["read_tries"] = held.get("read_tries", 0) + 1
                    return self.answer(503, {"detail": "the api is restarting"})
                if "alwaysdown" in held["prompt"]:
                    return self.answer(502, {"detail": "the api is down"})
                self.answer(200, fake.status(rid))

            def log_message(self, *args):
                pass

        self.handler = Handler
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.server.server_address[1]
        self.url = "http://127.0.0.1:{}".format(self.port)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def restart(self):
        """Back on the same port after a shutdown, as the api after a restart."""
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", self.port), self.handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def status(self, rid, read=True):
        """GET /v1/images/{rid}'s answer; a read counts toward a plain request's end."""
        state = self.requests[rid]
        state["reads"] += 1 if read else 0
        body = {"id": rid, "provider": "chatgpt", "text": "", "error": None, "images": [], "session": state.get("session"),
                "created_at": "2026-10-29 10:00:00", "finished_at": None}
        if state.get("cancelled"):
            body.update(status="cancelled", error="cancelled by the user", finished_at="2026-10-29 10:00:30")
        elif "fail" in state["prompt"]:
            body.update(status="failed", error="chatgpt returned nothing after 300s",
                        finished_at="2026-10-29 10:05:00")
        elif "behind the budget" in state["prompt"] and not state["finished"]:
            body.update(status="queued", budget_free_at="2026-10-29 13:44:25")
        elif ("slow" in state["prompt"] and not state["finished"]) or state["reads"] < 2:
            body["status"] = "running"
        elif "noimage" in state["prompt"]:
            body.update(status="done", text="I could not draw that.", finished_at="2026-10-29 10:01:04")
        else:
            body.update(status="done", text="Here it is.", finished_at="2026-10-29 10:01:04", images=[{
                "id": "m1", "url": "/v1/images/{}/files/m1".format(rid), "content_type": "image/png",
                "bytes": len(PICTURE)}])
        return body

    def rid(self, prompt):
        return next((r for r, s in self.requests.items() if s["prompt"] == prompt), None)

    def finish(self, rid):
        self.requests[rid]["finished"] = True

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def said(result):
    return "\n".join(getattr(block, "text", "") for block in result.content)


def previews(result):
    return [block for block in result.content if getattr(block, "type", "") == "image"]


def pictures(folder):
    """The pictures saved in a folder, without the records beside them."""
    return sorted(p for p in folder.glob("*") if p.suffix != ".json") if folder.exists() else []


def kept_record(path):
    """The JSON record a picture's answer names, or {} when that file is not one."""
    try:
        return json.loads(Path(path or "/nowhere").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def server_params(api, key=KEY):
    env = {"AIP_API_URL": api, "AIP_POLL_SECONDS": "0.2"}
    if key:
        env["AIP_API_KEY"] = key
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)


async def run(fake, work):
    async with Client(server_params(fake.url)) as client:
        listed = {tool.name: tool for tool in (await client.list_tools()).tools}
        record("the server offers account_status, cancel_image, generate_image, generate_images, get_image and list_sessions",
               sorted(listed) == ["account_status", "cancel_image", "generate", "generate_image", "generate_images", "get_image",
                                  "get_video_script", "list_presets", "list_script_targets", "list_sessions", "write_video_script"],
               repr(sorted(listed)))
        schemas = {name: (tool.output_schema or {}).get("properties", {}) for name, tool in listed.items()}
        record("each tool publishes the shape of its answer as its output schema",
               all("request_id" in schemas.get(n, {}) and "pictures" in schemas.get(n, {})
                   for n in ("generate_image", "get_image")) and "requests" in schemas.get("generate_images", {}),
               repr({n: sorted(s) for n, s in schemas.items()}))

        out = work / "plain"
        result = await client.call_tool("generate_image", {"prompt": "a plain blue square", "save_dir": str(out)},
                                        read_timeout_seconds=60)
        text = said(result)
        saved = pictures(out)
        post = fake.posts[-1] if fake.posts else {}
        record("generate_image sends the prompt to chatgpt with the key, and saves the picture it made",
               not result.is_error and len(saved) == 1 and saved[0].read_bytes() == PICTURE
               and str(saved[0]) in text and post.get("auth") == "Bearer " + KEY
               and post.get("fields", {}).get("provider") == b"chatgpt"
               and post.get("fields", {}).get("prompt") == b"a plain blue square",
               "error {} saved {} said {!r} sent {}".format(result.is_error, [p.name for p in saved], text[:200],
                                                           {k: v[:20] for k, v in post.get("fields", {}).items()}))
        record("the key never appears in what the tool answers",
               KEY not in text and "aip_" not in text and "aip_" not in json.dumps(result.structured_content), "")

        shown = previews(result)
        size = Image.open(io.BytesIO(base64.b64decode(shown[0].data))).size if len(shown) == 1 else None
        record("a done picture's answer carries one preview, a JPEG whose longer side is 512 px",
               len(shown) == 1 and shown[0].mime_type == "image/jpeg" and size == (512, 341),
               "previews {} type {} size {}".format(len(shown), shown[0].mime_type if shown else None, size))

        answer = result.structured_content or {}
        first = (answer.get("pictures") or [{}])[0]
        rid = fake.rid("a plain blue square") or ""
        record("the answer's structured content names the request, its status and each saved picture",
               answer.get("request_id") == rid and answer.get("status") == "done"
               and answer.get("text") == "Here it is." and first.get("path") == str(saved[0] if saved else "")
               and first.get("content_type") == "image/png" and first.get("bytes") == len(PICTURE)
               and "windows_path" in first and kept_record(first.get("record")).get("request_id") == rid,
               repr(answer)[:300])

        name = saved[0].name if saved else ""
        kept = kept_record(first.get("record"))
        record("a picture is named by its prompt, the request and its number, with a record of it beside it",
               name == "a-plain-blue-square-{}-1.png".format(rid[:8])
               and Path(first.get("record", "")).name == "a-plain-blue-square-{}-1.json".format(rid[:8])
               and kept.get("prompt") == "a plain blue square" and kept.get("request_id") == rid
               and kept.get("reference_path") is None and kept.get("created_at") == "2026-10-29 10:00:00"
               and kept.get("finished_at") == "2026-10-29 10:01:04" and kept.get("text") == "Here it is.",
               "name {} record {}".format(name, kept))

        result = await client.call_tool("generate_image", {"prompt": "no preview wanted", "preview": False,
                                                           "save_dir": str(work / "quiet")}, read_timeout_seconds=60)
        record("preview=False answers without a preview, and still saves the picture",
               not result.is_error and not previews(result) and len(pictures(work / "quiet")) == 1,
               "error {} previews {}".format(result.is_error, len(previews(result))))

        result = await client.call_tool("generate_image", {"prompt": "a broken picture", "save_dir": str(work / "bad")},
                                        read_timeout_seconds=60)
        kept = pictures(work / "bad")
        record("a picture no preview can be made from is still saved, and the answer says why it has none",
               not result.is_error and not previews(result) and len(kept) == 1 and kept[0].read_bytes() == BROKEN
               and str(kept[0]) in said(result) and "no preview" in said(result),
               "error {} saved {} said {!r}".format(result.is_error, [p.name for p in kept], said(result)[:300]))

        reference = work / "ref.png"
        reference.write_bytes(b"\x89PNG\r\n\x1a\n reference picture")
        result = await client.call_tool("generate_image", {"prompt": "the same at night",
                                                           "reference_path": str(reference),
                                                           "save_dir": str(work / "ref")},
                                        read_timeout_seconds=60)
        sent = fake.posts[-1].get("fields", {}).get("image")
        kept = [kept_record(p) for p in (work / "ref").glob("*.json")]
        record("a reference picture is sent as the request's image, byte for byte, and its record names it",
               not result.is_error and sent == reference.read_bytes()
               and [k.get("reference_path") for k in kept] == [str(reference)],
               "error {} sent {} bytes records {}".format(result.is_error, len(sent or b""), kept))

        earlier = fake.rid("a plain blue square") or "none"
        result = await client.call_tool("generate_image", {"prompt": "the same square, at night",
                                                           "continue_from": earlier, "save_dir": str(work / "more")},
                                        read_timeout_seconds=60)
        once = fake.posts[-1].get("fields", {}).get("continue_from")
        before = len(fake.posts)
        await client.call_tool("generate_images", {"prompts": ["one more", "and another"], "continue_from": earlier,
                                                   "save_dir": str(work / "more")}, read_timeout_seconds=60)
        each = [p.get("fields", {}).get("continue_from") for p in fake.posts[before:]]
        plain = [p.get("fields", {}) for p in fake.posts if p.get("path") == "/v1/images"][0]
        record("continue_from is sent with the request, by generate_image and by every prompt of generate_images",
               not result.is_error and once == earlier.encode() and each == [earlier.encode()] * 2
               and "continue_from" not in plain, "once {} each {}".format(once, each))

        # Issue #28: a name of its own for a character.
        result = await client.call_tool("generate_image", {"prompt": "a woman with short hair", "session": "Woman-A",
                                                           "save_dir": str(work / "sessions")}, read_timeout_seconds=60)
        once = fake.posts[-1].get("fields", {}).get("session")
        data = result.structured_content or {}
        kept = [kept_record(p.with_suffix(".json")) for p in pictures(work / "sessions")]
        record("a session is sent with the request, and the answer and the record name it",
               not result.is_error and once == b"Woman-A" and data.get("session") == "woman-a"
               and 'in session "woman-a"' in said(result) and [k.get("session") for k in kept] == ["woman-a"],
               "sent {} answer {!r} records {}".format(once, data.get("session"), [k.get("session") for k in kept]))
        before = len(fake.posts)
        result = await client.call_tool("generate_images", {"prompts": ["one", "two"], "session": "woman-b",
                                                            "save_dir": str(work / "sessions")}, read_timeout_seconds=60)
        each = [p.get("fields", {}).get("session") for p in fake.posts[before:]]
        record("every prompt of a set goes into its session, and the answer names it",
               not result.is_error and each == [b"woman-b"] * 2 and (result.structured_content or {}).get("session") == "woman-b"
               and 'in session "woman-b"' in said(result), "each {} said {!r}".format(each, said(result)[:60]))
        record("a request with no session sends none", "session" not in plain and (fake.status(fake.rid("a plain blue square"),
               read=False).get("session") is None), str(sorted(plain)))

        result = await client.call_tool("list_sessions", {})
        record("no session yet is said in words", not result.is_error and "no named session" in said(result)
               and (result.structured_content or {}).get("sessions") == [], said(result))
        fake.sessions = [{"name": "woman-b", "provider": "chatgpt", "conversation_id": "c2", "requests": 2, "pictures": 2,
                          "created_at": "2026-10-31 10:00:00", "last_used": "2026-10-31 10:05:00"},
                         {"name": "woman-a", "provider": "chatgpt", "conversation_id": "c1", "requests": 1, "pictures": 1,
                          "created_at": "2026-10-31 09:00:00", "last_used": "2026-10-31 09:00:00"}]
        result = await client.call_tool("list_sessions", {})
        rows = (result.structured_content or {}).get("sessions") or []
        record("list_sessions lists them with what they hold", not result.is_error and [r["name"] for r in rows] == ["woman-b", "woman-a"]
               and rows[0]["pictures"] == 2 and '"woman-a": 1 picture(s)' in said(result), said(result))
        fake.sessions_broken = True
        result = await client.call_tool("list_sessions", {})
        record("sessions that cannot be read are a tool error", result.is_error and "sessions could not be read" in said(result), said(result))
        fake.sessions_broken = False
        # Issue #30: video scripts for a video model, and recipes kept as files.
        result = await client.call_tool("write_video_script", {"brief": "Lan goes home", "target": "flow", "scenes": 1, "session": "lan",
                                                               "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
        data, asked = result.structured_content or {}, fake.script_posts[-1]
        markdown = Path(data.get("markdown_path") or "/nowhere")
        text = markdown.read_text(encoding="utf-8") if markdown.exists() else ""
        record("a script goes to Grok unless told, and comes back saved to read and to paste from",
               not result.is_error and asked["provider"] == "grok" and asked["scenes"] == 1 and asked["session"] == "lan" and data.get("status") == "done"
               and data["script"]["title"] == "Về nhà" and json.loads(Path(data["json_path"]).read_text(encoding="utf-8"))["scenes"][0]["video_prompt"] == "Lan walks home"
               and "Lan walks home" in text and "a still of Lan" in text and "Xin chào" in text and "blurry" in text and data.get("session") == "lan",
               "{} {} {!r}".format(result.is_error, asked, said(result)[:90]))
        record("the saved Markdown shows the direction, and each scene's color, lighting and sound",
               all(word in text for word in ("a coat that remembers", "she walks out of a painting", "35mm handheld", "teal and amber", "teal shadows", "low golden sun", "soft wind")), text[:200])
        result = await client.call_tool("write_video_script", {"brief": "oldscript", "target": "flow", "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
        old = Path((result.structured_content or {}).get("markdown_path") or "/nowhere")
        record("a script from before the direction still reads as Markdown", not result.is_error and old.exists() and "An old walk" in old.read_text(encoding="utf-8"), said(result)[:90])
        result = await client.call_tool("write_video_script", {"brief": "x", "target": "nosuch"}, read_timeout_seconds=60)
        record("a target the platform does not know is a tool error saying which there are", result.is_error and "flow" in said(result), said(result)[:90])
        result = await client.call_tool("write_video_script", {"brief": "badscript", "target": "flow"}, read_timeout_seconds=60)
        record("a script that did not fit is a tool error saying why and that the credit came back",
               result.is_error and "99s" in said(result) and "credit" in said(result), said(result)[:90])
        result = await client.call_tool("write_video_script", {"brief": "slowscript", "target": "wan", "wait_seconds": 1}, read_timeout_seconds=60)
        waiting = (result.structured_content or {})
        record("a script still running says to collect it later", not result.is_error and waiting.get("status") == "running" and "get_video_script" in said(result), said(result)[:90])
        result = await client.call_tool("get_video_script", {"request_id": waiting.get("request_id") or "x"}, read_timeout_seconds=60)
        record("get_video_script reads it again", not result.is_error and (result.structured_content or {}).get("status") == "running", said(result)[:90])
        result = await client.call_tool("list_script_targets", {})
        record("list_script_targets says what each video model takes", not result.is_error and (result.structured_content or {})["targets"][0]["name"] == "flow", said(result)[:90])

        result = await client.call_tool("list_presets", {})
        ids = [p["id"] for p in (result.structured_content or {}).get("presets") or []]
        record("list_presets reads the recipes kept as files", not result.is_error and {"character-portrait", "short-film-flow", "short-film-minimax", "short-film-wan"} <= set(ids), ids)
        before = len(fake.posts)
        result = await client.call_tool("generate", {"preset": "character-portrait", "inputs": {"character": "Lan", "description": "a woman in a red coat"},
                                                     "save_dir": str(work / "presets")}, read_timeout_seconds=60)
        sent = fake.posts[before].get("fields", {}) if len(fake.posts) > before else {}
        record("an image preset fills its template, its defaults, and takes its session from the character",
               not result.is_error and b"a woman in a red coat" in sent.get("prompt", b"") and b"A gentle smile" in sent.get("prompt", b"") and sent.get("session") == b"Lan",
               "{} {} {!r}".format(result.is_error, sent, said(result)[:80]))
        result = await client.call_tool("generate", {"preset": "short-film-wan", "inputs": {"story": "Lan goes home"}, "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
        asked = fake.script_posts[-1]
        record("a script preset names its video model and its writer", not result.is_error and asked["target"] == "wan" and asked["provider"] == "grok" and asked["brief"] == "Lan goes home",
               "{} {}".format(asked, said(result)[:80]))
        content = {"content-ad-flow": ({"product": "PRODUCT-X", "audience": "AUDIENCE-X", "benefit": "BENEFIT-X"}, 4),
                   "content-story-flow": ({"idea": "IDEA-X", "characters": "CHARACTER-X"}, 6),
                   "content-review-flow": ({"product": "PRODUCT-X", "audience": "AUDIENCE-X", "experience": "EXPERIENCE-X"}, 4),
                   "content-explainer-flow": ({"topic": "TOPIC-X", "points": "POINTS-X", "audience": "AUDIENCE-X"}, 5)}
        for preset, (given, count) in content.items():
            result = await client.call_tool("generate", {"preset": preset, "inputs": given, "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            asked = fake.script_posts[-1]
            record("{} goes to Grok for Flow, {} scenes, with what it was given and its defaults".format(preset, count),
                   not result.is_error and asked["provider"] == "grok" and asked["target"] == "flow" and asked["scenes"] == count and asked["language"] == "vi"
                   and all(value in asked["brief"] for value in given.values()) and "vertical 9:16" in asked["brief"] and "{" not in asked["brief"], "{} {}".format(asked, said(result)[:80]))
            before = len(fake.script_posts)
            result = await client.call_tool("generate", {"preset": preset, "inputs": dict(list(given.items())[1:]), "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            record("{} refuses a brief with its first input left out".format(preset), result.is_error and "needs" in said(result) and len(fake.script_posts) == before, said(result)[:90])
            result = await client.call_tool("generate", {"preset": preset, "inputs": given, "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            brief = fake.script_posts[-1]["brief"]
            record("{} forbids danger on screen, gives a child nothing unfit, and asks for the palette inside the prompts".format(preset),
                   "No one does anything dangerous" in brief and "No child" in brief and "Name the palette's colors" in brief and "aloud" in brief, brief[-200:])
            wanted = {"content-ad-flow": "where it is safe to use", "content-story-flow": "Throw away the first ending",
                      "content-review-flow": "different shot size", "content-explainer-flow": "snowball"}[preset]
            record("{} carries its own rule against what its first real script got wrong".format(preset), wanted in brief, wanted)
        for preset in ("content-ad-flow", "content-review-flow"):
            result = await client.call_tool("generate", {"preset": preset, "inputs": content[preset][0], "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            record("{} forbids inventing claims".format(preset), "Do not invent" in fake.script_posts[-1]["brief"], fake.script_posts[-1]["brief"][-200:])
        director = {"director-ad": {"product": "PRODUCT-X", "audience": "AUDIENCE-X", "benefit": "BENEFIT-X"},
                    "director-story": {"idea": "IDEA-X", "characters": "CHARACTER-X"},
                    "director-review": {"product": "PRODUCT-X", "audience": "AUDIENCE-X", "experience": "EXPERIENCE-X"},
                    "director-explainer": {"topic": "TOPIC-X", "points": "POINTS-X", "audience": "AUDIENCE-X"}}
        for preset, given in director.items():
            result = await client.call_tool("generate", {"preset": preset, "inputs": given, "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            asked = fake.script_posts[-1]
            brief = asked["brief"]
            record("{} asks Grok for a whole film of 45s by default, in Vietnamese, with what it was given".format(preset),
                   not result.is_error and asked["target"] == "production" and asked["provider"] == "grok" and asked["total_seconds"] == 45 and asked["language"] == "vi"
                   and "scenes" not in asked and all(value in brief for value in given.values()) and "vertical 9:16" in brief and "{" not in brief, "{} {}".format(asked, said(result)[:80]))
            record("{} keeps danger off screen and asks for rhythm in its cut".format(preset),
                   "No one does anything dangerous" in brief and "No child" in brief and "rhythm" in brief and "aloud" in brief, brief[-200:])
            result = await client.call_tool("generate", {"preset": preset, "inputs": dict(given, seconds=90), "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            record("{} asks for a camera that moves on purpose, a strong first two seconds, and no image repeated".format(preset),
                   "Move the camera on purpose" in brief and "first two seconds" in brief and "more than twice" in brief and "four words a second" in brief, brief[-200:])
            record("{} shares out the film's time first, and does not pad its ending".format(preset),
                   "Divide the film's length" in brief and "never pad the ending" in brief and "no more than three seconds" in brief, brief[-200:])
            record("{} takes the film's length from its input".format(preset), not result.is_error and fake.script_posts[-1]["total_seconds"] == 90 and "90 seconds" in fake.script_posts[-1]["brief"], said(result)[:90])
            before = len(fake.script_posts)
            result = await client.call_tool("generate", {"preset": preset, "inputs": dict(given, seconds="dài"), "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            record("{} refuses a length that is not a number, and sends nothing".format(preset), result.is_error and "seconds" in said(result) and len(fake.script_posts) == before, said(result)[:90])
        for preset, wanted in (("director-ad", "Do not invent"), ("director-ad", "where it is safe to use"), ("director-ad", "not even at a red light"), ("director-story", "Throw away the first ending"),
                               ("director-review", "Do not invent"), ("director-review", "different shot size"), ("director-explainer", "snowball"), ("director-explainer", "sources, promises or facts")):
            result = await client.call_tool("generate", {"preset": preset, "inputs": director[preset], "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
            record("{} says: {}".format(preset, wanted), wanted in fake.script_posts[-1]["brief"], fake.script_posts[-1]["brief"][-200:])
        result = await client.call_tool("write_video_script", {"brief": "a film", "target": "production", "total_seconds": 3, "save_dir": str(work / "scripts")}, read_timeout_seconds=60)
        data = result.structured_content or {}
        film_text = Path(data.get("markdown_path") or "/nowhere").read_text(encoding="utf-8") if data.get("markdown_path") else ""
        missing = [word for word in ("IDEA-M", "AUDIENCE-M", "MESSAGE-M", "TONE-M", "STYLE-M", "PALETTE-M", "SYNOPSIS-M", "LOOK-M", "SETTING-M", "SCENE-M", "LOCATION-M", "PURPOSE-M", "DESCRIPTION-M",
                                     "SIZE-M", "ANGLE-M", "LENS-M", "MOVE-M", "FRAME-M", "ACTION-M", "LIGHT-M", "COLOR-M", "SOUND-M", "CUT-M", "LINE-M", "VO-M", "TEXT-M",
                                     "PACE-M", "TRANS-M", "GRADE-M", "MUSIC-M", "MIX-M", "SUBS-M", "FORMAT-M", "00:00 to 00:02.5") if word not in film_text]
        record("a production's Markdown shows every part of it, its shots timed", not result.is_error and not missing, missing or said(result)[:90])
        for name, arguments, word in (("a missing input", {"preset": "character-scene", "inputs": {"character": "Lan"}}, "needs"),
                                      ("an input it does not take", {"preset": "short-film-wan", "inputs": {"story": "x", "mood": "y"}}, "no input mood"),
                                      ("a preset that is not there", {"preset": "nosuch", "inputs": {}}, "no preset"),
                                      ("a reference picture to a script", {"preset": "short-film-wan", "inputs": {"story": "x"}, "reference_path": "/x.png"}, "no reference")):
            before = len(fake.posts) + len(fake.script_posts)
            result = await client.call_tool("generate", arguments, read_timeout_seconds=60)
            record("{} is refused and nothing is sent".format(name), result.is_error and word in said(result) and len(fake.posts) + len(fake.script_posts) == before, said(result)[:90])

        told = client.instructions or ""
        record("the server tells an agent to give each character a session", "session=" in told and "different person" in told,
               told[-120:])

        refs = []
        for n in range(5):
            refs.append(work / "ref{}.png".format(n))
            refs[-1].write_bytes(b"\x89PNG\r\n\x1a\n reference " + str(n).encode())
        result = await client.call_tool("generate_image", {"prompt": "the two together",
                                                           "reference_paths": [str(refs[0]), str(refs[1])],
                                                           "save_dir": str(work / "two")}, read_timeout_seconds=60)
        sent = fake.posts[-1].get("images")
        kept = [kept_record(p) for p in (work / "two").glob("*.json")]
        before = len(fake.posts)
        five = await client.call_tool("generate_image", {"prompt": "too many", "reference_path": str(refs[0]),
                                                         "reference_paths": [str(r) for r in refs[1:]]},
                                      read_timeout_seconds=30)
        record("reference_paths sends each picture in order, the record names them, and more than 4 is refused",
               not result.is_error and sent == [refs[0].read_bytes(), refs[1].read_bytes()]
               and [k.get("reference_paths") for k in kept] == [[str(refs[0]), str(refs[1])]]
               and five.is_error and "at most 4" in said(five) and len(fake.posts) == before,
               "error {} sent {} records {} five {!r}".format(result.is_error, len(sent or []), kept, said(five)[:120]))

        before = len(fake.posts)
        result = await client.call_tool("generate_image", {"prompt": "x", "reference_path": str(work / "nope.png")},
                                        read_timeout_seconds=30)
        record("a reference picture that is not there is refused before anything is sent",
               result.is_error and len(fake.posts) == before and "nope.png" in said(result),
               "error {} posts {} said {!r}".format(result.is_error, len(fake.posts) - before, said(result)[:120]))

        result = await client.call_tool("generate_image", {"prompt": "please refuse", "save_dir": str(work / "no")},
                                        read_timeout_seconds=30)
        record("a request the platform refuses is a tool error with the platform's own reason",
               result.is_error and "402" in said(result) and "quota exhausted" in said(result)
               and not (work / "no").exists(),
               "error {} said {!r}".format(result.is_error, said(result)[:160]))

        result = await client.call_tool("generate_image", {"prompt": "this will fail", "save_dir": str(work / "f")},
                                        read_timeout_seconds=30)
        record("a request that fails is a tool error with its reason",
               result.is_error and "chatgpt returned nothing after 300s" in said(result),
               "error {} said {!r}".format(result.is_error, said(result)[:160]))

        result = await client.call_tool("generate_image", {"prompt": "a slow one", "save_dir": str(work / "slow"),
                                                           "wait_seconds": 1}, read_timeout_seconds=30)
        rid = fake.rid("a slow one")
        answer = result.structured_content or {}
        record("a request still running when the wait ends says so with its id, and is no error",
               not result.is_error and rid and rid in said(result) and "get_image" in said(result)
               and answer.get("request_id") == rid and answer.get("status") == "running"
               and answer.get("pictures") == [] and "picture budget" not in said(result),
               "error {} said {!r} answer {}".format(result.is_error, said(result)[:200], answer))
        if rid:
            fake.finish(rid)

        steps = []

        async def waiting(done, total, message):
            steps.append(message or "")

        result = await client.call_tool("generate_image", {"prompt": "one behind the budget", "save_dir": str(work / "budget"),
                                                           "wait_seconds": 1}, read_timeout_seconds=30, progress_callback=waiting)
        behind = fake.rid("one behind the budget")
        record("a request behind the spent budget says so, until when, and not to send it again",
               not result.is_error and "picture budget" in said(result) and "2026-10-29 13:44:25" in said(result)
               and "sending it again" in said(result) and behind in said(result)
               and any("2026-10-29 13:44:25" in step for step in steps),
               "said {!r} steps {}".format(said(result)[:300], steps))
        result = await client.call_tool("generate_images", {"prompts": ["a set's one behind the budget"], "save_dir": str(work / "budget"),
                                                            "wait_seconds": 1}, read_timeout_seconds=30)
        record("so does one of a set", not result.is_error and "picture budget" in said(result)
               and "2026-10-29 13:44:25" in said(result), "said {!r}".format(said(result)[:300]))
        fake.finish(behind or "")
        fake.finish(fake.rid("a set's one behind the budget") or "")
        result = await client.call_tool("get_image", {"request_id": rid or "none", "save_dir": str(work / "slow")},
                                        read_timeout_seconds=30)
        later = pictures(work / "slow")
        record("get_image collects that request's picture once it is done, named by the prompt it was sent with",
               not result.is_error and len(later) == 1 and later[0].read_bytes() == PICTURE
               and later[0].name.startswith("a-slow-one-") and len(previews(result)) == 1,
               "error {} saved {} said {!r}".format(result.is_error, [p.name for p in later], said(result)[:160]))

        steps = []

        async def progress(done, total, message):
            steps.append(message or "")

        prompts = ["Một chú mèo cam bên cửa sổ!", "the set's second will fail", "the set's third is slow"]
        result = await client.call_tool("generate_images", {"prompts": prompts, "save_dir": str(work / "set"),
                                                            "wait_seconds": 3},
                                        read_timeout_seconds=60, progress_callback=progress)
        items = (result.structured_content or {}).get("requests") or []
        fates = [(i.get("prompt"), i.get("status")) for i in items]
        slow = fake.rid("the set's third is slow")
        made = pictures(work / "set")
        record("generate_images sends every prompt and answers each one's fate: done, failed, still running",
               not result.is_error and fates == list(zip(prompts, ["done", "failed", "running"]))
               and "chatgpt returned nothing after 300s" in (items[1].get("error") or "")
               and items[2].get("request_id") == slow and slow in said(result) and "get_image" in said(result)
               and len(made) == 1 and len(previews(result)) == 1,
               "error {} fates {} saved {} said {!r}".format(result.is_error, fates, [p.name for p in made],
                                                            said(result)[:300]))
        rid = fake.rid(prompts[0]) or ""
        record("a prompt in Vietnamese is named by its letters without their marks",
               [p.name for p in made] == ["mot-chu-meo-cam-ben-cua-so-{}-1.png".format(rid[:8])], repr(made))
        record("generate_images reports its progress as how many of the set are done",
               any("of 3" in step for step in steps), repr(steps[-3:]))

        before = len(fake.posts)
        prompts = ["first of three", "second gets a refuse", "third never sent"]
        result = await client.call_tool("generate_images", {"prompts": prompts, "save_dir": str(work / "short")},
                                        read_timeout_seconds=60)
        items = (result.structured_content or {}).get("requests") or []
        fates = [(i.get("prompt"), i.get("status")) for i in items]
        record("a refusal partway stops sending the rest, and the answer says which were sent and which were not",
               not result.is_error and len(fake.posts) - before == 2
               and fates == list(zip(prompts, ["done", "refused", "not sent"]))
               and "quota exhausted" in (items[1].get("error") or "") and len(pictures(work / "short")) == 1,
               "error {} posts {} fates {} said {!r}".format(result.is_error, len(fake.posts) - before, fates,
                                                            said(result)[:300]))

        before = len(fake.posts)
        result = await client.call_tool("generate_images", {"prompts": ["please refuse this set"]},
                                        read_timeout_seconds=30)
        record("a set whose first prompt is refused is a tool error with the platform's reason",
               result.is_error and "quota exhausted" in said(result) and len(fake.posts) - before == 1,
               "error {} said {!r}".format(result.is_error, said(result)[:160]))

        before = len(fake.posts)
        refused = []
        for prompts in ([], ["p{}".format(n) for n in range(21)], ["fine", "   "]):
            result = await client.call_tool("generate_images", {"prompts": prompts}, read_timeout_seconds=30)
            refused.append(result.is_error and "prompt" in said(result).split("generate_images", 1)[-1])
        record("an empty set, a set over 20 and a blank prompt are refused, saying why, before anything is sent",
               refused == [True, True, True] and len(fake.posts) == before,
               "errors {} posts {}".format(refused, len(fake.posts) - before))

        result = await client.call_tool("account_status", {}, read_timeout_seconds=30)
        answer = result.structured_content or {}
        record("account_status says the credits left, when they come back, and that ChatGPT is served",
               not result.is_error and answer.get("credits_left") == 7 and answer.get("credits_daily") == 100
               and answer.get("refills_at") == "2026-10-30T00:00:00Z" and answer.get("chatgpt_served") is True
               and all(part in said(result) for part in ("7", "100", "2026-10-30")),
               "error {} answer {}".format(result.is_error, answer))
        fake.served = False
        result = await client.call_tool("account_status", {}, read_timeout_seconds=30)
        fake.served = True
        record("account_status says so when no worker serves ChatGPT",
               not result.is_error and (result.structured_content or {}).get("chatgpt_served") is False
               and "not served" in said(result), "said {!r}".format(said(result)[:200]))

        result = await client.call_tool("generate_image", {"prompt": "a slow one to cancel", "wait_seconds": 1,
                                                           "save_dir": str(work / "cancel")}, read_timeout_seconds=30)
        rid = fake.rid("a slow one to cancel")
        result = await client.call_tool("cancel_image", {"request_id": rid or "none"}, read_timeout_seconds=30)
        answer = result.structured_content or {}
        record("cancel_image cancels a request still running, and says its credit was given back",
               not result.is_error and rid and answer.get("request_id") == rid and answer.get("status") == "cancelled"
               and "credit" in said(result) and (fake.posts[-1].get("path") == "/v1/images/{}/cancel".format(rid)),
               "error {} answer {} said {!r}".format(result.is_error, answer, said(result)[:200]))
        done_rid = fake.rid("a plain blue square")
        result = await client.call_tool("cancel_image", {"request_id": done_rid or "none"}, read_timeout_seconds=30)
        record("cancel_image on a request already over says so and changes nothing",
               not result.is_error and (result.structured_content or {}).get("status") == "done"
               and "already" in said(result), "said {!r}".format(said(result)[:200]))
        result = await client.call_tool("cancel_image", {"request_id": "not-a-request"}, read_timeout_seconds=30)
        record("cancel_image on an unknown request is a tool error with the platform's reason",
               result.is_error and "404" in said(result) and "image request not found" in said(result),
               "said {!r}".format(said(result)[:200]))

    # The branches coverage showed no test had reached (2026-10-30), and the platform not answering.
    async with Client(server_params(fake.url)) as client:
        async def picture(prompt, **more):
            return await client.call_tool("generate_image", dict({"prompt": prompt, "save_dir": str(work / "errs")},
                                                                 **more), read_timeout_seconds=60)

        got = await picture("flakyread comes back")
        record("a status read answering 503 for a while is waited through, and the picture is saved",
               not got.is_error and (got.structured_content or {}).get("status") == "done",
               "error {} said {!r}".format(got.is_error, said(got)[:140]))
        got = await picture("flakyfile comes back")
        record("a download answering 500 for a while is tried again, and the picture is saved",
               not got.is_error and (got.structured_content or {}).get("status") == "done",
               "error {} said {!r}".format(got.is_error, said(got)[:140]))
        got = await picture("alwaysdown never answers", wait_seconds=1)
        rid = fake.rid("alwaysdown never answers") or ""
        record("a platform that stays down ends the wait with the request's id to collect later, and is no error",
               not got.is_error and rid and rid in said(got) and "get_image" in said(got)
               and "does not answer" in said(got) and (got.structured_content or {}).get("request_id") == rid,
               "error {} said {!r}".format(got.is_error, said(got)[:200]))
        got = await picture("nofile is gone")
        record("a picture that answers 404 on download is a tool error naming it",
               got.is_error and "could not be downloaded" in said(got) and "404" in said(got), said(got)[:160])
        got = await picture("noimage at all")
        record("a request done with no picture is a tool error carrying what ChatGPT said",
               got.is_error and "no picture came back" in said(got) and "I could not draw that" in said(got),
               said(got)[:160])
        got = await picture("vanishes after sending")
        record("a request that answers 404 when read is a tool error naming it",
               got.is_error and "could not be read" in said(got) and "404" in said(got), said(got)[:160])

        prompts = ["set vanishes", "set nofile", "set noimage", "set flakyread", "set flakyfile", "set fine"]
        got = await client.call_tool("generate_images", {"prompts": prompts, "save_dir": str(work / "errset")},
                                     read_timeout_seconds=60)
        fates = [i.get("status") for i in (got.structured_content or {}).get("requests") or []]
        record("in a set, each failure stays its own prompt's: the rest are saved, the waits waited through",
               not got.is_error and fates == ["unread", "unsaved", "unsaved", "done", "done", "done"]
               and "get_image" in said(got), "fates {} said {!r}".format(fates, said(got)[:160]))

        before = len(fake.posts)
        fake.server.shutdown()
        fake.server.server_close()
        got = await client.call_tool("generate_images", {"prompts": ["nobody is there", "nor here"],
                                                         "save_dir": str(work / "down")}, read_timeout_seconds=30)
        record("a set whose first prompt cannot reach the platform is a tool error saying so",
               got.is_error and "could not be reached" in said(got), said(got)[:160])
        fake.restart()

        got = await client.call_tool("generate_image", {"prompt": "still fine", "save_dir": str(work / "again")},
                                     read_timeout_seconds=30)
        fake.account_broken = True
        broken_account = await client.call_tool("account_status", {}, read_timeout_seconds=30)
        fake.account_broken, fake.providers_broken = False, True
        broken_providers = await client.call_tool("account_status", {}, read_timeout_seconds=30)
        fake.providers_broken = False
        record("account_status names what it could not read",
               not got.is_error and broken_account.is_error and "account broken" in said(broken_account)
               and broken_providers.is_error and "providers broken" in said(broken_providers),
               "{!r} {!r}".format(said(broken_account)[:80], said(broken_providers)[:80]))

    before = len(fake.posts)
    async with Client(server_params(fake.url, key=None)) as client:
        result = await client.call_tool("generate_image", {"prompt": "no key"}, read_timeout_seconds=30)
        again = await client.call_tool("generate_images", {"prompts": ["no key"]}, read_timeout_seconds=30)
        others = [await client.call_tool(name, arguments, read_timeout_seconds=30)
                  for name, arguments in (("account_status", {}), ("cancel_image", {"request_id": "x"}))]
    record("without AIP_API_KEY the tools say how to set it and send nothing",
           result.is_error and "AIP_API_KEY" in said(result) and again.is_error and "AIP_API_KEY" in said(again)
           and all(o.is_error and "AIP_API_KEY" in said(o) for o in others) and len(fake.posts) == before,
           "error {} said {!r}".format(result.is_error, said(result)[:160]))


def module_cases():
    sys.path.insert(0, str(SERVER.parent))
    import chatgpt_images  # noqa: E402
    cases = {r"D:\work\ai-platform\ref.png": "/mnt/d/work/ai-platform/ref.png",
             "C:/Users/me/pic.png": "/mnt/c/Users/me/pic.png",
             "/home/me/pic.png": "/home/me/pic.png"}
    got = {path: chatgpt_images.local_path(path, wsl=True) for path in cases}
    record("under WSL a Windows path the agent gives is read where WSL sees it",
           got == cases, repr(got))
    record("outside WSL a path is taken as given",
           chatgpt_images.local_path(r"D:\x.png", wsl=False) == r"D:\x.png", "")
    slugs = {"Đường phố Sài Gòn về đêm": "duong-pho-sai-gon-ve-dem",
             "你好世界": "picture",
             "": "picture",
             "  A cat -- on a   MAT!! ": "a-cat-on-a-mat",
             "one two three four five six seven eight nine ten": "one-two-three-four-five-six-seven-eight"}
    slug = getattr(chatgpt_images, "slug", None)
    got = {prompt: slug(prompt) for prompt in slugs} if slug else None
    record("a prompt's slug is short ASCII, cut at a word, and 'picture' when it has no Latin letters",
           got == slugs, repr(got))


def main():
    if not SERVER.exists():
        record("the server file is there", False, str(SERVER))
    else:
        fake, work = FakeV1(), Path(tempfile.mkdtemp(prefix="mcp-chatgpt-images-"))
        try:
            anyio.run(run, fake, work)
            module_cases()
        finally:
            fake.close()
            shutil.rmtree(work, ignore_errors=True)
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
