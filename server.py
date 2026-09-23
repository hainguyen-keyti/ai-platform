#!/usr/bin/env python3
"""
ChatGPT Server - simple version.

Start: python server.py
Test:  curl -X POST localhost:5123/chat -d '{"message":"Hi"}'
"""

import json
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import cloakbrowser

STORAGE = Path.home() / ".chatgpt-cli" / "storage_cloak.json"

browser = None
page = None
lock = threading.Lock()


def init():
    global browser, page
    print("Starting browser...")
    browser = cloakbrowser.launch(headless=True)
    ctx = browser.new_context(storage_state=str(STORAGE))
    page = ctx.new_page()
    page.goto("https://chatgpt.com/", timeout=90000, wait_until="domcontentloaded")

    # Wait for textarea
    for i in range(30):
        page.wait_for_timeout(1000)
        if page.locator("#prompt-textarea").is_visible():
            print(f"Ready in {i+1}s")
            return
    print("Warning: textarea not found")


def chat(msg: str) -> str:
    global page
    with lock:
        # Get baseline
        base = page.locator('[data-message-author-role="assistant"]').count()

        # Type and send
        ta = page.locator("#prompt-textarea")
        ta.click()
        ta.fill(msg)
        page.wait_for_timeout(200)

        btn = page.locator('button[data-testid="send-button"]')
        if btn.is_visible():
            btn.click()
        else:
            page.keyboard.press("Enter")

        # Wait for new response
        result = ""
        stable = 0
        for _ in range(120):  # max 60s
            page.wait_for_timeout(500)

            els = page.locator('[data-message-author-role="assistant"]').all()
            if len(els) > base:
                txt = els[-1].inner_text()
                if txt == result:
                    stable += 1
                    # Stable for 1s and no stop button
                    if stable >= 2 and page.locator('[data-testid="stop-button"]').count() == 0:
                        return txt
                else:
                    result = txt
                    stable = 0

        return result


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/chat":
            n = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(n).decode()) if n else {}
            msg = body.get("message", "")

            if not msg:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b'{"error":"no message"}')
                return

            try:
                r = chat(msg)
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"response": r}).encode())
            except Exception as e:
                self.send_response(500)
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, *a): pass


if __name__ == "__main__":
    if not STORAGE.exists():
        print("Run login first: python chatgpt_cloak.py --login")
        sys.exit(1)

    init()
    s = HTTPServer(("127.0.0.1", 5123), H)
    print("Server at http://localhost:5123")
    try:
        s.serve_forever()
    except KeyboardInterrupt:
        browser.close()
