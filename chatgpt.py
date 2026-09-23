#!/usr/bin/env python3
"""
ChatGPT CLI wrapper - dùng session token để tương tác với ChatGPT subscription.

Setup:
    1. Mở chatgpt.com, đăng nhập
    2. DevTools (F12) > Console, chạy:
       JSON.stringify(await (await fetch('/api/auth/session')).json())
    3. Copy output, chạy: python chatgpt.py --setup
    4. Paste JSON khi được hỏi

Usage:
    python chatgpt.py "Hello!"
    python chatgpt.py --stream "Tell me a joke"
"""

import json
import sys
import time
import uuid
from pathlib import Path
from typing import Generator

from curl_cffi import requests

CONFIG_DIR = Path.home() / ".chatgpt-cli"
CONFIG_FILE = CONFIG_DIR / "config.json"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text())


def save_config(config: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2))


def refresh_access_token(session_token: str) -> str | None:
    """Dùng session token để lấy access token mới."""
    resp = requests.get(
        "https://chatgpt.com/api/auth/session",
        cookies={"__Secure-next-auth.session-token": session_token},
        impersonate="chrome",
    )
    if resp.ok:
        data = resp.json()
        return data.get("accessToken")
    return None


def get_access_token() -> str:
    """Lấy access token, refresh nếu cần."""
    config = load_config()
    if not config.get("session_token"):
        print("Chưa setup. Chạy: python chatgpt.py --setup", file=sys.stderr)
        sys.exit(1)

    access_token = config.get("access_token")
    expires_at = config.get("expires_at", 0)

    if not access_token or time.time() > expires_at - 300:
        access_token = refresh_access_token(config["session_token"])
        if not access_token:
            print("Không thể refresh token. Chạy lại --setup", file=sys.stderr)
            sys.exit(1)
        config["access_token"] = access_token
        config["expires_at"] = time.time() + 86400 * 9
        save_config(config)

    return access_token


def chat(message: str, model: str = "auto", stream: bool = False) -> str | Generator[str, None, None]:
    """Gửi message và nhận response."""
    token = get_access_token()
    config = load_config()

    payload = {
        "action": "next",
        "messages": [{
            "id": str(uuid.uuid4()),
            "author": {"role": "user"},
            "content": {"content_type": "text", "parts": [message]},
            "metadata": {},
        }],
        "parent_message_id": str(uuid.uuid4()),
        "model": model,
        "timezone_offset_min": -420,
        "history_and_training_disabled": False,
        "conversation_mode": {"kind": "primary_assistant"},
        "force_paragen": False,
        "force_rate_limit": False,
    }

    conv_id = config.get("conversation_id")
    if conv_id:
        payload["conversation_id"] = conv_id

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
        "Origin": "https://chatgpt.com",
        "Referer": "https://chatgpt.com/",
        "Oai-Language": "en-US",
        "Oai-Device-Id": str(uuid.uuid4()),
    }

    resp = requests.post(
        "https://chatgpt.com/backend-api/conversation",
        headers=headers,
        json=payload,
        impersonate="chrome",
        stream=stream,
    )

    if not resp.ok:
        raise Exception(f"API error: {resp.status_code} - {resp.text[:200]}")

    if stream:
        return _stream_response(resp, config)
    else:
        return _parse_response(resp, config)


def _parse_response(resp, config: dict) -> str:
    """Parse non-stream response."""
    full_text = ""
    for line in resp.text.split("\n"):
        if line.startswith("data: ") and line != "data: [DONE]":
            try:
                data = json.loads(line[6:])
                if msg := data.get("message"):
                    if msg.get("author", {}).get("role") == "assistant":
                        parts = msg.get("content", {}).get("parts", [])
                        if parts:
                            full_text = parts[0]
                    if conv_id := data.get("conversation_id"):
                        config["conversation_id"] = conv_id
                        save_config(config)
            except json.JSONDecodeError:
                pass
    return full_text


def _stream_response(resp, config: dict) -> Generator[str, None, None]:
    """Stream response."""
    prev_text = ""
    for line in resp.iter_lines(decode_unicode=True):
        if line and line.startswith("data: ") and line != "data: [DONE]":
            try:
                data = json.loads(line[6:])
                if msg := data.get("message"):
                    if msg.get("author", {}).get("role") == "assistant":
                        parts = msg.get("content", {}).get("parts", [])
                        if parts and isinstance(parts[0], str):
                            new_text = parts[0]
                            if len(new_text) > len(prev_text):
                                yield new_text[len(prev_text):]
                                prev_text = new_text
                    if conv_id := data.get("conversation_id"):
                        config["conversation_id"] = conv_id
                        save_config(config)
            except json.JSONDecodeError:
                pass


def setup():
    """Setup session token."""
    print("Paste JSON từ DevTools (hoặc chỉ sessionToken):")
    raw = input().strip()

    try:
        data = json.loads(raw)
        session_token = data.get("sessionToken") or data.get("session_token")
        access_token = data.get("accessToken") or data.get("access_token")
    except json.JSONDecodeError:
        session_token = raw
        access_token = None

    if not session_token:
        print("Không tìm thấy session token!", file=sys.stderr)
        sys.exit(1)

    config = {
        "session_token": session_token,
        "access_token": access_token,
        "expires_at": time.time() + 86400 * 9 if access_token else 0,
    }
    save_config(config)
    print(f"Đã lưu config tại {CONFIG_FILE}")


def new_conversation():
    """Bắt đầu conversation mới."""
    config = load_config()
    config.pop("conversation_id", None)
    save_config(config)
    print("Đã reset conversation.")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--setup":
        setup()
        return

    if sys.argv[1] == "--new":
        new_conversation()
        return

    stream = "--stream" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("Thiếu message!", file=sys.stderr)
        sys.exit(1)

    message = " ".join(args)

    if stream:
        for chunk in chat(message, stream=True):
            print(chunk, end="", flush=True)
        print()
    else:
        print(chat(message))


if __name__ == "__main__":
    main()
