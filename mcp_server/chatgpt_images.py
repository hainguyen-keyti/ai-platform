#!/usr/bin/env python3
"""An MCP server that makes pictures with ChatGPT through the platform's image API (/v1/images).

An agent's host (Claude Code, Claude Desktop, any MCP client) starts it as a subprocess and talks to
it over stdio. It calls the platform with the person's own API key, made on the web's API page:

    AIP_API_KEY   the key (aip_...), required; never printed
    AIP_API_URL   the platform's api (default http://localhost:3000)
    AIP_SAVE_DIR  where pictures are saved when a call names no folder (default: <temp>/aip-pictures)

Five tools. generate_image sends a prompt (and optionally a reference picture), waits for ChatGPT,
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
import io
import json
import os
import platform
import re
import subprocess
import tempfile
import time
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
# Claude Code counts a result's images against MAX_MCP_OUTPUT_TOKENS (25,000 by default): a preview is small.
PREVIEW_SIDE, SLUG_LENGTH = 512, 40
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
    "call get_image with its request id later. account_status says the credits left before a set; "
    "cancel_image cancels a request sent by mistake."))


class Picture(TypedDict):
    """One saved picture: the file, its Windows path under WSL, and the record kept beside it."""
    path: str
    windows_path: Optional[str]
    content_type: str
    bytes: int
    record: str


class Answer(TypedDict):
    """A request: done with its pictures, or still queued or running (then call get_image later)."""
    request_id: str
    status: str
    pictures: List[Picture]
    text: str
    message: str


class SetRequest(TypedDict):
    """One prompt of a set: done, failed, cancelled, queued or running, refused, or not sent."""
    prompt: str
    request_id: Optional[str]
    status: str
    pictures: List[Picture]
    error: Optional[str]


class SetAnswer(TypedDict):
    """Every prompt of a set, in the order given."""
    requests: List[SetRequest]
    message: str


class Account(TypedDict):
    """The credits left today, when they come back (UTC), and whether a worker serves ChatGPT now."""
    credits_left: int
    credits_daily: Optional[int]
    refills_at: str
    chatgpt_served: bool
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
    except urllib.error.URLError as exc:
        raise ToolError("the platform at {} could not be reached: {}".format(API, exc.reason))


def detail(raw: bytes) -> str:
    try:
        said = json.loads(raw).get("detail")
    except (ValueError, AttributeError):
        said = None
    return str(said) if said else raw.decode(errors="replace")[:300]


def form(prompt: str, reference: Optional[Path]):
    """multipart/form-data: the prompt, provider chatgpt, and the reference picture as `image`."""
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in (("prompt", prompt), ("provider", "chatgpt")):
        body += ('--{}\r\nContent-Disposition: form-data; name="{}"\r\n\r\n'.format(boundary, name).encode()
                 + value.encode() + b"\r\n")
    if reference is not None:
        body += ('--{}\r\nContent-Disposition: form-data; name="image"; filename="{}"\r\n'
                 'Content-Type: {}\r\n\r\n'.format(
                     boundary, reference.name, CONTENT_TYPES.get(reference.suffix.lower(), "application/octet-stream")
                 ).encode() + reference.read_bytes() + b"\r\n")
    return body + "--{}--\r\n".format(boundary).encode(), "multipart/form-data; boundary=" + boundary


def send(prompt: str, reference: Optional[Path]):
    body, content_type = form(prompt, reference)
    return call("POST", "/v1/images", body, content_type)


def needs_key():
    if not KEY:
        raise ToolError("AIP_API_KEY is not set: make a key on the platform's web, page API, and give it to "
                        "this server in its environment")


def checked_reference(reference_path: Optional[str]) -> Optional[Path]:
    if not reference_path:
        return None
    reference = Path(local_path(reference_path))
    if not reference.is_file():
        raise ToolError("the reference picture {} is not there".format(reference_path))
    return reference


def preview(blob: bytes) -> ImageContent:
    """A small JPEG copy of a picture for the agent to look at; the saved file stays the original."""
    with Image.open(io.BytesIO(blob)) as picture:
        picture.thumbnail((PREVIEW_SIDE, PREVIEW_SIDE))
        out = io.BytesIO()
        picture.convert("RGB").save(out, "JPEG", quality=80)
    return ImageContent(type="image", data=base64.b64encode(out.getvalue()).decode(), mime_type="image/jpeg")


def save(state: dict, folder: Path, prompt: Optional[str], reference_path: Optional[str], with_preview: bool):
    """Download every picture of a done request into folder, each named by its prompt with its record
    beside it: (the pictures, their previews, a line for each picture no preview was made from)."""
    folder.mkdir(parents=True, exist_ok=True)
    stem = "{}-{}".format(slug(prompt or ""), state["id"][:8])
    saved, shown, notes = [], [], []
    for number, picture in enumerate(state.get("images") or [], 1):
        status, blob = call("GET", picture["url"])
        if status != 200:
            raise ToolError("picture {} of request {} could not be downloaded ({}): {}".format(
                number, state["id"], status, detail(blob)))
        path = folder / "{}-{}{}".format(stem, number, SUFFIXES.get(picture.get("content_type"), ""))
        path.write_bytes(blob)
        kept = folder / "{}-{}.json".format(stem, number)
        kept.write_text(json.dumps({
            "prompt": prompt, "request_id": state["id"], "reference_path": reference_path,
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


def later(request_id: str) -> str:
    return "call get_image with request_id \"{}\" in a minute to collect its pictures".format(request_id)


def answered(message: str, data: dict, shown: list) -> CallToolResult:
    """The words for any client, the previews for the model, and the same facts as structured content."""
    return CallToolResult(content=[TextContent(type="text", text=message)] + shown, structured_content=data)


async def collect(request_id: str, folder: Path, wait: float, ctx: Optional[Context],
                  with_preview: bool) -> CallToolResult:
    """Ask for the request until it ends or `wait` seconds pass; save what a done one made."""
    prompt, reference_path = SENT.get(request_id, (None, None))
    began = time.monotonic()
    while True:
        status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/images/{}".format(request_id))
        if status != 200:
            raise ToolError("request {} could not be read ({}): {}".format(request_id, status, detail(raw)))
        state = json.loads(raw)
        if state.get("status") == "done":
            saved, shown, notes = await anyio.to_thread.run_sync(save, state, folder, prompt, reference_path,
                                                                 with_preview)
            words = "\nChatGPT said: {}".format(state["text"]) if state.get("text") else ""
            message = "ChatGPT made {} picture(s) for request {}, saved as:\n{}{}".format(
                len(saved), request_id, "\n".join(listed(saved, notes)), words)
            return answered(message, Answer(request_id=request_id, status="done", pictures=saved,
                                            text=state.get("text") or "", message=message), shown)
        if state.get("status") in ("failed", "cancelled"):
            raise ToolError("request {} {}: {} (the credit was given back)".format(
                request_id, state["status"], state.get("error") or "no reason given"))
        waited = time.monotonic() - began
        if waited >= wait:
            message = "Request {} is still {} after {:.0f}s: {}.".format(
                request_id, state.get("status"), waited, later(request_id))
            return answered(message, Answer(request_id=request_id, status=state.get("status") or "running",
                                            pictures=[], text="", message=message), [])
        if ctx is not None:
            await ctx.report_progress(min(waited, wait), wait, message="ChatGPT is {}".format(state.get("status")))
        await anyio.sleep(POLL_SECONDS)


@mcp.tool()
async def generate_image(prompt: str, ctx: Context, reference_path: Optional[str] = None,
                         save_dir: Optional[str] = None, wait_seconds: int = WAIT_SECONDS,
                         preview: bool = True) -> Annotated[CallToolResult, Answer]:
    """Make a picture with ChatGPT from a prompt, optionally following a reference picture (PNG, JPEG
    or WEBP, at most 10 MB), and save it named by its prompt, with a .json record of it beside it.
    Waits for it (about a minute, up to wait_seconds) and answers with the saved files' paths and a
    small preview of each picture (preview=False leaves it out); a request still running then is
    collected with get_image. Each request costs one credit on the platform; a failed one gives it back."""
    needs_key()
    reference = checked_reference(reference_path)
    status, raw = await anyio.to_thread.run_sync(send, prompt, reference)
    if status != 202:
        raise ToolError("the platform refused the request ({}): {}".format(status, detail(raw)))
    request_id = json.loads(raw)["id"]
    SENT[request_id] = (prompt, reference_path)
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    return await collect(request_id, folder, max(1, min(int(wait_seconds), MAX_WAIT_SECONDS)), ctx, preview)


@mcp.tool()
async def generate_images(prompts: List[str], ctx: Context, reference_path: Optional[str] = None,
                          save_dir: Optional[str] = None, wait_seconds: int = SET_WAIT_SECONDS,
                          preview: bool = True) -> Annotated[CallToolResult, SetAnswer]:
    """Make a set of pictures with ChatGPT, one request per prompt (1 to 20), all following the same
    reference picture when one is given. Sends them all at once; ChatGPT makes them one after another,
    about a minute each. Reports how many are done as it goes, and answers once all have ended or
    wait_seconds has passed (at most 3600) with each prompt's files and preview, its failure reason,
    or its request id for get_image when it is still running. One failed prompt fails only itself; a
    refusal when sending (no credit left, say) stops sending the rest. One credit per request sent."""
    needs_key()
    if not 1 <= len(prompts) <= MAX_SET:
        raise ToolError("send 1 to {} prompts; this set has {}".format(MAX_SET, len(prompts)))
    blank = [str(n) for n, prompt in enumerate(prompts, 1) if not prompt.strip()]
    if blank:
        raise ToolError("prompt {} of the set is blank".format(", ".join(blank)))
    reference = checked_reference(reference_path)
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    items = [SetRequest(prompt=prompt, request_id=None, status="not sent", pictures=[], error=None)
             for prompt in prompts]
    for item in items:
        status, raw = await anyio.to_thread.run_sync(send, item["prompt"], reference)
        if status != 202:
            item.update(status="refused", error="the platform refused it ({}): {}".format(status, detail(raw)))
            break
        item.update(request_id=json.loads(raw)["id"], status="queued")
        SENT[item["request_id"]] = (item["prompt"], reference_path)
    if items[0]["status"] == "refused":
        raise ToolError("the platform refused the set's first prompt, so none was sent: " + items[0]["error"])

    sent = [item for item in items if item["request_id"]]
    wait = max(1, min(int(wait_seconds), MAX_SET_WAIT_SECONDS))
    shown, notes = [], {}
    began = time.monotonic()
    while True:
        for item in [item for item in sent if item["status"] in LIVE]:
            status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/images/{}".format(item["request_id"]))
            if status != 200:
                item.update(status="unread", error="it could not be read ({}): {}".format(status, detail(raw)))
                continue
            state = json.loads(raw)
            if state.get("status") == "done":
                try:
                    saved, more, notes[item["request_id"]] = await anyio.to_thread.run_sync(
                        save, state, folder, item["prompt"], reference_path, preview)
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
                                                                  later(item["request_id"])))
        elif item["status"] == "unread":
            lines.append(head + "request {}: {}; {}".format(item["request_id"], item["error"],
                                                            later(item["request_id"])))
        elif item["status"] == "not sent":
            lines.append(head + "not sent, as the platform refused an earlier prompt")
        else:
            lines.append(head + "{}: {}".format(item["status"], item["error"]))
    done = sum(1 for item in items if item["status"] == "done")
    message = "{} of {} prompts done ({} sent).\n{}".format(done, len(items), len(sent), "\n".join(lines))
    return answered(message, SetAnswer(requests=items, message=message), shown)


@mcp.tool()
async def account_status() -> Annotated[CallToolResult, Account]:
    """How many credits are left today and when they come back, and whether ChatGPT is served right now.
    Worth asking before a set: each request takes one credit, and none is sent while nobody serves ChatGPT."""
    needs_key()
    status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/account")
    if status != 200:
        raise ToolError("the account could not be read ({}): {}".format(status, detail(raw)))
    account = json.loads(raw)
    status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/providers")
    if status != 200:
        raise ToolError("the providers could not be read ({}): {}".format(status, detail(raw)))
    served = any(p.get("name") == "chatgpt" and p.get("served") for p in json.loads(raw).get("providers") or [])
    message = "{} of {} credits left today; they come back at {} (UTC). ChatGPT is {}.".format(
        account["credits_left"], account.get("credits_daily"), account["refills_at"],
        "served right now" if served else "not served right now, so a request would be refused (503) until it is")
    return answered(message, Account(credits_left=account["credits_left"], credits_daily=account.get("credits_daily"),
                                     refills_at=account["refills_at"], chatgpt_served=served, message=message), [])


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


if __name__ == "__main__":
    mcp.run()
