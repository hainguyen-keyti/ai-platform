#!/usr/bin/env python3
"""
ChatGPT CLI via Playwright - dùng browser thật, bypass Cloudflare.

Setup (1 lần):
    python chatgpt_pw.py --login
    # Browser mở ra, đăng nhập ChatGPT, đóng browser

Usage:
    python chatgpt_pw.py "Hello!"
    python chatgpt_pw.py --stream "Tell me a joke"
    python chatgpt_pw.py --new "Start fresh conversation"
"""

import json
import sys
import uuid
from pathlib import Path
from typing import Generator

from playwright.sync_api import sync_playwright

CONFIG_DIR = Path.home() / ".chatgpt-cli"
STORAGE_FILE = CONFIG_DIR / "storage.json"
STATE_FILE = CONFIG_DIR / "state.json"


def load_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())


def save_state(state: dict):
    CONFIG_DIR.mkdir(exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def login():
    """Mở browser để đăng nhập."""
    print("Đang mở browser... Đăng nhập ChatGPT, sau đó ĐÓNG BROWSER để lưu session.")
    CONFIG_DIR.mkdir(exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://chatgpt.com/")

        try:
            while len(context.pages) > 0:
                page.wait_for_timeout(1000)
        except Exception:
            pass

        context.storage_state(path=str(STORAGE_FILE))
        browser.close()

    print(f"Đã lưu session tại {STORAGE_FILE}")


def chat(message: str, stream: bool = False, new_conv: bool = False) -> str | Generator[str, None, None]:
    """Gửi message qua browser API."""
    if not STORAGE_FILE.exists():
        raise Exception("Chưa đăng nhập. Chạy: python chatgpt_pw.py --login")

    state = load_state()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=str(STORAGE_FILE))
        page = context.new_page()

        page.goto("https://chatgpt.com/")
        page.wait_for_load_state("domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)

        token_result = page.evaluate("""
            async () => {
                try {
                    const resp = await fetch('/api/auth/session');
                    const data = await resp.json();
                    return data.accessToken || null;
                } catch (e) {
                    return null;
                }
            }
        """)

        if not token_result:
            browser.close()
            raise Exception("Session hết hạn. Chạy lại: python chatgpt_pw.py --login")

        conv_id = None if new_conv else state.get("conversation_id")

        payload = {
            "action": "next",
            "messages": [{
                "id": str(uuid.uuid4()),
                "author": {"role": "user"},
                "content": {"content_type": "text", "parts": [message]},
                "metadata": {},
            }],
            "parent_message_id": state.get("parent_message_id", str(uuid.uuid4())),
            "model": "auto",
            "timezone_offset_min": -420,
            "history_and_training_disabled": False,
            "conversation_mode": {"kind": "primary_assistant"},
            "force_paragen": False,
            "force_rate_limit": False,
        }

        if conv_id:
            payload["conversation_id"] = conv_id

        response_text = page.evaluate("""
            async (args) => {
                const [token, payload] = args;
                const resp = await fetch('https://chatgpt.com/backend-api/conversation', {
                    method: 'POST',
                    headers: {
                        'Authorization': 'Bearer ' + token,
                        'Content-Type': 'application/json',
                        'Accept': 'text/event-stream',
                    },
                    body: JSON.stringify(payload),
                });
                return await resp.text();
            }
        """, [token_result, payload])

        context.storage_state(path=str(STORAGE_FILE))
        browser.close()

        full_text = ""
        for line in response_text.split("\n"):
            if line.startswith("data: ") and line != "data: [DONE]":
                try:
                    data = json.loads(line[6:])
                    if msg := data.get("message"):
                        if msg.get("author", {}).get("role") == "assistant":
                            parts = msg.get("content", {}).get("parts", [])
                            if parts and isinstance(parts[0], str):
                                full_text = parts[0]
                        if msg_id := msg.get("id"):
                            state["parent_message_id"] = msg_id
                    if cid := data.get("conversation_id"):
                        state["conversation_id"] = cid
                except json.JSONDecodeError:
                    pass

        save_state(state)
        return full_text


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--login":
        login()
        return

    new_conv = "--new" in sys.argv
    stream = "--stream" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("Thiếu message!", file=sys.stderr)
        sys.exit(1)

    message = " ".join(args)
    result = chat(message, stream=stream, new_conv=new_conv)
    print(result)


if __name__ == "__main__":
    main()
