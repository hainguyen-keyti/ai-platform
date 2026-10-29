#!/usr/bin/env python3
"""The ChatGPT picture MCP server (mcp_server/chatgpt_images.py), run as a host runs it: a subprocess
over stdio, driven by the SDK's own Client, against a fake /v1 that records what it was sent.

    ~/.venvs/aip-mcp/bin/python tests/test_mcp_chatgpt_images.py

Needs the server's own venv (mcp_server/requirements.txt). No platform, no worker, no account.
Prints N/N PASSED.
"""

import anyio
import email.parser
import http.server
import json
import os
import shutil
import sys
import tempfile
import threading
import uuid
from pathlib import Path

from mcp import Client, StdioServerParameters

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "mcp_server" / "chatgpt_images.py"
KEY = "aip_test-key-" + "x" * 30
PICTURE = b"\x89PNG\r\n\x1a\n" + b"fake picture bytes" * 20

results = []


def record(name, ok, detail=""):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class FakeV1:
    """/v1/images as the platform answers it. A prompt names its fate: "refuse" answers 402, "fail"
    ends failed, "slow" stays running until `finish` is called, anything else ends done with one
    picture after one running read."""

    def __init__(self):
        self.posts, self.requests = [], {}
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
                if len(parts) == 5 and parts[3] == "files":
                    return self.answer(200, PICTURE, ctype="image/png")
                rid = parts[2] if len(parts) == 3 else None
                state = fake.requests.get(rid)
                if not state:
                    return self.answer(404, {"detail": "image request not found"})
                state["reads"] += 1
                body = {"id": rid, "provider": "chatgpt", "text": "", "error": None, "images": []}
                if "fail" in state["prompt"]:
                    body.update(status="failed", error="chatgpt returned nothing after 300s")
                elif ("slow" in state["prompt"] and not state["finished"]) or state["reads"] < 2:
                    body["status"] = "running"
                else:
                    body.update(status="done", text="Here it is.", images=[{
                        "id": "m1", "url": "/v1/images/{}/files/m1".format(rid), "content_type": "image/png",
                        "bytes": len(PICTURE)}])
                self.answer(200, body)

            def log_message(self, *args):
                pass

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:{}".format(self.server.server_address[1])
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def finish(self, rid):
        self.requests[rid]["finished"] = True

    def close(self):
        self.server.shutdown()
        self.server.server_close()


def said(result):
    return "\n".join(getattr(block, "text", "") for block in result.content)


def server_params(api, key=KEY):
    env = {"AIP_API_URL": api, "AIP_POLL_SECONDS": "0.2"}
    if key:
        env["AIP_API_KEY"] = key
    return StdioServerParameters(command=sys.executable, args=[str(SERVER)], env=env)


async def run(fake, work):
    async with Client(server_params(fake.url)) as client:
        tools = sorted(tool.name for tool in (await client.list_tools()).tools)
        record("the server offers generate_image and get_image, and nothing else",
               tools == ["generate_image", "get_image"], repr(tools))

        out = work / "plain"
        result = await client.call_tool("generate_image", {"prompt": "a plain blue square", "save_dir": str(out)},
                                        read_timeout_seconds=60)
        text = said(result)
        saved = sorted(out.glob("*"))
        post = fake.posts[-1] if fake.posts else {}
        record("generate_image sends the prompt to chatgpt with the key, and saves the picture it made",
               not result.is_error and len(saved) == 1 and saved[0].read_bytes() == PICTURE
               and str(saved[0]) in text and post.get("auth") == "Bearer " + KEY
               and post.get("fields", {}).get("provider") == b"chatgpt"
               and post.get("fields", {}).get("prompt") == b"a plain blue square",
               "error {} saved {} said {!r} sent {}".format(result.is_error, [p.name for p in saved], text[:200],
                                                           {k: v[:20] for k, v in post.get("fields", {}).items()}))
        record("the key never appears in what the tool answers", KEY not in text and "aip_" not in text, "")

        reference = work / "ref.png"
        reference.write_bytes(b"\x89PNG\r\n\x1a\n reference picture")
        result = await client.call_tool("generate_image", {"prompt": "the same at night",
                                                           "reference_path": str(reference),
                                                           "save_dir": str(work / "ref")},
                                        read_timeout_seconds=60)
        sent = fake.posts[-1].get("fields", {}).get("image")
        record("a reference picture is sent as the request's image, byte for byte",
               not result.is_error and sent == reference.read_bytes(),
               "error {} sent {} bytes".format(result.is_error, len(sent or b"")))

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
        rid = next((r for r, s in fake.requests.items() if s["prompt"] == "a slow one"), None)
        record("a request still running when the wait ends says so with its id, and is no error",
               not result.is_error and rid and rid in said(result) and "get_image" in said(result),
               "error {} said {!r}".format(result.is_error, said(result)[:200]))
        if rid:
            fake.finish(rid)
        result = await client.call_tool("get_image", {"request_id": rid or "none", "save_dir": str(work / "slow")},
                                        read_timeout_seconds=30)
        later = sorted((work / "slow").glob("*")) if (work / "slow").exists() else []
        record("get_image collects that request's picture once it is done",
               not result.is_error and len(later) == 1 and later[0].read_bytes() == PICTURE,
               "error {} saved {} said {!r}".format(result.is_error, [p.name for p in later], said(result)[:160]))

    before = len(fake.posts)
    async with Client(server_params(fake.url, key=None)) as client:
        result = await client.call_tool("generate_image", {"prompt": "no key"}, read_timeout_seconds=30)
    record("without AIP_API_KEY the tool says how to set it and sends nothing",
           result.is_error and "AIP_API_KEY" in said(result) and len(fake.posts) == before,
           "error {} said {!r}".format(result.is_error, said(result)[:160]))


def path_cases():
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


def main():
    if not SERVER.exists():
        record("the server file is there", False, str(SERVER))
    else:
        fake, work = FakeV1(), Path(tempfile.mkdtemp(prefix="mcp-chatgpt-images-"))
        try:
            anyio.run(run, fake, work)
            path_cases()
        finally:
            fake.close()
            shutil.rmtree(work, ignore_errors=True)
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
