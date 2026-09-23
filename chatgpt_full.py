#!/usr/bin/env python3
"""
ChatGPT CLI - Full version with image support.

Usage:
    python chatgpt_full.py "Hello"                    # Text chat
    python chatgpt_full.py "Draw a cat" --image       # Generate & download image
    python chatgpt_full.py --login                    # Login
"""

import base64
import sys
from pathlib import Path

import cloakbrowser

CONFIG_DIR = Path.home() / ".chatgpt-cli"
STORAGE_FILE = CONFIG_DIR / "storage_cloak.json"
OUTPUT_DIR = Path.home() / "Sources/RE/chatgpt/images"


def login():
    print("Opening browser... Login to ChatGPT, then close browser.")
    CONFIG_DIR.mkdir(exist_ok=True)
    browser = cloakbrowser.launch(headless=False)
    ctx = browser.new_context()
    page = ctx.new_page()
    page.goto("https://chatgpt.com/")
    try:
        while len(ctx.pages) > 0:
            page.wait_for_timeout(1000)
    except:
        pass
    ctx.storage_state(path=str(STORAGE_FILE))
    browser.close()
    print(f"Session saved to {STORAGE_FILE}")


def chat(message: str, download_image: bool = False) -> dict:
    """Send message and get response. Returns {text, images: [paths]}"""
    if not STORAGE_FILE.exists():
        raise Exception("Not logged in. Run: python chatgpt_full.py --login")

    OUTPUT_DIR.mkdir(exist_ok=True)

    browser = cloakbrowser.launch(headless=True)
    ctx = browser.new_context(storage_state=str(STORAGE_FILE))
    page = ctx.new_page()
    page.goto("https://chatgpt.com/", timeout=90000, wait_until="domcontentloaded")
    page.wait_for_timeout(8000)

    # Count existing responses
    base_count = page.locator('[data-message-author-role="assistant"]').count()

    # Send message
    ta = page.locator("#prompt-textarea")
    ta.click()
    ta.fill(message)
    page.wait_for_timeout(300)

    btn = page.locator('button[data-testid="send-button"]')
    if btn.is_visible():
        btn.click()
    else:
        page.keyboard.press("Enter")

    # Wait for response
    result = {"text": "", "images": []}
    timeout = 120 if download_image else 60  # Longer for images
    stable = 0

    for i in range(timeout):
        page.wait_for_timeout(1000)

        resp_els = page.locator('[data-message-author-role="assistant"]').all()
        if len(resp_els) > base_count:
            last_resp = resp_els[-1]
            txt = last_resp.inner_text()

            if txt == result["text"]:
                stable += 1
                if stable >= 2 and page.locator('[data-testid="stop-button"]').count() == 0:
                    break
            else:
                result["text"] = txt
                stable = 0

    # Download images if requested
    if download_image:
        imgs_info = page.evaluate('''() => {
            const imgs = document.querySelectorAll("img");
            const results = [];
            for (const img of imgs) {
                const rect = img.getBoundingClientRect();
                if (rect.width > 100 && rect.height > 100) {
                    results.push({src: img.src, alt: img.alt || ""});
                }
            }
            return results;
        }''')

        for j, img in enumerate(imgs_info):
            src = img["src"]
            if "avatar" in src or "profile" in src:
                continue

            try:
                data = page.evaluate('''async (url) => {
                    const r = await fetch(url);
                    const b = await r.blob();
                    return new Promise(resolve => {
                        const reader = new FileReader();
                        reader.onload = () => resolve(reader.result);
                        reader.readAsDataURL(b);
                    });
                }''', src)

                if data and data.startswith("data:"):
                    # Generate filename from alt or index
                    alt = img["alt"][:30].replace(" ", "_").replace("/", "_") if img["alt"] else f"image_{j}"
                    fname = OUTPUT_DIR / f"{alt}.png"
                    with open(fname, "wb") as f:
                        f.write(base64.b64decode(data.split(",")[1]))
                    result["images"].append(str(fname))
            except:
                pass

    ctx.storage_state(path=str(STORAGE_FILE))
    browser.close()
    return result


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    if sys.argv[1] == "--login":
        login()
        return

    download_image = "--image" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    message = " ".join(args)

    if not message:
        print("Missing message!", file=sys.stderr)
        sys.exit(1)

    result = chat(message, download_image=download_image)

    print(result["text"])

    if result["images"]:
        print(f"\nImages saved:")
        for img in result["images"]:
            print(f"  {img}")


if __name__ == "__main__":
    main()
