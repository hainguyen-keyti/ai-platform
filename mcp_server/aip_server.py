#!/usr/bin/env python3
"""An MCP server for the platform's modes: pictures with ChatGPT (/v1/images) and video scripts (/v1/scripts), with
ready recipes kept as files in presets/. chatgpt_images.py beside it is the name existing configs run.

An agent's host (Claude Code, Claude Desktop, any MCP client) starts it as a subprocess and talks to
it over stdio. It calls the platform with the person's own API key, made on the web's API page:

    AIP_API_KEY   the key (aip_...), required; never printed
    AIP_API_URL   the platform's api (default http://localhost:3000)
    AIP_SAVE_DIR  where pictures are saved when a call names no folder (default: <temp>/aip-pictures)

Six tools. list_sessions lists the key's named sessions; generate_image sends a prompt (and optionally a reference picture), waits for ChatGPT,
saves every picture it made and answers with their paths; generate_images does the same for a set of
prompts sent at once; get_image collects a request already sent, for a host that stopped waiting;
account_status says the credits left and whether ChatGPT is served; cancel_image cancels a request
sent by mistake, its credit given back (issue #20).
A picture is saved under its prompt's name with a record of it beside it, and the answer carries a
small preview of it for the agent to look at, and its facts as structured content (issue #19).
Under WSL a Windows path the agent gives is read where WSL sees it, and every saved picture is also
named by its Windows path. Install and register: README.md, "MCP server for ChatGPT pictures".
Issue #17.
"""

import base64
import http.client
import io
import json
import os
import platform
import re
import subprocess
import tempfile
import time
import tomllib
import unicodedata
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Annotated, List, Optional

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult, ImageContent, TextContent
from PIL import Image
# pydantic, which builds the output schemas, needs typing_extensions' TypedDict before Python 3.12.
from typing_extensions import TypedDict

API = os.environ.get("AIP_API_URL", "http://localhost:3000").rstrip("/")
KEY = os.environ.get("AIP_API_KEY", "")
POLL_SECONDS = float(os.environ.get("AIP_POLL_SECONDS", "3"))
SAVE_DIR = Path(os.environ.get("AIP_SAVE_DIR") or Path(tempfile.gettempdir()) / "aip-pictures")
# A picture usually takes about a minute and the platform gives up after five (docs/api-v1-images.md).
WAIT_SECONDS, MAX_WAIT_SECONDS = 420, 900
# The worker makes one ChatGPT picture at a time, so a set of twenty waits its turn picture by picture.
MAX_SET, SET_WAIT_SECONDS, MAX_SET_WAIT_SECONDS = 20, 1800, 3600
SCRIPT_WAIT_SECONDS, SCRIPT_MAX_WAIT_SECONDS = 600, 900
PRESETS_DIR = Path(__file__).resolve().parent / "presets"
MODES = ("image", "script")
# Claude Code counts a result's images against MAX_MCP_OUTPUT_TOKENS (25,000 by default): a preview is small.
PREVIEW_SIDE, SLUG_LENGTH = 512, 40
# The platform takes up to four reference pictures in one chatgpt request (issue #22).
MAX_REFERENCES = 4
LIVE = ("queued", "running")
WSL = "microsoft" in platform.release().lower()
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
WINDOWS_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")
# What this process sent, by request id: the prompt and the reference path, so get_image names the
# pictures of a request it did not wait for. A request sent before a restart is named "picture".
SENT = {}

mcp = MCPServer("aip-chatgpt-images", instructions=(
    "Makes pictures with ChatGPT on the AI Platform. Call generate_image with a prompt, and a "
    "reference picture's path when the picture should follow one, or generate_images with a list of "
    "prompts for a set; each answers with the saved files' paths and a small preview of each picture. "
    "A picture takes about a minute, and ChatGPT makes one at a time. If a request is still running, "
    "call get_image with its request id later. To change a picture already made, pass its request id "
    "as continue_from rather than sending the picture back. Every request of one API key goes into that "
    "key's own ChatGPT thread for the day, so ChatGPT sees the key's earlier pictures of the day and "
    "its pictures drift toward one look: for a varied set, name the face angle and the expression in "
    "every prompt. For a different person or character, pass a session name of its own, such as "
    "session=\"woman-a\" and session=\"woman-b\": each session is a ChatGPT thread that sees no other "
    "session's pictures and lasts across days, so the same name keeps the same character, and "
    "list_sessions says which there are. write_video_script writes a shot-by-shot script for an AI video "
    "model (flow, minimax_h3 or wan), each scene with its first-frame picture prompt and video prompt; with target "
    "production it writes a director's whole film instead, concept, screenplay, shot list and post-production, for no "
    "particular tool, and the director-* presets ask for one. list_presets shows ready recipes, and generate runs one. account_status says the credits left before a set; "
    "cancel_image cancels a request sent by mistake."))


class Picture(TypedDict):
    """One saved picture: the file, its Windows path under WSL, and the record kept beside it."""
    path: str
    windows_path: Optional[str]
    content_type: str
    bytes: int
    record: str


class Answer(TypedDict):
    """A request: done with its pictures, or still queued or running (then call get_image later). The
    conversation is its session's, or with no session the key's for the day: one ChatGPT thread."""
    request_id: str
    status: str
    pictures: List[Picture]
    text: str
    message: str
    conversation_id: Optional[str]
    session: Optional[str]


class SetRequest(TypedDict):
    """One prompt of a set: done, failed, cancelled, queued or running, refused, or not sent."""
    prompt: str
    request_id: Optional[str]
    status: str
    pictures: List[Picture]
    error: Optional[str]


class SetAnswer(TypedDict):
    """Every prompt of a set, in the order given, and the session they were sent to."""
    requests: List[SetRequest]
    message: str
    session: Optional[str]


class Session(TypedDict):
    """A named session of this key: its ChatGPT thread's conversation and what has gone into it."""
    name: str
    conversation_id: str
    requests: int
    pictures: int
    created_at: str
    last_used: Optional[str]


class Sessions(TypedDict):
    """This key's sessions on ChatGPT, the last used first."""
    sessions: List[Session]
    message: str


class Account(TypedDict):
    """The credits left today, when they come back (UTC), and whether a worker serves ChatGPT now."""
    credits_left: int
    credits_daily: Optional[int]
    refills_at: str
    chatgpt_served: bool
    pictures_last_3h: Optional[int]
    picture_budget: Optional[int]
    budget_free_at: Optional[str]
    waiting: int
    message: str


class Cancelled(TypedDict):
    """A request after cancel_image: cancelled, or as it already ended (done, failed, cancelled)."""
    request_id: str
    status: str
    message: str


def local_path(path: str, wsl: bool = WSL) -> str:
    """A path as this process can open it: under WSL, D:\\x\\y.png is /mnt/d/x/y.png."""
    found = WINDOWS_PATH.match(path) if wsl else None
    if not found:
        return path
    return "/mnt/{}/{}".format(found.group(1).lower(), found.group(2).replace("\\", "/"))


def windows_path(path: Path) -> Optional[str]:
    """Under WSL, the Windows path of a saved file (\\\\wsl.localhost\\...), for an agent on Windows."""
    if not WSL:
        return None
    ran = subprocess.run(["wslpath", "-w", str(path)], capture_output=True, text=True, timeout=10)
    if ran.returncode != 0:
        return None
    return ran.stdout.strip() or None


def slug(prompt: str) -> str:
    """A short ASCII name from a prompt: its Latin letters without their marks, cut at a word;
    "picture" when it has none."""
    plain = unicodedata.normalize("NFKD", prompt.replace("đ", "d").replace("Đ", "D"))
    words = re.findall(r"[a-z0-9]+", plain.encode("ascii", "ignore").decode().lower())
    name = words[0][:SLUG_LENGTH] if words else ""
    for word in words[1:]:
        if len(name) + 1 + len(word) > SLUG_LENGTH:
            break
        name += "-" + word
    return name or "picture"


class Unreachable(ToolError):
    """The platform did not answer, or answered 5xx. A request already sent is not lost by it: the api
    restarting (a code reload, Docker, WSL) took a whole set's answer with it, ids and all (stress test,
    2026-10-30), so whoever is waiting keeps waiting."""


def call(method: str, path: str, body: bytes = None, content_type: str = None):
    """(status, body bytes) of one call to the platform with the key; an error status is returned."""
    request = urllib.request.Request(API + path, data=body, method=method,
                                     headers={"Authorization": "Bearer " + KEY})
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (OSError, http.client.HTTPException) as exc:
        raise Unreachable("the platform at {} could not be reached: {}".format(API, getattr(exc, "reason", exc)))


def read_state(request_id: str) -> Optional[dict]:
    """A request's status; None while the platform cannot answer. Anything else it answers is final."""
    try:
        status, raw = call("GET", "/v1/images/{}".format(request_id))
    except Unreachable:
        return None
    if status >= 500:
        return None
    if status != 200:
        raise ToolError("request {} could not be read ({}): {}".format(request_id, status, detail(raw)))
    return json.loads(raw)


def detail(raw: bytes) -> str:
    try:
        said = json.loads(raw).get("detail")
    except (ValueError, AttributeError):
        said = None
    return str(said) if said else raw.decode(errors="replace")[:300]


def form(prompt: str, references: List[Path], continue_from: Optional[str] = None, session: Optional[str] = None):
    """multipart/form-data: the prompt, provider chatgpt, the request it continues if any (#21), its
    session if any (#28), and each reference picture as an `image` field, in order (#22)."""
    boundary = uuid.uuid4().hex
    body = b""
    fields = (("prompt", prompt), ("provider", "chatgpt")) + ((("continue_from", continue_from),)
                                                            if continue_from else ()) + (
        (("session", session),) if session is not None else ())
    for name, value in fields:
        body += ('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n'.format(boundary, name).encode()
                 + value.encode() + b"\r\n")
    for reference in references:
        body += ('--{}\r\nContent-Disposition: form-data; name="image"; filename="{}"\r\n'
                 'Content-Type: {}\r\n\r\n'.format(
                     boundary, reference.name, CONTENT_TYPES.get(reference.suffix.lower(), "application/octet-stream")
                 ).encode() + reference.read_bytes() + b"\r\n")
    return body + "--{}--\r\n".format(boundary).encode(), "multipart/form-data; boundary=" + boundary


def send(prompt: str, references: List[Path], continue_from: Optional[str] = None, session: Optional[str] = None):
    body, content_type = form(prompt, references, continue_from, session)
    return call("POST", "/v1/images", body, content_type)


def needs_key():
    if not KEY:
        raise ToolError("AIP_API_KEY is not set: make a key on the platform's web, page API, and give it to "
                        "this server in its environment")


def given_references(reference_path: Optional[str], reference_paths: Optional[List[str]]) -> List[str]:
    """The reference pictures asked for, reference_path first, at most MAX_REFERENCES (#22)."""
    given = ([reference_path] if reference_path else []) + list(reference_paths or [])
    if len(given) > MAX_REFERENCES:
        raise ToolError("at most {} reference pictures; {} were given".format(MAX_REFERENCES, len(given)))
    return given


def checked_references(given: List[str]) -> List[Path]:
    references = []
    for reference_path in given:
        reference = Path(local_path(reference_path))
        if not reference.is_file():
            raise ToolError("the reference picture {} is not there".format(reference_path))
        references.append(reference)
    return references


def preview(blob: bytes) -> ImageContent:
    """A small JPEG copy of a picture for the agent to look at; the saved file stays the original."""
    with Image.open(io.BytesIO(blob)) as picture:
        picture.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
        out = io.BytesIO()
        picture.convert("RGB").save(out, "JPEG", quality=80)
    return ImageContent(type="image", data=base64.b64encode(out.getvalue()).decode(), mime_type="image/jpeg")


def save(state: dict, folder: Path, prompt: Optional[str], given: List[str], with_preview: bool):
    """Download every picture of a done request into folder, each named by its prompt with its record
    beside it: (the pictures, their previews, a line for each picture no preview was made from)."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = "{}-{}".format(slug(prompt or ""), state["id"][:8])
    saved, shown, notes = [], [], []
    for number, picture in enumerate(state.get("images") or [], 1):
        status, blob = call("GET", picture["url"])
        if status >= 500:
            raise Unreachable("picture {} of request {} could not be downloaded yet ({})".format(
                number, state["id"], status))
        if status != 200:
            raise ToolError("picture {} of request {} could not be downloaded ({}): {}".format(
                number, state["id"], status, detail(blob)))
        path = folder / "{}-{}{}".format(stem, number, SUFFIXES.get(picture.get("content_type"), ""))
        path.write_bytes(blob)
        kept = folder / "{}-{}.json".format(stem, number)
        kept.write_text(json.dumps({
            "prompt": prompt, "request_id": state["id"], "reference_path": given[0] if given else None,
            "reference_paths": given,
            "continued_from": state.get("continued_from"), "session": state.get("session"),
            "created_at": state.get("created_at"), "finished_at": state.get("finished_at"),
            "text": state.get("text") or "", "picture": path.name,
            "content_type": picture.get("content_type"), "bytes": len(blob)}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        saved.append(Picture(path=str(path), windows_path=windows_path(path),
                             content_type=picture.get("content_type") or "", bytes=len(blob), record=str(kept)))
        if with_preview:
            try:
                shown.append(preview(blob))
            except (OSError, ValueError, Image.DecompressionBombError) as exc:
                notes.append("no preview for picture {}: {}".format(number, exc))
    if not saved:
        raise ToolError("request {} is done but no picture came back{}".format(
            state["id"], ": " + state["text"] if state.get("text") else ""))
    return saved, shown, notes


def listed(saved: List[Picture], notes: List[str]) -> List[str]:
    lines = ["- {}{}".format(p["path"], " (Windows: {})".format(p["windows_path"]) if p["windows_path"] else "")
             for p in saved]
    return lines + ["  ({})".format(note) for note in notes]


def later(request_id: str, budget_free_at: Optional[str] = None) -> str:
    if budget_free_at:
        return ("it waits for the platform's own picture budget (a pace this platform keeps, not a limit ChatGPT "
                "reported): the account it runs on has made all the pictures allowed in three hours, and has room "
                "again at about {} (UTC). Nothing is wrong and sending it again would only queue another; call "
                "get_image with request_id \"{}\" after that to collect its pictures".format(budget_free_at, request_id))
    return "call get_image with request_id \"{}\" in a minute to collect its pictures".format(request_id)


def answered(message: str, data: dict, shown: list) -> CallToolResult:
    """The words for any client, the previews for the model, and the same facts as structured content."""
    return CallToolResult(content=[TextContent(type="text", text=message)] + shown, structured_content=data)


async def collect(request_id: str, folder: Path, wait: float, ctx: Optional[Context],
                  with_preview: bool) -> CallToolResult:
    """Ask for the request until it ends or `wait` seconds pass; save what a done one made."""
    prompt, given = SENT.get(request_id, (None, []))
    began = time.monotonic()
    state = None
    while True:
        now = await anyio.to_thread.run_sync(read_state, request_id)
        # The last status known stands while the platform cannot answer.
        state, answering = now or state, now is not None
        if answering and state.get("status") == "done":
            try:
                saved, shown, notes = await anyio.to_thread.run_sync(save, state, folder, prompt, given, with_preview)
            except Unreachable:
                answering = False
            else:
                words = "\nChatGPT said: {}".format(state["text"]) if state.get("text") else ""
                where = ' in session "{}"'.format(state["session"]) if state.get("session") else ""
                message = "ChatGPT made {} picture(s) for request {}{}, saved as:\n{}{}".format(
                    len(saved), request_id, where, "\n".join(listed(saved, notes)), words)
                return answered(message, Answer(request_id=request_id, status="done", pictures=saved,
                                                text=state.get("text") or "", message=message,
                                                conversation_id=state.get("conversation_id"),
                                                session=state.get("session")), shown)
        if answering and state.get("status") in ("failed", "cancelled"):
            raise ToolError("request {} {}: {} (the credit was given back)".format(
                request_id, state["status"], state.get("error") or "no reason given"))
        known = state or {}
        waited = time.monotonic() - began
        if waited >= wait:
            message = "Request {} is still {} after {:.0f}s: {}.".format(
                request_id, known.get("status") or "not known", waited, later(request_id, known.get("budget_free_at")))
            if not answering:
                message = "The platform does not answer just now, so {}".format(message[0].lower() + message[1:])
            return answered(message, Answer(request_id=request_id, status=known.get("status") or "unknown",
                                            pictures=[], text="", message=message,
                                            conversation_id=known.get("conversation_id"),
                                            session=known.get("session")), [])
        if ctx is not None:
            await ctx.report_progress(min(waited, wait), wait, message="ChatGPT is {}".format(
                ("{}, waiting for the picture budget until about {} (UTC)".format(
                    known.get("status"), known["budget_free_at"]) if known.get("budget_free_at") else known.get("status"))
                if answering else "not answering, still waiting"))
        await anyio.sleep(POLL_SECONDS)


@mcp.tool()
async def generate_image(prompt: str, ctx: Context, reference_path: Optional[str] = None,
                         save_dir: Optional[str] = None, wait_seconds: int = WAIT_SECONDS,
                         preview: bool = True, continue_from: Optional[str] = None,
                         reference_paths: Optional[List[str]] = None,
                         session: Optional[str] = None) -> Annotated[CallToolResult, Answer]:
    """Make a picture with ChatGPT from a prompt, optionally following reference pictures (PNG, JPEG
    or WEBP; reference_path for one, reference_paths for up to 4 in order, e.g. "put the character of
    the first into the scene of the second"; all together under 10 MB), and save it named by its
    prompt, with a .json record of it beside it.
    To change a picture already made ("brighter", "the same cat, sleeping"), pass its request id as
    continue_from instead of sending the picture back: the prompt goes into the ChatGPT thread that
    made it, which sees that picture and what was asked before. To keep a person or character apart
    from the others, give it a session name of its own (session="woman-a"): the same name goes into the
    same ChatGPT thread on any day, another name into a thread that sees none of its pictures; with
    continue_from it is left out, as the request stays in its own session. Waits for it (about a minute, up to
    wait_seconds) and answers with the saved files' paths and a small preview of each picture
    (preview=False leaves it out); a request still running then is collected with get_image. Each
    request costs one credit on the platform; a failed one gives it back."""
    needs_key()
    given = given_references(reference_path, reference_paths)
    references = checked_references(given)
    status, raw = await anyio.to_thread.run_sync(send, prompt, references, continue_from, session)
    if status != 202:
        raise ToolError("the platform refused the request ({}): {}".format(status, detail(raw)))
    request_id = json.loads(raw)["id"]
    SENT[request_id] = (prompt, given)
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    return await collect(request_id, folder, max(1, min(int(wait_seconds), MAX_WAIT_SECONDS)), ctx, preview)


@mcp.tool()
async def generate_images(prompts: List[str], ctx: Context, reference_path: Optional[str] = None,
                          save_dir: Optional[str] = None, wait_seconds: int = SET_WAIT_SECONDS,
                          preview: bool = True, continue_from: Optional[str] = None,
                          reference_paths: Optional[List[str]] = None,
                          session: Optional[str] = None) -> Annotated[CallToolResult, SetAnswer]:
    """Make a set of pictures with ChatGPT, one request per prompt (1 to 20), all following the same
    reference pictures when given (reference_path, or reference_paths for up to 4), and all continuing
    the request continue_from names when one is given (each then goes into that request's ChatGPT
    thread, one after another), or all going into the named session when one is given: a set is one
    session, so a set of different people is one call per person. Sends them all at once; ChatGPT makes them one after another, about a
    minute each. Reports how many are done as it goes, and answers once all have ended or
    wait_seconds has passed (at most 3600) with each prompt's files and preview, its failure reason,
    or its request id for get_image when it is still running. One failed prompt fails only itself; a
    refusal when sending (no credit left, say) stops sending the rest. One credit per request sent."""
    needs_key()
    if not 1 <= len(prompts) <= MAX_SET:
        raise ToolError("send 1 to {} prompts; this set has {}".format(MAX_SET, len(prompts)))
    blank = [str(n) for n, prompt in enumerate(prompts, 1) if not prompt.strip()]
    if blank:
        raise ToolError("prompt {} of the set is blank".format(", ".join(blank)))
    given = given_references(reference_path, reference_paths)
    references = checked_references(given)
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    items = [SetRequest(prompt=prompt, request_id=None, status="not sent", pictures=[], error=None)
             for prompt in prompts]
    for item in items:
        try:
            status, raw = await anyio.to_thread.run_sync(send, item["prompt"], references, continue_from, session)
        except Unreachable as exc:
            # Whether this one arrived cannot be told, and those sent before it must not be lost.
            item.update(status="unknown", error=str(exc))
            break
        if status != 202:
            item.update(status="refused", error="the platform refused it ({}): {}".format(status, detail(raw)))
            break
        item.update(request_id=json.loads(raw)["id"], status="queued")
        SENT[item["request_id"]] = (item["prompt"], given)
    if items[0]["status"] in ("refused", "unknown"):
        raise ToolError("the set's first prompt did not go, so none was sent: " + items[0]["error"])

    sent = [item for item in items if item["request_id"]]
    wait = max(1, min(int(wait_seconds), MAX_SET_WAIT_SECONDS))
    shown, notes, budget = [], {}, {}
    began = time.monotonic()
    while True:
        for item in [item for item in sent if item["status"] in LIVE]:
            try:
                state = await anyio.to_thread.run_sync(read_state, item["request_id"])
            except ToolError as exc:
                item.update(status="unread", error=str(exc))
                continue
            if state is None:
                continue
            if state.get("status") == "done":
                try:
                    saved, more, notes[item["request_id"]] = await anyio.to_thread.run_sync(
                        save, state, folder, item["prompt"], given, preview)
                except Unreachable:
                    continue
                except ToolError as exc:
                    item.update(status="unsaved", error=str(exc))
                    continue
                item.update(status="done", pictures=saved)
                shown += more
            elif state.get("status") in ("failed", "cancelled"):
                item.update(status=state["status"],
                            error="{} (the credit was given back)".format(state.get("error") or "no reason given"))
            else:
                item["status"] = state.get("status") or item["status"]
                budget[item["request_id"]] = state.get("budget_free_at")
        ended = sum(1 for item in sent if item["status"] not in LIVE)
        if ended == len(sent) or time.monotonic() - began >= wait:
            break
        await ctx.report_progress(ended, len(sent), message="{} of {} done".format(ended, len(sent)))
        await anyio.sleep(POLL_SECONDS)

    lines = []
    for number, item in enumerate(items, 1):
        head = "{}. \"{}\": ".format(number, item["prompt"])
        if item["status"] == "done":
            lines += [head + "done, saved as:"] + listed(item["pictures"], notes.get(item["request_id"], []))
        elif item["status"] in LIVE:
            lines.append(head + "still {} as request {}: {}".format(item["status"], item["request_id"],
                                                                  later(item["request_id"], budget.get(item["request_id"]))))
        elif item["status"] == "unread":
            lines.append(head + "request {}: {}; {}".format(item["request_id"], item["error"],
                                                            later(item["request_id"])))
        elif item["status"] == "not sent":
            lines.append(head + "not sent, as sending stopped at an earlier prompt")
        else:
            lines.append(head + "{}: {}".format(item["status"], item["error"]))
    done = sum(1 for item in items if item["status"] == "done")
    where = ' in session "{}"'.format(" ".join(session.split()).casefold()) if session else ""
    message = "{} of {} prompts done{} ({} sent).\n{}".format(done, len(items), where, len(sent), "\n".join(lines))
    return answered(message, SetAnswer(requests=items, message=message, session=session), shown)


@mcp.tool()
async def list_sessions() -> Annotated[CallToolResult, Sessions]:
    """This key's named sessions on ChatGPT, the last used first, with how many requests and pictures
    each holds. Use it to carry on with a character made earlier, by passing its name as session."""
    needs_key()
    status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/sessions?provider=chatgpt")
    if status != 200:
        raise ToolError("the sessions could not be read ({}): {}".format(status, detail(raw)))
    rows = json.loads(raw).get("sessions") or []
    found = [Session(name=r["name"], conversation_id=r["conversation_id"], requests=r["requests"],
                     pictures=r["pictures"], created_at=r["created_at"], last_used=r.get("last_used")) for r in rows]
    lines = ['- "{}": {} picture(s) from {} request(s), last used {}'.format(
        s["name"], s["pictures"], s["requests"], s["last_used"] or "never") for s in found]
    message = "\n".join(["{} session(s) on this key:".format(len(found))] + lines) if found else (
        "This key has no named session yet.")
    return answered(message, Sessions(sessions=found, message=message), [])


@mcp.tool()
async def account_status() -> Annotated[CallToolResult, Account]:
    """How many credits are left today and when they come back, whether ChatGPT is served right now, how
    much of the worker's picture budget is used (40 pictures in three hours by default; past it requests
    wait in the queue) and how many requests are waiting. Worth asking before a set: each request takes one
    credit, and none is sent while nobody serves ChatGPT."""
    needs_key()
    status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/account")
    if status != 200:
        raise ToolError("the account could not be read ({}): {}".format(status, detail(raw)))
    account = json.loads(raw)
    status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/providers")
    if status != 200:
        raise ToolError("the providers could not be read ({}): {}".format(status, detail(raw)))
    chatgpt = next((p for p in json.loads(raw).get("providers") or [] if p.get("name") == "chatgpt"), {})
    served = bool(chatgpt.get("served"))
    message = "{} of {} credits left today; they come back at {} (UTC). ChatGPT is {}.".format(
        account["credits_left"], account.get("credits_daily"), account["refills_at"],
        "served right now" if served else "not served right now, so a request would be refused (503) until it is")
    used, budget, free_at = chatgpt.get("pictures_last_3h"), chatgpt.get("picture_budget"), chatgpt.get("budget_free_at")
    if budget:
        message += " {} of the {} pictures the worker makes in three hours are used.".format(used, budget)
    if free_at:
        message += " The budget is spent: requests wait in the queue until about {} (UTC).".format(free_at)
    if chatgpt.get("waiting"):
        message += " {} request(s) are waiting.".format(chatgpt["waiting"])
    return answered(message, Account(credits_left=account["credits_left"], credits_daily=account.get("credits_daily"),
                                     refills_at=account["refills_at"], chatgpt_served=served, pictures_last_3h=used,
                                     picture_budget=budget, budget_free_at=free_at,
                                     waiting=chatgpt.get("waiting") or 0, message=message), [])


@mcp.tool()
async def cancel_image(request_id: str) -> Annotated[CallToolResult, Cancelled]:
    """Cancel a request generate_image or generate_images sent, queued or running, and get its credit
    back. A request already over is left as it ended."""
    needs_key()
    status, raw = await anyio.to_thread.run_sync(call, "POST", "/v1/images/{}/cancel".format(request_id))
    if status != 200:
        raise ToolError("request {} could not be cancelled ({}): {}".format(request_id, status, detail(raw)))
    state = json.loads(raw)
    if state.get("status") == "cancelled":
        message = "Request {} is cancelled; its credit was given back.".format(request_id)
    else:
        message = "Request {} had already ended as {}; nothing changed.".format(request_id, state.get("status"))
    return answered(message, Cancelled(request_id=request_id, status=state.get("status") or "", message=message), [])


@mcp.tool()
async def get_image(request_id: str, ctx: Context, save_dir: Optional[str] = None,
                    preview: bool = True) -> Annotated[CallToolResult, Answer]:
    """Collect the pictures of a request generate_image or generate_images already sent: saves them
    and answers with their paths and previews when it is done, says so when it is still running, and
    gives its reason when it failed."""
    needs_key()
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    return await collect(request_id, folder, 0, ctx, preview)


class Script(TypedDict):
    """A request for a video script: done with the script and its files, or still queued or running."""
    request_id: str
    status: str
    target: Optional[str]
    script: Optional[dict]
    json_path: Optional[str]
    markdown_path: Optional[str]
    session: Optional[str]
    message: str


class Target(TypedDict):
    """A video model a script can be written for, and what it takes."""
    name: str
    label: str
    min_seconds: float
    max_seconds: float
    dialogue: bool
    negative_prompt: bool
    source: str


class Targets(TypedDict):
    targets: List[Target]
    message: str


class Preset(TypedDict):
    """A ready recipe: what it makes, and what must be filled in."""
    id: str
    mode: str
    title: str
    description: str
    inputs: dict


class Presets(TypedDict):
    presets: List[Preset]
    message: str


def clock(seconds: float) -> str:
    whole = int(seconds)
    return "{:02d}:{:02d}".format(whole // 60, whole % 60) + (".{}".format(int(round((seconds - whole) * 10))) if seconds != whole else "")


def production_markdown(script: dict) -> str:
    """A director's whole film for a crew and an editor to read, concept to post-production."""
    concept, post = script["concept"], script["post"]
    lines = ["# {}".format(script["title"]), "", "{}s in all.".format(script["total_seconds"]), "", "## Concept", ""]
    lines += ["- **{}**: {}".format(label, concept[field]) for label, field in (
        ("Idea", "idea"), ("Audience", "audience"), ("Message", "message"), ("Tone", "tone"), ("Visual style", "visual_style"), ("Palette", "palette"), ("Synopsis", "synopsis"))]
    if script.get("characters"):
        lines += ["", "## Characters", ""] + ["- **{}**: {}".format(c["name"], c["description"]) for c in script["characters"]]
    lines += ["", "## Settings", ""] + ["- **{}**: {}".format(s["name"], s["description"]) for s in script["settings"]]
    lines += ["", "## Screenplay and shots"]
    for scene in script["scenes"]:
        lines += ["", "### Scene {}: {}".format(scene["number"], scene["title"]), "", "{}. {}".format(scene["location"], scene["purpose"]), "", scene["description"]]
        for shot in scene["shots"]:
            lines += ["", "**Shot {}, {} to {} ({}s)**".format(shot["number"], clock(shot["start_seconds"]), clock(shot["end_seconds"]), shot["duration_seconds"]), ""]
            lines += ["- {}: {}".format(label, shot[field]) for label, field in (
                ("Shot size", "shot_size"), ("Angle", "angle"), ("Lens", "lens"), ("Movement", "movement"), ("Composition", "composition"), ("Action", "action"),
                ("Lighting", "lighting"), ("Color", "color"), ("Dialogue", "dialogue"), ("Voice-over", "voice_over"), ("Sound", "sound"), ("On-screen text", "on_screen_text"),
                ("Cut to next", "transition")) if shot.get(field)]
    lines += ["", "## Post-production", ""]
    lines += ["- **{}**: {}".format(label, post[field]) for label, field in (
        ("Pacing", "pacing"), ("Transitions", "transitions"), ("Color grade", "color_grade"), ("Music", "music"), ("Sound mix", "sound_mix"), ("Subtitles", "subtitles"), ("Format", "format"))]
    return "\n".join(lines) + "\n"


def script_markdown(script: dict) -> str:
    """The script for a person to read and paste from, scene by scene."""
    if script.get("post"):
        return production_markdown(script)
    lines = ["# {}".format(script["title"]), "", "For {}, {}s in all.".format(script["target"], script["total_seconds"]), ""]
    direction = script.get("direction") or {}
    for label, field in (("Concept", "concept"), ("Hook", "hook"), ("Visual style", "visual_style"), ("Palette", "palette")):
        if direction.get(field):
            lines.append("- **{}**: {}".format(label, direction[field]))
    if direction:
        lines.append("")
    for character in script.get("characters") or []:
        lines.append("- **{}**: {}".format(character["name"], character["description"]))
    for scene in script["scenes"]:
        lines += ["", "## Scene {} ({}s)".format(scene["number"], scene["duration_seconds"]), "", scene["description"], "",
                  "Camera: {}".format(scene["camera"])]
        for label, field in (("Color", "color"), ("Lighting", "lighting"), ("Sound", "sound")):
            if scene.get(field):
                lines += ["", "{}: {}".format(label, scene[field])]
        if scene.get("dialogue"):
            lines += ["", "Dialogue: {}".format(scene["dialogue"])]
        lines += ["", "First frame:", "", "```text", scene["image_prompt"], "```", "", "Video prompt:", "", "```text", scene["video_prompt"], "```"]
        if scene.get("negative_prompt"):
            lines += ["", "Negative prompt:", "", "```text", scene["negative_prompt"], "```"]
    return "\n".join(lines) + "\n"


async def collect_script(request_id: str, folder: Path, wait: float, ctx: Optional[Context]) -> CallToolResult:
    """Ask for the script until it ends or `wait` seconds pass; save a done one as JSON and Markdown."""
    began = time.monotonic()
    state, answering = None, False
    while True:
        try:
            status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/scripts/{}".format(request_id))
        except Unreachable:
            status, raw = 0, b""
        answering = status == 200
        if status not in (0, 200) and status < 500:
            raise ToolError("script request {} could not be read ({}): {}".format(request_id, status, detail(raw)))
        state = json.loads(raw) if answering else state
        known = state or {}
        if answering and known.get("status") in ("failed", "cancelled"):
            raise ToolError("script request {} {}: {} (the credit was given back)".format(
                request_id, known["status"], known.get("error") or "no reason given"))
        if answering and known.get("status") == "done":
            script = known["script"]
            folder.mkdir(parents=True, exist_ok=True)
            stem = folder / "{}-{}".format(slug(script["title"]), request_id[:8])
            as_json, as_markdown = stem.with_suffix(".json"), stem.with_suffix(".md")
            as_json.write_text(json.dumps(script, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            as_markdown.write_text(script_markdown(script), encoding="utf-8")
            message = '"{}", {} scene(s), {}s, for {}, saved as:\n- {}\n- {}'.format(
                script["title"], len(script["scenes"]), script["total_seconds"], known.get("target"), as_markdown, as_json)
            return answered(message, Script(request_id=request_id, status="done", target=known.get("target"), script=script,
                                            json_path=str(as_json), markdown_path=str(as_markdown), session=known.get("session"),
                                            message=message), [])
        waited = time.monotonic() - began
        if waited >= wait:
            message = "Script request {} is still {} after {:.0f}s: call get_video_script with its id later.".format(
                request_id, known.get("status") or "not known", waited)
            return answered(message, Script(request_id=request_id, status=known.get("status") or "unknown", target=known.get("target"),
                                            script=None, json_path=None, markdown_path=None, session=known.get("session"),
                                            message=message), [])
        if ctx is not None:
            await ctx.report_progress(min(waited, wait), wait, message="the script is {}".format(known.get("status") or "not known"))
        await anyio.sleep(POLL_SECONDS)


async def send_script(brief, target, ctx, scenes, total_seconds, language, provider, session, save_dir, wait_seconds) -> CallToolResult:
    needs_key()
    body = {"brief": brief, "target": target, "provider": provider, "language": language}
    for name, value in (("scenes", scenes), ("total_seconds", total_seconds), ("session", session)):
        if value is not None:
            body[name] = value
    status, raw = await anyio.to_thread.run_sync(call, "POST", "/v1/scripts", json.dumps(body).encode(), "application/json")
    if status != 202:
        raise ToolError("the platform refused the script ({}): {}".format(status, detail(raw)))
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    return await collect_script(json.loads(raw)["id"], folder, max(1, min(int(wait_seconds), SCRIPT_MAX_WAIT_SECONDS)), ctx)


@mcp.tool()
async def write_video_script(brief: str, target: str, ctx: Context, scenes: Optional[int] = None,
                             total_seconds: Optional[int] = None, language: str = "vi", provider: str = "grok",
                             session: Optional[str] = None, save_dir: Optional[str] = None,
                             wait_seconds: int = SCRIPT_WAIT_SECONDS) -> Annotated[CallToolResult, Script]:
    """Write a shot-by-shot video script for an AI video model. target is flow (Google Flow, Veo: 8s clips),
    minimax_h3 (5 to 15s) or wan (Wan 2.2: under 5s, silent); list_script_targets says what each takes. The script
    comes with its direction (concept, hook, visual style, palette), and each scene with its duration, camera, color,
    lighting, sound (none on a silent target), dialogue, a first-frame image_prompt and a video_prompt written the way
    that model reads them; the script is checked against the target, and one that does not fit fails and gives
    its credit back. Saved as Markdown to read and paste from, and JSON. Written by Grok unless provider says
    otherwise. Each request costs one credit. A script still running is collected with get_video_script.
    target production is a director's whole film instead, for no particular tool: concept, characters, settings, scenes
    of timed shots of any length (size, angle, lens, movement, composition, action, light, color, sound, cut, lines,
    on-screen text) and post-production; total_seconds is held to."""
    return await send_script(brief, target, ctx, scenes, total_seconds, language, provider, session, save_dir, wait_seconds)


@mcp.tool()
async def get_video_script(request_id: str, ctx: Context, save_dir: Optional[str] = None) -> Annotated[CallToolResult, Script]:
    """Collect a script write_video_script already sent, or say it is still running or why it failed."""
    needs_key()
    return await collect_script(request_id, Path(local_path(save_dir)) if save_dir else SAVE_DIR, 0, ctx)


@mcp.tool()
async def list_script_targets() -> Annotated[CallToolResult, Targets]:
    """The video models a script can be written for, and what each takes."""
    needs_key()
    status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/script-targets")
    if status != 200:
        raise ToolError("the script targets could not be read ({}): {}".format(status, detail(raw)))
    targets = json.loads(raw)["targets"]
    message = "\n".join("- {}: {}, {} to {}s".format(t["name"], t["label"], t["min_seconds"], t["max_seconds"]) for t in targets)
    return answered(message, Targets(targets=targets, message=message), [])


def load_presets(folder: Path = PRESETS_DIR) -> dict:
    """Every preset in the folder, by id. A file that is not a whole preset is an error, not a preset quietly gone."""
    found = {}
    for path in sorted(folder.glob("*.toml")):
        preset = tomllib.loads(path.read_text(encoding="utf-8"))
        missing = [field for field in ("id", "mode", "title", "description", "template") if not preset.get(field)]
        if missing or preset.get("mode") not in MODES:
            raise ToolError("preset {} is not whole: missing {}, mode {!r}".format(path.name, missing, preset.get("mode")))
        if preset["mode"] == "script" and not preset.get("target"):
            raise ToolError("script preset {} names no target".format(path.name))
        found[preset["id"]] = preset
    return found


def filled(preset: dict, given: dict) -> str:
    """The preset's template with its inputs: defaults where left out; a missing or unknown one is refused."""
    inputs = preset.get("inputs") or {}
    unknown = sorted(set(given) - set(inputs))
    if unknown:
        raise ToolError("preset {} has no input {}; it takes {}".format(preset["id"], ", ".join(unknown), ", ".join(inputs)))
    values = {name: given.get(name, spec.get("default")) for name, spec in inputs.items()}
    missing = [name for name, value in values.items() if value in (None, "")]
    if missing:
        raise ToolError("preset {} needs {}".format(preset["id"], ", ".join(missing)))
    return preset["template"].format(**values)


@mcp.tool()
async def list_presets() -> Annotated[CallToolResult, Presets]:
    """The ready recipes generate can run: what each makes and what it asks for."""
    presets = [Preset(id=p["id"], mode=p["mode"], title=p["title"], description=p["description"], inputs=p.get("inputs") or {})
               for p in load_presets().values()]
    message = "\n".join("- {} ({}): {} Inputs: {}".format(p["id"], p["mode"], p["description"], ", ".join(p["inputs"]) or "none")
                        for p in presets) or "No preset yet."
    return answered(message, Presets(presets=presets, message=message), [])


@mcp.tool()
async def generate(preset: str, inputs: dict, ctx: Context, session: Optional[str] = None, save_dir: Optional[str] = None,
                   reference_path: Optional[str] = None) -> CallToolResult:
    """Run a ready recipe from list_presets: mode image makes a picture, mode script writes a video script. inputs fills
    the recipe's blanks. A preset that keeps a character takes its session from that input unless session is given."""
    presets = load_presets()
    if preset not in presets:
        raise ToolError("no preset {}; there are {}".format(preset, ", ".join(presets) or "none"))
    chosen = presets[preset]
    text = filled(chosen, inputs)
    named = session or inputs.get(chosen.get("session_input") or "")
    if chosen["mode"] == "image":
        return await generate_image(text, ctx, reference_path=reference_path, save_dir=save_dir, session=named)
    if reference_path:
        raise ToolError("preset {} writes a script and takes no reference picture".format(preset))
    total = chosen.get("total_seconds")
    if chosen.get("seconds_input"):
        name = chosen["seconds_input"]
        value = inputs.get(name, chosen["inputs"][name].get("default"))
        if not str(value).isdigit():
            raise ToolError("preset {} needs {} as a whole number of seconds, not {!r}".format(preset, name, value))
        total = int(value)
    return await send_script(text, chosen["target"], ctx, chosen.get("scenes"), total, chosen.get("language", "vi"),
                             chosen.get("provider", "grok"), named, save_dir, SCRIPT_WAIT_SECONDS)


if __name__ == "__main__":
    mcp.run()
