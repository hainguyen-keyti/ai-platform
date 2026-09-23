#!/usr/bin/env python3
"""Drive the web UI in a real browser and screenshot each step.

    python tests/ui_smoke.py

Needs a running stack whose worker is in mock mode with a delay:

    PROVIDER_MODE=mock MOCK_DELAY_SECONDS=4 ./scripts/run-worker.sh

The delay is not optional. A mock that answers instantly leaves no waiting state,
so the typing indicator can never be observed. Against a real provider the waits
here are far too short.

Reads WEB_URL (default http://localhost:5173) and INVITE_CODE. Screenshots go to
SHOT_DIR (default /tmp/ui_shots) so a human, or an agent that can read images,
can look at what actually rendered instead of trusting an assertion.
"""

import os
import sys
import time
from pathlib import Path

import cloakbrowser

WEB_URL = os.environ.get("WEB_URL", "http://localhost:5173")
INVITE_CODE = os.environ.get("INVITE_CODE", "")
SHOT_DIR = Path(os.environ.get("SHOT_DIR", "/tmp/ui_shots"))
# Prefix match so a reworded placeholder does not break every step at once.
COMPOSER = "input[placeholder^='Type a message']"

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

        page.fill(COMPOSER, "hello from the ui smoke test")
        shot(page, "04-message-typed")
        page.click("button:has-text('Send')")

        # Needs MOCK_DELAY_SECONDS on the worker: a mock that answers instantly
        # leaves no waiting state to look at.
        try:
            page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
            page.wait_for_timeout(1200)
            shot(page, "05a-typing")
            label = page.locator("[data-testid=typing-bubble]").inner_text().strip()
            dots = page.evaluate(
                "() => document.querySelectorAll('[data-testid=typing-bubble] span.animate-bounce').length"
            )
            record("typing indicator while waiting", dots == 3 and label != "",
                   "{} dots, elapsed reads {}".format(dots, label))
        except Exception as exc:
            record("typing indicator while waiting", False,
                   "{}; is the worker running with MOCK_DELAY_SECONDS set?".format(type(exc).__name__))

        page.wait_for_selector("text=mock reply from chatgpt", timeout=60000)
        shot(page, "05-chat-reply")
        record("chat message round trip", True, "assistant bubble rendered")

        page.fill(COMPOSER, "generate an image of a red square")
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

        # Document order, not coordinates: the picture must sit where it was
        # produced, with the later reply below it, rather than in a strip
        # dumped at the end of the thread.
        order = page.evaluate(
            """() => {
                const img = document.querySelector('[data-testid=media-thumb]');
                const bubbles = document.querySelectorAll('[data-testid=message-scroll] .whitespace-pre-wrap');
                const last = bubbles[bubbles.length - 1];
                if (!img || !last) return null;
                const following = img.compareDocumentPosition(last) & Node.DOCUMENT_POSITION_FOLLOWING;
                return {following: !!following, tail: last.textContent.trim().slice(0, 40)};
            }"""
        )
        record("media sits inline in the timeline", bool(order and order["following"]),
               "last bubble {} the image: {}".format(
                   "follows" if order and order["following"] else "precedes",
                   (order or {}).get("tail", "?")))

        page.click("[data-testid=media-thumb]")
        page.wait_for_selector("[data-testid=lightbox]", timeout=10000)
        page.wait_for_timeout(600)
        shot(page, "07d-lightbox")
        downloadable = page.evaluate(
            """() => {
                const a = document.querySelector('[data-testid=lightbox-download]');
                const img = document.querySelector('[data-testid=lightbox] img');
                return {
                  hasDownload: !!(a && a.hasAttribute('download')),
                  name: a ? a.getAttribute('download') : null,
                  w: img ? img.naturalWidth : 0
                };
            }"""
        )
        record("media opens large and can be saved",
               downloadable["hasDownload"] and downloadable["w"] > 0,
               "{}x, download name {}".format(downloadable["w"], downloadable["name"]))
        page.keyboard.press("Escape")
        page.wait_for_selector("[data-testid=lightbox]", state="detached", timeout=5000)

        # Read the quota before the scroll checks below spend any more of it.
        quota_mid = quota_number(page)

        # Scrolling up mid-job means "I am reading"; the reply landing must not
        # drag the view back down.
        page.fill(COMPOSER, "sent then scrolled away")
        page.click("button:has-text('Send')")
        page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
        page.evaluate("() => document.querySelector('[data-testid=message-scroll]').scrollTo({top: 0})")
        page.wait_for_timeout(400)
        page.wait_for_selector("[data-testid=typing-bubble]", state="detached", timeout=60000)
        page.wait_for_timeout(1500)
        shot(page, "07c-stayed-put")
        top_after = page.evaluate(
            "() => document.querySelector('[data-testid=message-scroll]').scrollTop"
        )
        record("reading history is not interrupted", top_after < 120,
               "scrollTop {} after a reply landed while scrolled up".format(round(top_after)))

        # Auto-scroll can only be observed once the thread is taller than the
        # viewport, so push it over with one deliberately long message.
        page.fill(COMPOSER, "pad " * 400)
        page.click("button:has-text('Send')")
        page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
        page.wait_for_selector("[data-testid=typing-bubble]", state="detached", timeout=60000)
        page.wait_for_timeout(1500)
        shot(page, "07b-after-long-message")

        box = page.evaluate(
            """() => {
                const el = document.querySelector('[data-testid=message-scroll]')
                return {h: el.scrollHeight, t: el.scrollTop, c: el.clientHeight}
            }"""
        )
        overflow = box["h"] - box["c"]
        gap = box["h"] - box["t"] - box["c"]
        if overflow < 40:
            # Say so rather than banking a pass the layout could not have failed.
            record("view follows new messages", True,
                   "not proven here, the thread is only {}px taller than the viewport".format(round(overflow)))
        else:
            record("view follows new messages", gap < 80,
                   "{}px from the bottom with {}px of overflow".format(round(gap), round(overflow)))

        record("quota in the nav tracks the jobs spent", quota_mid == quota_before - 3,
               "{} -> {} after 3 jobs".format(quota_before, quota_mid))

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
