#!/usr/bin/env python3
"""
ChatGPT CLI via CloakBrowser - bypass Cloudflare detection.

Setup (1 lần):
    python chatgpt_cloak.py --login
    # Browser mở ra, đăng nhập ChatGPT, đóng browser

Usage:
    python chatgpt_cloak.py "Hello!"
    python chatgpt_cloak.py --new "Start fresh conversation"
"""

import sys
from pathlib import Path

import cloakbrowser

CONFIG_DIR = Path.home() / ".chatgpt-cli"
STORAGE_FILE = CONFIG_DIR / "storage_cloak.json"


def login():
    """Mở browser để đăng nhập."""
    print("Đang mở browser... Đăng nhập ChatGPT, sau đó ĐÓNG BROWSER để lưu session.")
    CONFIG_DIR.mkdir(exist_ok=True)

    browser = cloakbrowser.launch(headless=False)
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


def chat(message: str, new_conv: bool = False) -> str:
    """Gửi message qua browser UI."""
    if not STORAGE_FILE.exists():
        raise Exception("Chưa đăng nhập. Chạy: python chatgpt_cloak.py --login")

    browser = cloakbrowser.launch(headless=True)
    context = browser.new_context(storage_state=str(STORAGE_FILE))
    page = context.new_page()

    url = "https://chatgpt.com/" if new_conv else "https://chatgpt.com/"
    page.goto(url, timeout=90000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)

    textarea = page.locator("#prompt-textarea").first
    if not textarea.is_visible():
        browser.close()
        raise Exception("Không tìm thấy ô nhập. Session có thể hết hạn.")

    textarea.fill(message)
    page.wait_for_timeout(500)

    send_btn = page.locator('button[data-testid="send-button"]').first
    if send_btn.is_visible():
        send_btn.click()
    else:
        page.keyboard.press("Enter")

    # Wait for response (check every 2s, max 60s)
    max_wait = 60
    waited = 0
    last_response = ""

    while waited < max_wait:
        page.wait_for_timeout(2000)
        waited += 2

        responses = page.locator('[data-message-author-role="assistant"]').all()
        if responses:
            current = responses[-1].inner_text()
            if current and current != last_response:
                last_response = current
                # Check if response is complete (no typing indicator)
                typing = page.locator('[data-testid="stop-button"]').count()
                if typing == 0:
                    break

    context.storage_state(path=str(STORAGE_FILE))
    browser.close()

    return last_response


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--login":
        login()
        return

    new_conv = "--new" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    if not args:
        print("Thiếu message!", file=sys.stderr)
        sys.exit(1)

    message = " ".join(args)
    result = chat(message, new_conv=new_conv)
    print(result)


if __name__ == "__main__":
    main()
