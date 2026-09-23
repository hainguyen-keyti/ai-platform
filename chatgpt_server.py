#!/usr/bin/env python3
"""
ChatGPT Server - chạy browser 1 lần, giữ alive, nhận request qua HTTP.

Start server:
    python chatgpt_server.py

API:
    curl -X POST http://localhost:5123/chat -d '{"message": "Hello"}'
    curl http://localhost:5123/health
"""

import json
import threading
import uuid
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import cloakbrowser

CONFIG_DIR = Path.home() / ".chatgpt-cli"
STORAGE_FILE = CONFIG_DIR / "storage_cloak.json"

# Global browser instance
browser = None
context = None
page = None
lock = threading.Lock()


def init_browser():
    global browser, context, page
    print("Starting browser...")
    browser = cloakbrowser.launch(headless=True)
    context = browser.new_context(storage_state=str(STORAGE_FILE))
    page = context.new_page()
    page.goto("https://chatgpt.com/", timeout=90000, wait_until="domcontentloaded")

    # Wait for textarea to be ready
    for _ in range(20):
        page.wait_for_timeout(1000)
        if page.locator("#prompt-textarea").is_visible():
            break

    print("Browser ready!")


def chat(message: str) -> str:
    global page, context

    with lock:
        # Scroll to bottom first
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(300)

        # Count existing responses
        existing_count = page.locator('[data-message-author-role="assistant"]').count()
        print(f"[chat] existing_count={existing_count}, message={message[:30]}")

        # Find and fill textarea
        textarea = page.locator("#prompt-textarea").first
        if not textarea.is_visible():
            page.reload()
            page.wait_for_timeout(5000)
            existing_count = page.locator('[data-message-author-role="assistant"]').count()
            textarea = page.locator("#prompt-textarea").first

        textarea.click()
        textarea.fill(message)
        page.wait_for_timeout(300)

        # Click send
        send_btn = page.locator('button[data-testid="send-button"]').first
        if send_btn.is_visible():
            send_btn.click()
        else:
            page.keyboard.press("Enter")

        # Wait for NEW response
        max_wait = 120
        waited = 0
        last_response = ""
        stable_count = 0

        while waited < max_wait:
            page.wait_for_timeout(500)
            waited += 1

            responses = page.locator('[data-message-author-role="assistant"]').all()
            # Only check if we have more responses than before
            if len(responses) > existing_count:
                current = responses[-1].inner_text()
                if current:
                    if current == last_response:
                        stable_count += 1
                        if stable_count >= 3:
                            typing = page.locator('[data-testid="stop-button"]').count()
                            if typing == 0:
                                break
                    else:
                        last_response = current
                        stable_count = 0

        # Save session periodically
        if waited < max_wait:
            context.storage_state(path=str(STORAGE_FILE))

        return last_response


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok"}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/chat":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode()

            try:
                data = json.loads(body) if body else {}
                message = data.get("message", "")

                if not message:
                    self.send_response(400)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "Missing message"}).encode())
                    return

                response = chat(message)

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"response": response}).encode())

            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[{self.client_address[0]}] {args[0]}")


def main():
    if not STORAGE_FILE.exists():
        print("Chưa đăng nhập. Chạy: python chatgpt_cloak.py --login")
        return

    init_browser()

    server = HTTPServer(("127.0.0.1", 5123), Handler)
    print("Server running at http://localhost:5123")
    print("  POST /chat - Send message")
    print("  GET /health - Health check")
    print("Press Ctrl+C to stop")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        browser.close()
        server.shutdown()


if __name__ == "__main__":
    main()
