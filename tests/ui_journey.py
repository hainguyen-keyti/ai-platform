#!/usr/bin/env python3
"""One pass through the web interface as a user, against the real provider.

    INVITE_CODE=... ~/cloakbrowser-env/bin/python tests/ui_journey.py

Needs the running stack with the host worker in real mode. Costs two real turns,
one of them a picture, so run it when the browser flow changed, not on every
commit. Screenshots go to SHOT_DIR (default /tmp/ui_journey) so a person can look
at what rendered. Prints a PASS/FAIL table and exits non-zero on failure. The
waits are long on purpose: a picture takes minutes and the worker paces itself.
"""

import json
import os
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

import cloakbrowser

# The installed Chromium build, as open_session keeps it: a launch of its own looks hourly for a newer one to fetch.
os.environ.setdefault("CLOAKBROWSER_AUTO_UPDATE", "false")

WEB_URL = os.environ.get("WEB_URL", "http://localhost:5173")
WORKER_URL = os.environ.get("WORKER_URL", "http://localhost:8000")
INVITE_CODE = os.environ.get("INVITE_CODE", "")
SHOT_DIR = Path(os.environ.get("SHOT_DIR", "/tmp/ui_journey"))
COMPOSER = "input[placeholder^='Type a message']"
# Above the provider's own ceiling (REPLY_TIMEOUT 300s) plus pacing and the
# first-use browser launch, or the journey fails a wait it caused itself.
TURN_TIMEOUT_MS = 480000

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


def worker_health():
    try:
        with urllib.request.urlopen(WORKER_URL + "/health", timeout=5) as resp:
            return json.load(resp)
    except Exception as exc:
        return {"error": "{}: {}".format(type(exc).__name__, exc)}


def main():
    if not INVITE_CODE:
        sys.exit("set INVITE_CODE to the code the running API was started with")
    health = worker_health()
    if health.get("mode") != "real":
        sys.exit("the host worker must run in real mode; health says {}".format(
            health.get("mode") or health.get("error")))

    email = "journey-{}@aiplatform-acceptance.com".format(int(time.time()))
    password = "journey-pw-1"

    browser = cloakbrowser.launch(headless=True)
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    errors = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    try:
        page.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("text=AI Platform", timeout=20000)
        page.click("button:has-text('Create account')")
        page.fill("input[type=email]", email)
        page.fill("input[type=password]", password)
        page.fill("input[placeholder='name (optional)']", "Journey")
        page.fill("input[placeholder='invite code']", INVITE_CODE)
        page.click("form button[type=submit]")
        page.wait_for_selector("text=sign out", timeout=30000)
        shot(page, "01-signed-in")
        record("register and sign in", True, email)
        quota_before = quota_number(page)

        # Turn one: a picture, asked the way a person types it.
        started = time.time()
        page.fill(COMPOSER, "vẽ cho tôi một hình tròn màu cam trên nền trắng, thật đơn giản")
        page.click("button:has-text('Send')")
        page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
        page.wait_for_timeout(1500)
        shot(page, "02-waiting-for-the-picture")
        page.wait_for_selector("[data-testid=media-thumb]", timeout=TURN_TIMEOUT_MS)
        page.wait_for_selector("[data-testid=typing-bubble]", state="detached", timeout=60000)
        page.wait_for_timeout(1500)
        shot(page, "03-picture-in-the-thread")
        rendered = page.evaluate(
            """() => Array.from(document.images)
                 .filter(i => i.naturalWidth > 0 && i.src.startsWith('blob:'))
                 .map(i => ({w: i.naturalWidth, h: i.naturalHeight}))"""
        )
        record("a real picture arrives in the thread", bool(rendered),
               "{} image(s) after {:.0f}s, first {}".format(len(rendered), time.time() - started,
                                                            rendered[:1]))

        # Turn two, same conversation: have the model package what it just made.
        started = time.time()
        page.fill(COMPOSER, "gói tấm hình vừa rồi lại thành một file zip cho tôi tải về")
        page.click("button:has-text('Send')")
        page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
        page.wait_for_selector("[data-testid=file-card]", timeout=TURN_TIMEOUT_MS)
        page.wait_for_selector("[data-testid=typing-bubble]", state="detached", timeout=60000)
        page.wait_for_timeout(1500)
        shot(page, "04-file-card")
        card = page.evaluate(
            """() => {
                const el = document.querySelector('[data-testid=file-card]');
                return el ? el.textContent.trim().slice(0, 80) : null;
            }"""
        )
        record("the model's own zip arrives as a file card", bool(card),
               "card reads {!r} after {:.0f}s".format(card, time.time() - started))

        order = page.evaluate(
            """() => {
                const img = document.querySelector('[data-testid=media-thumb]');
                const card = document.querySelector('[data-testid=file-card]');
                if (!img || !card) return null;
                return !!(img.compareDocumentPosition(card) & Node.DOCUMENT_POSITION_FOLLOWING);
            }"""
        )
        record("the file sits below the picture it packaged", bool(order),
               "file card follows the thumbnail" if order else "order {}".format(order))

        # The platform's own archive of everything this conversation produced.
        with page.expect_download(timeout=30000) as caught:
            page.click("[data-testid=download-all]", timeout=10000)
        names = zipfile.ZipFile(caught.value.path()).namelist()
        shot(page, "05-download-all")
        record("download all packs the picture and the file", len(names) >= 2,
               "{} entries: {}".format(len(names), names[:4]))

        quota_after = quota_number(page)
        record("quota tracks two real turns", quota_after == quota_before - 2,
               "{} -> {}".format(quota_before, quota_after))

        health = worker_health()
        provider = (health.get("providers") or {}).get("chatgpt") or {}
        record("the worker read the memory switch before speaking", provider.get("memory") == "off",
               "memory {} settle {} p50 {}s".format(provider.get("memory"), provider.get("last_settle"),
                                                    provider.get("p50_latency_s")))

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
