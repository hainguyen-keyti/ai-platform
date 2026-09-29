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

import json
import os
import sys
import time
import zipfile
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

        # The team types Vietnamese; the switch must change the labels and back,
        # so the rest of this test can keep reading the English ones.
        try:
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Gửi')", timeout=5000)
            vietnamese = page.locator("button:has-text('Trò chuyện mới')").count()
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Send')", timeout=5000)
            shot(page, "03b-language")
            record("the language switch changes the labels and back", vietnamese == 1,
                   "Send became Gửi, New chat became Trò chuyện mới, and back")
        except Exception as exc:
            record("the language switch changes the labels and back", False,
                   "{}: no switch, or the labels did not change".format(type(exc).__name__))

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

        # Read the quota before the checks below spend any more of it.
        quota_mid = quota_number(page)

        page.fill(COMPOSER, "make me a zip file with my notes in it")
        page.click("button:has-text('Send')")
        page.wait_for_selector("[data-testid=file-card]", timeout=90000)
        page.wait_for_timeout(800)
        shot(page, "07e-file-card")
        card = page.evaluate(
            """() => {
                const el = document.querySelector('[data-testid=file-card]');
                const btn = el && el.querySelector('[data-testid=file-download]');
                const broken = Array.from(document.images).some(i => i.naturalWidth === 0);
                return {text: el ? el.textContent.trim().slice(0, 60) : null,
                        hasButton: !!btn, brokenImage: broken};
            }"""
        )
        record("a non image arrives as a file, not a broken picture",
               card["hasButton"] and not card["brokenImage"],
               "card reads {!r}, download button {}".format(card["text"], card["hasButton"]))

        # The model writes markdown; the bubble must show it rendered, and a
        # sandbox: link (the file is already a card) must not appear as a raw link.
        rendered_md = page.evaluate(
            """() => {
                const bubbles = Array.from(document.querySelectorAll('[data-testid=message-scroll] [data-testid=reply-bubble]'));
                const el = bubbles.find((b) => (b.textContent || '').includes('mock archive'));
                if (!el) return null;
                const text = el.textContent || '';
                return {strong: el.querySelectorAll('strong').length,
                        rawStars: text.includes('**'), rawSandbox: text.includes('sandbox:'),
                        sandboxLinks: el.querySelectorAll('a[href^="sandbox:"]').length};
            }"""
        )
        record("markdown in a reply renders, sandbox links become text",
               bool(rendered_md) and rendered_md["strong"] >= 1 and not rendered_md["rawStars"]
               and not rendered_md["rawSandbox"] and rendered_md["sandboxLinks"] == 0,
               "{}".format(rendered_md))

        # Everything this conversation produced, the picture and the file, in one
        # zip built by the platform; caught as a browser download, then opened.
        try:
            with page.expect_download(timeout=20000) as caught:
                page.click("[data-testid=download-all]", timeout=5000)
            names = zipfile.ZipFile(caught.value.path()).namelist()
            shot(page, "07g-download-all")
            record("download all media as one zip", len(names) == 2,
                   "{} entries: {}".format(len(names), names[:3]))
        except Exception as exc:
            record("download all media as one zip", False,
                   "{}: no Download all control, or no archive came out".format(type(exc).__name__))

        # Scrolling up mid-job means "I am reading"; the reply landing must not
        # drag the view back down.
        page.fill(COMPOSER, "sent then scrolled away")
        page.click("button:has-text('Send')")
        page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)

        # A follow-up in an already open conversation, which is the case that
        # broke: setting the same conversation id again reloads nothing, so the
        # message stayed invisible until its job finished. The window is short
        # on purpose. The job cannot finish inside it, so seeing the text here
        # can only mean it was shown without waiting for the answer.
        try:
            page.wait_for_selector("text=sent then scrolled away", timeout=3000)
            record("your message shows before the reply arrives", True,
                   "on screen within 3s, job still running")
        except Exception:
            record("your message shows before the reply arrives", False,
                   "not on screen after 3s, still waiting on the job")

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

        # Waiting minutes with no way out was the top complaint the surveyed
        # interfaces had all fixed: Send must become Stop while a job runs.
        # The slow phrase keeps the mock busy long enough that Stop is pressed
        # while the job is still running, whatever else the machine is doing.
        page.fill(COMPOSER, "take your time, cancel me please")
        page.click("button:has-text('Send')")
        page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
        stage = "finding the Stop control"
        try:
            page.click("button:has-text('Stop')", timeout=3000)
            # The page learns of the cancel on its next poll (1.5s apart), so the
            # bubble leaves within a few seconds; a job left running would keep
            # it for the mock's ten.
            stage = "waiting for the bubble to leave after Stop"
            page.wait_for_selector("[data-testid=typing-bubble]", state="detached", timeout=6000)
            page.wait_for_timeout(8000)
            replied = page.locator("text=mock reply from chatgpt to: take your time, cancel me please").count()
            record("stop cancels a running job", replied == 0,
                   "bubble gone within 6s, {} reply bubble(s) appeared afterwards".format(replied))
        except Exception as exc:
            page.wait_for_selector("[data-testid=typing-bubble]", state="detached", timeout=60000)
            record("stop cancels a running job", False,
                   "{} while {}".format(type(exc).__name__, stage))
        shot(page, "07f-stop")

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

        # A reply that lands while the tab is hidden must show in the title, and
        # the badge must clear when the person comes back.
        base_title = page.title()
        page.evaluate(
            """() => {
                Object.defineProperty(document, 'hidden', {configurable: true, get: () => true});
                Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'hidden'});
            }"""
        )
        page.fill(COMPOSER, "badge me while the tab is hidden")
        page.click("button:has-text('Send')")
        page.wait_for_selector("text=mock reply from chatgpt to: badge me", timeout=60000)
        page.wait_for_timeout(800)
        badged = page.title()
        page.evaluate(
            """() => {
                Object.defineProperty(document, 'hidden', {configurable: true, get: () => false});
                Object.defineProperty(document, 'visibilityState', {configurable: true, get: () => 'visible'});
                document.dispatchEvent(new Event('visibilitychange'));
            }"""
        )
        page.wait_for_timeout(500)
        cleared = page.title()
        record("a reply landing while the tab is hidden badges the title",
               badged.startswith("(1)") and cleared == base_title,
               "title {!r} while hidden, {!r} after returning".format(badged, cleared))

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

        # Back in the chat: the conversation can be renamed, found, and deleted
        # from the sidebar, and deleting it takes its media out of the gallery.
        page.click("nav button:has-text('chat')")
        page.wait_for_selector("[data-testid=message-scroll]", timeout=10000)
        try:
            page.click("[data-testid=rename-conversation]", timeout=5000)
            page.fill("[data-testid=rename-input]", "Renamed by the smoke test")
            page.keyboard.press("Enter")
            page.wait_for_selector("aside >> text=Renamed by the smoke test", timeout=5000)
            shot(page, "08b-renamed")
            record("a conversation can be renamed from the sidebar", True, "new title shown in the sidebar")
        except Exception as exc:
            record("a conversation can be renamed from the sidebar", False,
                   "{}: no rename control or the title did not change".format(type(exc).__name__))

        try:
            page.fill("[data-testid=conversation-search]", "Renamed by")
            page.wait_for_timeout(700)
            hits = page.locator("[data-testid=conversation-item]").count()
            page.fill("[data-testid=conversation-search]", "zzz-nothing-here")
            page.wait_for_timeout(700)
            misses = page.locator("[data-testid=conversation-item]").count()
            page.fill("[data-testid=conversation-search]", "")
            page.wait_for_timeout(700)
            record("search filters the sidebar", hits == 1 and misses == 0,
                   "{} hit(s) for the title, {} for nonsense".format(hits, misses))
        except Exception as exc:
            record("search filters the sidebar", False, "{}: no search box".format(type(exc).__name__))

        # Which providers a worker serves comes from the api; here it answers with a chosen reply
        # (the real request goes through for its CORS headers, only the body is replaced).
        chosen = {"providers": [{"name": "chatgpt", "served": False}, {"name": "grok", "served": False},
                                {"name": "gemini", "served": True}]}

        def answer_providers(route):
            if route.request.method != "GET":
                route.continue_()
                return
            real = route.fetch()
            headers = {k: v for k, v in real.headers.items() if k.lower() != "content-length"}
            headers["content-type"] = "application/json"
            route.fulfill(status=200, headers=headers, body=json.dumps(chosen))

        page.route("**/providers", answer_providers)
        try:
            page.click("nav button:has-text('gallery')")
            page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
            page.click("nav button:has-text('chat')")
            page.wait_for_selector("[data-testid=message-scroll]", timeout=10000)
            page.wait_for_timeout(1500)
            option = page.evaluate(
                """() => {
                    const o = document.querySelector('[data-testid=provider-select] option[value=grok]');
                    return o && {disabled: o.disabled, text: o.textContent.trim()};
                }"""
            )
            record("the selector greys out a provider no worker serves, with a note",
                   bool(option) and option["disabled"] is True and option["text"] != "grok", repr(option))
            # A filled composer, so a send button that is only off for an empty box proves nothing.
            page.fill(COMPOSER, "this must not be sent")
            notice = page.locator("[data-testid=provider-unserved]")
            shown = notice.count() > 0 and notice.first.is_visible()
            blocked = page.locator("button:has-text('Send')").first.is_disabled()
            shot(page, "08d-unserved")
            record("a conversation whose provider nobody serves says so and cannot send",
                   shown and blocked, "notice shown {}, send disabled {}".format(shown, blocked))
        except Exception as exc:
            record("the unserved provider checks ran", False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            page.unroute("**/providers")
            page.fill(COMPOSER, "")
            page.click("nav button:has-text('gallery')")
            page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
            page.click("nav button:has-text('chat')")
            page.wait_for_selector("[data-testid=message-scroll]", timeout=10000)

        try:
            page.once("dialog", lambda d: d.accept())
            page.click("[data-testid=delete-conversation]", timeout=5000)
            page.wait_for_selector("[data-testid=conversation-item]", state="detached", timeout=10000)
            page.click("nav button:has-text('gallery')")
            page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
            page.wait_for_timeout(1000)
            after = page.locator("text=/Gallery \\(\\d+\\)/").first.inner_text()
            shot(page, "08c-deleted")
            record("deleting a conversation from the sidebar removes it and its media",
                   after.strip().endswith("(0)"), "sidebar empty, gallery reads {!r}".format(after))
        except Exception as exc:
            record("deleting a conversation from the sidebar removes it and its media", False,
                   "{}: no delete control or the conversation stayed".format(type(exc).__name__))

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
