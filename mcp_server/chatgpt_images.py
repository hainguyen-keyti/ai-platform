#!/usr/bin/env python3
"""An MCP server that makes pictures with ChatGPT through the platform's image API (/v1/images).

An agent's host (Claude Code, Claude Desktop, any MCP client) starts it as a subprocess and talks to
it over stdio. It calls the platform with the person's own API key, made on the web's API page:

    AIP_API_KEY   the key (aip_...), required; never printed
    AIP_API_URL   the platform's api (default http://localhost:3000)
    AIP_SAVE_DIR  where pictures are saved when a call names no folder (default: <temp>/aip-pictures)

Two tools: generate_image sends a prompt (and optionally a reference picture), waits for ChatGPT,
saves every picture it made and answers with their paths; get_image does the same for a request
already sent, for a host that stopped waiting. Under WSL a Windows path the agent gives is read where
WSL sees it, and every saved picture is also named by its Windows path. Install and register:
README.md, "MCP server for ChatGPT pictures". Issue #17.
"""

import json
import os
import platform
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Optional

import anyio
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError

API = os.environ.get("AIP_API_URL", "http://localhost:3000").rstrip("/")
KEY = os.environ.get("AIP_API_KEY", "")
POLL_SECONDS = float(os.environ.get("AIP_POLL_SECONDS", "3"))
SAVE_DIR = Path(os.environ.get("AIP_SAVE_DIR") or Path(tempfile.gettempdir()) / "aip-pictures")
# A picture usually takes about a minute and the platform gives up after five (docs/api-v1-images.md).
WAIT_SECONDS, MAX_WAIT_SECONDS = 420, 900
WSL = "microsoft" in platform.release().lower()
CONTENT_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
SUFFIXES = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
WINDOWS_PATH = re.compile(r"^([A-Za-z]):[\\/](.*)$")

mcp = MCPServer("aip-chatgpt-images", instructions=(
    "Makes pictures with ChatGPT on the AI Platform. Call generate_image with a prompt, and a "
    "reference picture's path when the picture should follow one; it answers with the saved files' "
    "paths. A picture takes about a minute. If it says the request is still running, call get_image "
    "with its request id later."))


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


def needs_key():
    if not KEY:
        raise ToolError("AIP_API_KEY is not set: make a key on the platform's web, page API, and give it to "
                        "this server in its environment")


def save(state: dict, folder: Path) -> str:
    """Download every picture of a done request into folder; the answer naming them."""
    folder.mkdir(parents=True, exist_ok=True)
    lines = []
    for number, picture in enumerate(state.get("images") or [], 1):
        status, blob = call("GET", picture["url"])
        if status != 200:
            raise ToolError("picture {} of request {} could not be downloaded ({}): {}".format(
                number, state["id"], status, detail(blob)))
        path = folder / "{}-{}{}".format(state["id"][:8], number, SUFFIXES.get(picture.get("content_type"), ""))
        path.write_bytes(blob)
        shown = windows_path(path)
        lines.append("- {}{}".format(path, " (Windows: {})".format(shown) if shown else ""))
    if not lines:
        raise ToolError("request {} is done but no picture came back{}".format(
            state["id"], ": " + state["text"] if state.get("text") else ""))
    words = "\nChatGPT said: {}".format(state["text"]) if state.get("text") else ""
    return "ChatGPT made {} picture(s) for request {}, saved as:\n{}{}".format(
        len(lines), state["id"], "\n".join(lines), words)


async def collect(request_id: str, folder: Path, wait: float, ctx: Optional[Context]) -> str:
    """Ask for the request until it ends or `wait` seconds pass; save what a done one made."""
    began = time.monotonic()
    while True:
        status, raw = await anyio.to_thread.run_sync(call, "GET", "/v1/images/{}".format(request_id))
        if status != 200:
            raise ToolError("request {} could not be read ({}): {}".format(request_id, status, detail(raw)))
        state = json.loads(raw)
        if state.get("status") == "done":
            return await anyio.to_thread.run_sync(save, state, folder)
        if state.get("status") in ("failed", "cancelled"):
            raise ToolError("request {} {}: {} (the credit was given back)".format(
                request_id, state["status"], state.get("error") or "no reason given"))
        waited = time.monotonic() - began
        if waited >= wait:
            return ("Request {} is still {} after {:.0f}s. Call get_image with request_id \"{}\" in a minute "
                    "to collect its pictures.".format(request_id, state.get("status"), waited, request_id))
        if ctx is not None:
            await ctx.report_progress(min(waited, wait), wait, message="ChatGPT is {}".format(state.get("status")))
        await anyio.sleep(POLL_SECONDS)


@mcp.tool()
async def generate_image(prompt: str, ctx: Context, reference_path: Optional[str] = None,
                         save_dir: Optional[str] = None, wait_seconds: int = WAIT_SECONDS) -> str:
    """Make a picture with ChatGPT from a prompt, optionally following a reference picture (PNG, JPEG
    or WEBP, at most 10 MB), and save it. Waits for it (about a minute, up to wait_seconds) and
    answers with the saved files' paths; a request still running then is collected with get_image.
    Each request costs one credit on the platform; a failed one gives it back."""
    needs_key()
    reference = None
    if reference_path:
        reference = Path(local_path(reference_path))
        if not reference.is_file():
            raise ToolError("the reference picture {} is not there".format(reference_path))
    body, content_type = form(prompt, reference)
    status, raw = await anyio.to_thread.run_sync(call, "POST", "/v1/images", body, content_type)
    if status != 202:
        raise ToolError("the platform refused the request ({}): {}".format(status, detail(raw)))
    request_id = json.loads(raw)["id"]
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    return await collect(request_id, folder, max(1, min(int(wait_seconds), MAX_WAIT_SECONDS)), ctx)


@mcp.tool()
async def get_image(request_id: str, ctx: Context, save_dir: Optional[str] = None) -> str:
    """Collect the pictures of a request generate_image already sent: saves them and answers with
    their paths when it is done, says so when it is still running, and gives its reason when it failed."""
    needs_key()
    folder = Path(local_path(save_dir)) if save_dir else SAVE_DIR
    return await collect(request_id, folder, 0, ctx)


if __name__ == "__main__":
    mcp.run()
