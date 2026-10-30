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
                fields = {}
                for part in message.get_payload() if message.is_multipart() else []:
                    name = part.get_param("name", header="content-disposition")
                    fields[name] = part.get_payload(decode=True)
                fake.posts.append({"path": self.path, "auth": self.headers.get("Authorization"), "fields": fields})
                parts = self.path.strip("/").split("/")
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
                fake.requests[rid] = {"prompt": prompt, "reads": 0, "finished": False}
                self.answer(202, {"id": rid, "status": "queued"})

            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer " + KEY:
                    return self.answer(401, {"detail": "invalid api key"})
                parts = self.path.strip("/").split("/")
                if self.path == "/v1/account":
                    return self.answer(200, FakeV1.ACCOUNT)
                if self.path == "/v1/providers":
                    return self.answer(200, {"providers": [
                        {"name": "chatgpt", "served": fake.served, "makes_pictures": True, "takes_reference": True},
                        {"name": "grok", "served": True, "makes_pictures": True, "takes_reference": False}]})
                if len(parts) == 5 and parts[3] == "files":
                    shown = fake.requests.get(parts[2], {}).get("prompt", "")
                    return self.answer(200, BROKEN if "broken" in shown else PICTURE, ctype="image/png")
                rid = parts[2] if len(parts) == 3 else None
                if rid not in fake.requests:
                    return self.answer(404, {"detail": "image request not found"})
                self.answer(200, fake.status(rid))

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:{}".format(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def status(self, rid, read=True):
        """GET /v1/images/{rid}'s answer; a read counts toward a plain request's end."""
        state = self.requests[rid]
        state["reads"] += 1 if read else 0
        body = {"id": rid, "provider": "chatgpt", "text": "", "error": None, "images": [],
                "created_at": "2026-10-29 10:00:00", "finished_at": None}
        if state.get("cancelled"):
            body.update(status="cancelled", error="cancelled by the user", finished_at="2026-10-29 10:00:30")
        elif "fail" in state["prompt"]:
            body.update(status="failed", error="chatgpt returned nothing after 300s",
                        finished_at="2026-10-29 10:05:00")
        elif ("slow" in state["prompt"] and not state["finished"]) or state["reads"] < 2:
            body["status"] = "running"
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
        record("the server offers account_status, cancel_image, generate_image, generate_images and get_image",
               sorted(listed) == ["account_status", "cancel_image", "generate_image", "generate_images", "get_image"],
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
               and answer.get("pictures") == [],
               "error {} said {!r} answer {}".format(result.is_error, said(result)[:200], answer))
        if rid:
            fake.finish(rid)
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
    cases = {r"D:\keyti\ai-platform\ref.png": "/mnt/d/keyti/ai-platform/ref.png",
             "C:/Users/me/pic.png": "/mnt/c/Users/me/pic.png",
             "/home/keyti/pic.png": "/home/keyti/pic.png"}
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
