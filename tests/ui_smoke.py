#!/usr/bin/env python3
"""Drive the web UI in a real browser and screenshot each step.

    python tests/ui_smoke.py

Needs a running stack. Reads WEB_URL (default http://localhost:5173) and
INVITE_CODE. Screenshots go to SHOT_DIR (default /tmp/ui_shots) so a human, or
an agent that can read images, can look at what actually rendered instead of
trusting an assertion.
"""

import os
import sys
import time
from pathlib import Path

import cloakbrowser

WEB_URL = os.environ.get("WEB_URL", "http://localhost:5173")
INVITE_CODE = os.environ.get("INVITE_CODE", "")
SHOT_DIR = Path(os.environ.get("SHOT_DIR", "/tmp/ui_shots"))

steps = []


def record(name, ok, detail=""):
    steps.append((name, ok, detail))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)
    return ok


def quota_number(page):
    text = page.locator("text=/\\d+ left/").first.inner_text()
    return int("".join(c for c in text.split("·")[-1] if c.isdigit()))


def shot(page, name):
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / "{}.png".format(name)
    page.screenshot(path=str(path), full_page=False)
    return path


def main():
    if not INVITE_CODE:
        sys.exit("set INVITE_CODE to the code the running API was started with")

    email = "ui-smoke-{}@aiplatform-acceptance.com".format(int(time.time()))
    password = "ui-smoke-pw-1"

    browser = cloakbrowser.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    try:
        page.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("text=AI Platform", timeout=20000)
        shot(page, "01-login")
        record("login page renders", True, page.title())

        page.click("button:has-text('Create account')")
        page.fill("input[type=email]", email)
        page.fill("input[type=password]", password)
        page.fill("input[placeholder='name (optional)']", "UI Smoke")
        page.fill("input[placeholder='invite code']", INVITE_CODE)
        shot(page, "02-register-filled")

        # The mode toggle carries the same label as the submit button, so match
        # on type rather than text or the toggle gets clicked and nothing sends.
        page.click("form button[type=submit]")
        page.wait_for_selector("text=sign out", timeout=30000)
        shot(page, "03-signed-in")
        record("register and sign in", True, email)

        quota_before = quota_number(page)
        record("nav shows identity and quota", email.split("@")[0] in page.content(),
               "{} left".format(quota_before))

        page.fill("input[placeholder='Type a message...']", "hello from the ui smoke test")
        shot(page, "04-message-typed")
        page.click("button:has-text('Send')")

        page.wait_for_selector("text=mock reply from chatgpt", timeout=60000)
        shot(page, "05-chat-reply")
        record("chat message round trip", True, "assistant bubble rendered")

        page.click("header button:has-text('image')")
        page.fill("input[placeholder='Describe the image...']", "a red square")
        page.click("button:has-text('Send')")
        page.wait_for_selector("button:has-text('Video script')", timeout=90000)
        page.wait_for_timeout(2000)
        shot(page, "06-image-rendered")

        rendered = page.evaluate(
            """() => Array.from(document.images)
                 .filter(i => i.naturalWidth > 0)
                 .map(i => ({w: i.naturalWidth, h: i.naturalHeight, blob: i.src.startsWith('blob:')}))"""
        )
        record("generated image renders in chat", bool(rendered),
               "{} image(s), {}".format(len(rendered), rendered[:2]))

        page.click("button:has-text('Video script')")
        page.wait_for_selector("text=mock 5-second script", timeout=60000)
        shot(page, "07-video-script")
        record("video script from an image", True, "script bubble rendered")

        quota_after = quota_number(page)
        record("quota in the nav tracks the jobs spent", quota_after == quota_before - 3,
               "{} -> {} after 3 jobs".format(quota_before, quota_after))

        page.click("nav button:has-text('gallery')")
        page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
        page.wait_for_timeout(1500)
        shot(page, "08-gallery")
        heading = page.locator("text=/Gallery \\(\\d+\\)/").first.inner_text()
        gallery_images = page.evaluate(
            "() => Array.from(document.images).filter(i => i.naturalWidth > 0).length"
        )
        record("gallery lists the generated media", gallery_images >= 1,
               "{}, {} thumbnail(s)".format(heading, gallery_images))

        page.click("button:has-text('sign out')")
        page.wait_for_selector("button:has-text('Sign in')", timeout=20000)
        shot(page, "09-signed-out")
        record("sign out returns to login", True, "")

        real_errors = [e for e in errors if "favicon" not in e.lower()]
        record("no console errors", not real_errors, str(real_errors[:3]))

    except Exception as exc:
        shot(page, "99-failure")
        record("unexpected failure", False, "{}: {}".format(type(exc).__name__, str(exc)[:300]))
    finally:
        browser.close()

    passed = sum(1 for _, ok, _ in steps if ok)
    print("=" * 50)
    print("{}/{} PASSED".format(passed, len(steps)))
    print("screenshots in {}".format(SHOT_DIR))
    return 0 if passed == len(steps) else 1


if __name__ == "__main__":
    sys.exit(main())
