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
import re
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
    # Indices of console errors a check provokes on purpose (the refused send's 503).
    provoked = set()
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
            # Coming back to the chat opens no conversation; open the chatgpt one this test made.
            page.locator("[data-testid=conversation-item] button").first.click(timeout=5000)
            page.wait_for_selector("[data-testid=user-bubble]", timeout=10000)
            page.wait_for_timeout(800)
            # A filled composer, so a send button that is only off for an empty box proves nothing.
            page.fill(COMPOSER, "this must not be sent")
            notice = page.locator("[data-testid=provider-unserved]")
            shown = notice.count() > 0 and notice.first.is_visible()
            blocked = page.locator("button:has-text('Send')").first.is_disabled()
            scripts = page.locator("button:has-text('Video script')")
            scripts_held = scripts.count() > 0 and all(scripts.nth(i).is_disabled() for i in range(scripts.count()))
            shot(page, "08d-unserved")
            record("a conversation whose provider nobody serves says so and cannot send",
                   shown and blocked and scripts_held, "notice shown {}, send disabled {}, video script held {}"
                   .format(shown, blocked, scripts_held))
        except Exception as exc:
            record("the unserved provider checks ran", False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            page.unroute("**/providers")

        # A list a minute old can still say served when the api already refuses: the refusal must
        # keep the words in the box and bring the notice, not an english error. The api is never
        # reached here; its 503 is played in the browser, so no job is made.
        everyone = {"providers": [{"name": n, "served": True} for n in ("chatgpt", "grok", "gemini")]}

        def answer_served(route):
            if route.request.method != "GET":
                route.continue_()
                return
            real = route.fetch()
            headers = {k: v for k, v in real.headers.items() if k.lower() != "content-length"}
            headers["content-type"] = "application/json"
            route.fulfill(status=200, headers=headers, body=json.dumps(everyone))

        def refuse_chat(route):
            if route.request.method != "POST":
                route.continue_()
                return
            route.fulfill(status=503, headers={"access-control-allow-origin": "*",
                                               "content-type": "application/json"},
                          body=json.dumps({"detail": "no worker is serving chatgpt right now; try again later"}))

        page.route("**/providers", answer_served)
        try:
            page.click("nav button:has-text('gallery')")
            page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
            page.click("nav button:has-text('chat')")
            page.wait_for_selector("[data-testid=message-scroll]", timeout=10000)
            page.locator("[data-testid=conversation-item] button").first.click(timeout=5000)
            page.wait_for_selector("[data-testid=user-bubble]", timeout=10000)
            page.wait_for_timeout(800)
            page.route("**/chat", refuse_chat)
            page.fill(COMPOSER, "sent into a stale list")
            start = len(errors)
            page.click("button:has-text('Send')")
            page.wait_for_timeout(1500)
            provoked.update(i for i in range(start, len(errors)) if "503" in errors[i])
            kept = page.input_value(COMPOSER)
            notice = page.locator("[data-testid=provider-unserved]")
            shown = notice.count() > 0 and notice.first.is_visible()
            english = page.locator("header .text-red-600").count()
            shot(page, "08e-refused")
            record("a send the api refuses keeps the words and shows the notice",
                   kept == "sent into a stale list" and shown and english == 0,
                   "box {!r}, notice shown {}, header errors {}".format(kept, shown, english))
        except Exception as exc:
            record("a send the api refuses keeps the words and shows the notice", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            page.unroute("**/chat")
            page.unroute("**/providers")
            page.fill(COMPOSER, "")
            page.click("nav button:has-text('gallery')")
            page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
            page.click("nav button:has-text('chat')")
            page.wait_for_selector("[data-testid=message-scroll]", timeout=10000)

        # A phone, 390x844, signed in as the same person (the session token from this page): nothing
        # scrolls sideways, Send is on the screen, and the list sits behind a button until needed.
        phone = browser.new_context(viewport={"width": 390, "height": 844})
        phone.add_init_script("localStorage.setItem('token', {!r}); localStorage.setItem('lang', 'en');".format(
            page.evaluate("() => localStorage.getItem('token')")))
        small = phone.new_page()
        small.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        fits = """() => {
            const box = (n) => { if (!n) return null; const r = n.getBoundingClientRect();
                return {left: Math.round(r.left), right: Math.round(r.right)}; };
            const navButtons = document.querySelectorAll('nav button');
            return {screen: window.innerWidth, page: document.scrollingElement.scrollWidth,
                    send: box(document.querySelector('form button[type=submit]')),
                    language: box(document.querySelector('[data-testid=language-switch]')),
                    signOut: box(navButtons[navButtons.length - 1])};
        }"""
        try:
            small.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
            small.wait_for_selector("[data-testid=provider-select]", timeout=20000)
            small.wait_for_timeout(1000)
            got = small.evaluate(fits)
            send = got["send"] or {}
            shot(small, "10-phone-chat")
            record("on a phone the chat does not scroll sideways and Send is on screen",
                   got["page"] <= got["screen"] and send.get("left", -1) >= 0
                   and send.get("right", 10 ** 6) <= got["screen"], repr(got))
        except Exception as exc:
            record("on a phone the chat does not scroll sideways and Send is on screen", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        try:
            item = small.locator("[data-testid=conversation-item]").first
            item.wait_for(state="attached", timeout=10000)
            hidden_first = not item.is_visible()
            small.click("[data-testid=open-conversations]", timeout=5000)
            listed = item.is_visible()
            small.locator("[data-testid=conversation-item] button").first.click(timeout=5000)
            small.wait_for_selector("[data-testid=user-bubble]", timeout=10000)
            small.wait_for_timeout(500)
            closed = not item.is_visible()
            shot(small, "11-phone-conversation")
            record("on a phone the list opens from its button and closes on a pick",
                   hidden_first and listed and closed,
                   "hidden at first {}, shown {}, closed after the pick {}".format(hidden_first, listed, closed))
        except Exception as exc:
            record("on a phone the list opens from its button and closes on a pick", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        try:
            small.click("nav button:has-text('gallery')")
            small.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
            small.wait_for_timeout(800)
            got = small.evaluate(fits)
            on_screen = all(b and b["left"] >= 0 and b["right"] <= got["screen"]
                            for b in (got["language"], got["signOut"]))
            shot(small, "12-phone-gallery")
            record("on a phone the gallery page does not scroll sideways and the nav fits",
                   got["page"] <= got["screen"] and on_screen, repr(got))
        except Exception as exc:
            record("on a phone the gallery page does not scroll sideways and the nav fits", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))

        # The header names the conversation picked from the list before it has loaded: its request
        # is held here until the header has been read.
        held = []

        def hold_conversation(route):
            if route.request.method == "GET":
                held.append(route)
            else:
                route.continue_()

        try:
            small.click("nav button:has-text('chat')")
            small.wait_for_selector("[data-testid=message-scroll]", timeout=10000)
            small.wait_for_timeout(800)
            title = small.locator("[data-testid=conversation-title]")
            fresh = title.inner_text().strip() if title.count() else None
            small.click("[data-testid=open-conversations]", timeout=5000)
            first = small.locator("[data-testid=conversation-item] button").first
            wanted = first.evaluate("b => b.lastChild.textContent").strip()
            small.route("**/conversations/*", hold_conversation)
            first.click(timeout=5000)
            small.wait_for_timeout(500)
            named = title.inner_text().strip() if title.count() else None
            record("on a phone the header names the conversation picked before it loads",
                   fresh == "New chat" and named == wanted and len(held) == 1,
                   "before a pick {!r}, after {!r}, wanted {!r}, requests held {}".format(fresh, named, wanted, len(held)))
        except Exception as exc:
            record("on a phone the header names the conversation picked before it loads", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            for route in held:
                route.continue_()
            small.unroute("**/conversations/*")

        # The list covers the header where errors are shown, so a failure from the list is shown in
        # the list too. The rename is refused in the browser; the api never sees it.
        def refuse_rename(route):
            if route.request.method != "PATCH":
                route.continue_()
                return
            route.fulfill(status=500, headers={"access-control-allow-origin": "*", "content-type": "application/json"},
                          body=json.dumps({"detail": "rename refused by the smoke test"}))

        try:
            small.wait_for_selector("[data-testid=user-bubble]", timeout=10000)
            small.route("**/conversations/*", refuse_rename)
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.locator("[data-testid=rename-conversation]").first.click(timeout=5000)
            small.fill("[data-testid=rename-input]", "never saved")
            start = len(errors)
            small.press("[data-testid=rename-input]", "Enter")
            small.wait_for_timeout(800)
            provoked.update(i for i in range(start, len(errors)) if "500" in errors[i])
            in_list = small.locator("aside").get_by_text("rename refused by the smoke test")
            shown = in_list.count() > 0 and in_list.first.is_visible()
            shot(small, "13-phone-list-error")
            record("on a phone an error from the list shows in the list", shown,
                   "{} copy of the error in the list, visible {}".format(in_list.count(), shown))
        except Exception as exc:
            record("on a phone an error from the list shows in the list", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            small.unroute("**/conversations/*")
            if small.locator("[data-testid=close-conversations]").is_visible():
                small.click("[data-testid=close-conversations]")

        # The list as a panel, by keyboard and screen reader: its button says whether it is open and
        # which element it opens, focus goes in and comes back, Tab never reaches the chat under it,
        # Escape closes it, and Escape in a rename box only ends the rename.
        try:
            opener = small.locator("[data-testid=open-conversations]")
            shut = opener.get_attribute("aria-expanded")
            name = opener.get_attribute("aria-label")
            opener.click(timeout=5000)
            small.wait_for_timeout(300)
            opened = small.evaluate(
                """() => {
                    const opener = document.querySelector('[data-testid=open-conversations]');
                    const list = document.getElementById(opener.getAttribute('aria-controls') || '-');
                    return {expanded: opener.getAttribute('aria-expanded'),
                            controls: !!list && !!list.querySelector('[data-testid=conversation-search]'),
                            heading: list ? (list.querySelector('h2')?.textContent || null) : null,
                            focus: document.activeElement?.getAttribute('data-testid') || null};
                }"""
            )
            leaked = 0
            for _ in range(12):
                small.keyboard.press("Tab")
                leaked += small.evaluate("() => document.activeElement.closest('section') ? 1 : 0")
            small.locator("[data-testid=rename-conversation]").first.click(timeout=5000)
            small.keyboard.press("Escape")
            small.wait_for_timeout(300)
            renamed = small.evaluate(
                "() => ({renaming: !!document.querySelector('[data-testid=rename-input]'),"
                " open: !!document.querySelector('[data-testid=conversation-search]').offsetParent})")
            small.keyboard.press("Escape")
            small.wait_for_timeout(300)
            closed = small.evaluate(
                "() => ({open: !!document.querySelector('[data-testid=conversation-search]').offsetParent,"
                " focus: document.activeElement?.getAttribute('data-testid') || null,"
                " expanded: document.querySelector('[data-testid=open-conversations]').getAttribute('aria-expanded')})")
            record("on a phone the list works by keyboard and screen reader",
                   shut == "false" and name == "Open conversations" and opened["expanded"] == "true"
                   and opened["controls"] and opened["heading"] == "Conversations"
                   and opened["focus"] == "close-conversations" and leaked == 0
                   and not renamed["renaming"] and renamed["open"]
                   and not closed["open"] and closed["focus"] == "open-conversations" and closed["expanded"] == "false",
                   "closed {!r}, name {!r}, opened {}, tabs into the chat {}, escape in a rename {}, escape {}"
                   .format(shut, name, opened, leaked, renamed, closed))
        except Exception as exc:
            record("on a phone the list works by keyboard and screen reader", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            if small.locator("[data-testid=close-conversations]").is_visible():
                small.click("[data-testid=close-conversations]")

        # Big enough to hit with a thumb: the list button 40px and as tall as the provider select,
        # every control in a list row at least 24px wide and 40px tall, named for a screen reader,
        # and the panel's close a word, not a second × above each row's delete.
        try:
            boxes = small.evaluate(
                """() => {
                    const box = (n) => { const r = n.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height)}; };
                    return {opener: box(document.querySelector('[data-testid=open-conversations]')),
                            select: box(document.querySelector('[data-testid=provider-select]'))};
                }"""
            )
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.wait_for_timeout(300)
            rows = small.evaluate(
                """() => Array.from(document.querySelectorAll('[data-testid=conversation-item]')).map((row) => {
                    const box = (n) => { const r = n.getBoundingClientRect(); return {w: Math.round(r.width), h: Math.round(r.height)}; };
                    const [pick, rename, remove] = row.querySelectorAll('button');
                    return {pick: box(pick), rename: box(rename), remove: box(remove),
                            names: [rename.getAttribute('aria-label'), remove.getAttribute('aria-label')]};
                })"""
            )
            close_text = small.locator("[data-testid=close-conversations]").inner_text().strip()
            shot(small, "14-phone-list-open")

            def thumb(b):
                return b["w"] >= 24 and b["h"] >= 40

            record("on a phone the list's controls are big enough to tap, and named",
                   boxes["opener"]["w"] >= 40 and boxes["opener"]["h"] >= 40
                   and boxes["select"]["h"] == boxes["opener"]["h"] and close_text == "Close" and bool(rows)
                   and all(thumb(r["pick"]) and thumb(r["rename"]) and thumb(r["remove"])
                           and r["names"] == ["Rename", "Delete"] for r in rows),
                   "{}, close reads {!r}, rows {}".format(boxes, close_text, rows))
        except Exception as exc:
            record("on a phone the list's controls are big enough to tap, and named", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            if small.locator("[data-testid=close-conversations]").is_visible():
                small.click("[data-testid=close-conversations]")

        # An iPhone zooms into any field under 16px the moment it is tapped: 16px on a phone, 14px
        # from 768px as before. Widening the window with the list open must leave the chat usable.
        fonts = """() => {
            const size = (sel) => { const n = document.querySelector(sel); return n ? parseFloat(getComputedStyle(n).fontSize) : null; };
            return {composer: size('form input'), search: size('[data-testid=conversation-search]'),
                    select: size('[data-testid=provider-select]')};
        }"""
        try:
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.locator("[data-testid=rename-conversation]").first.click(timeout=5000)
            rename_size = small.evaluate(
                "() => parseFloat(getComputedStyle(document.querySelector('[data-testid=rename-input]')).fontSize)")
            small.keyboard.press("Escape")
            narrow = small.evaluate(fonts)
            small.set_viewport_size({"width": 1024, "height": 800})
            small.wait_for_timeout(800)
            wide = small.evaluate(fonts)
            usable = False
            for _ in range(6):
                small.focus("form input")
                usable = small.evaluate("() => document.activeElement === document.querySelector('form input')")
                if usable:
                    break
                small.wait_for_timeout(500)
            small.set_viewport_size({"width": 390, "height": 844})
            small.wait_for_timeout(500)
            reopened = small.locator("[data-testid=conversation-search]").is_visible()
            record("on a phone the fields are 16px so an iPhone does not zoom, 14px from 768px",
                   rename_size >= 16 and all(v >= 16 for v in narrow.values())
                   and all(v == 14 for v in wide.values()) and usable and not reopened,
                   "phone {} rename {}, wide {}, chat usable after widening with the list open {}, list back over"
                   " the chat after narrowing again {}".format(narrow, rename_size, wide, usable, reopened))
        except Exception as exc:
            record("on a phone the fields are 16px so an iPhone does not zoom, 14px from 768px", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            small.set_viewport_size({"width": 390, "height": 844})
            small.wait_for_timeout(500)
            if small.locator("[data-testid=close-conversations]").is_visible():
                small.click("[data-testid=close-conversations]")

        # The list also closes on its Close button and on New chat, and the phone layout ends at
        # 768px: a panel behind a button up to 767px, a sidebar with no button from 768px.
        search = small.locator("[data-testid=conversation-search]")
        try:
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.click("[data-testid=close-conversations]", timeout=5000)
            small.wait_for_timeout(300)
            by_close = not search.is_visible()
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.click("aside button:has-text('New chat')", timeout=5000)
            small.wait_for_timeout(300)
            by_new = not search.is_visible()
            fresh = small.locator("[data-testid=conversation-title]").inner_text().strip()
            edge = {}
            for width in (767, 768):
                small.set_viewport_size({"width": width, "height": 900})
                small.wait_for_timeout(300)
                edge[width] = {"button": small.locator("[data-testid=open-conversations]").is_visible(),
                               "list": search.is_visible()}
            record("on a phone the list closes on Close and on New chat, and the phone layout ends at 768px",
                   by_close and by_new and fresh == "New chat"
                   and edge[767] == {"button": True, "list": False} and edge[768] == {"button": False, "list": True},
                   "closed by Close {}, by New chat {} ({!r}), at 767 and 768 {}".format(by_close, by_new, fresh, edge))
        except Exception as exc:
            record("on a phone the list closes on Close and on New chat, and the phone layout ends at 768px", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            small.set_viewport_size({"width": 390, "height": 844})
            small.wait_for_timeout(500)
            if small.locator("[data-testid=close-conversations]").is_visible():
                small.click("[data-testid=close-conversations]")

        # Wide content in a conversation: a link the person pasted and a code block in the reply,
        # added in the browser to the real conversation. Nothing is cut off on the left, the thread
        # does not scroll sideways, and the page, Send and the nav still fit.
        link = ("https://docs.google.com/document/d/1aBcDeFgHiJkLmNoPqRsTuVwXyZ0123456789abcdefGHIJKLmnop/"
                "edit?usp=sharing")
        code = "def long_function_name_for_testing(argument_one, argument_two, argument_three, argument_four):"

        def widen(route):
            if route.request.method != "GET":
                route.continue_()
                return
            real = route.fetch()
            body = real.json()
            stamp = body["messages"][-1]["created_at"] if body.get("messages") else "2026-01-01 00:00:00"
            body["messages"] = body.get("messages", []) + [
                {"id": "wide-1", "role": "user", "content": link, "created_at": stamp, "media": []},
                {"id": "wide-2", "role": "assistant", "content": "Here:\n\n```\n" + code + "\n```",
                 "created_at": stamp, "media": []}]
            headers = {k: v for k, v in real.headers.items() if k.lower() != "content-length"}
            route.fulfill(status=200, headers=headers, body=json.dumps(body))

        try:
            small.route("**/conversations/*", widen)
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.locator("[data-testid=conversation-item] button").first.click(timeout=5000)
            small.wait_for_selector("[data-testid=user-bubble]:has-text('docs.google.com')", timeout=10000)
            small.wait_for_timeout(1000)
            got = small.evaluate(
                """(link) => {
                    const area = document.querySelector('[data-testid=message-scroll]');
                    area.scrollLeft = 0;
                    const bubble = [...document.querySelectorAll('[data-testid=user-bubble]')].find((n) => n.textContent === link);
                    const range = document.createRange();
                    const text = document.createTreeWalker(bubble, NodeFilter.SHOW_TEXT).nextNode();
                    range.setStart(text, 0);
                    range.setEnd(text, 1);
                    const send = document.querySelector('form button[type=submit]').getBoundingClientRect();
                    return {screen: window.innerWidth, page: document.scrollingElement.scrollWidth,
                            sendRight: Math.round(send.right), firstChar: Math.round(range.getBoundingClientRect().left),
                            areaLeft: Math.round(area.getBoundingClientRect().left),
                            sideways: area.scrollWidth - area.clientWidth,
                            email: document.querySelector('nav').innerText.includes('@')};
                }""", link)
            shot(small, "15-phone-wide-content")
            record("on a phone wide content in a conversation is not cut off and nothing scrolls sideways",
                   got["page"] <= got["screen"] and got["sendRight"] <= got["screen"]
                   and got["firstChar"] >= got["areaLeft"] and got["sideways"] == 0 and not got["email"], repr(got))
        except Exception as exc:
            record("on a phone wide content in a conversation is not cut off and nothing scrolls sideways", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            small.unroute("**/conversations/*")

        # The nav on a phone: one row from 360px in both languages, its right side wrapping as one
        # below that, the quota saying what is left, the brand still shown from 640px; and the list's
        # title and its button read right in both languages.
        try:
            shape = """() => {
                const nav = document.querySelector('nav');
                const buttons = nav.querySelectorAll('button');
                // The quota is the first shown text in the nav with a digit in it.
                const walker = document.createTreeWalker(nav, NodeFilter.SHOW_TEXT);
                let quota = null;
                while (!quota && walker.nextNode()) {
                    const range = document.createRange();
                    range.selectNodeContents(walker.currentNode);
                    const r = range.getBoundingClientRect();
                    if (/\\d/.test(walker.currentNode.textContent) && r.width > 0) quota = r;
                }
                const middle = (r) => (r.top + r.bottom) / 2;
                const rows = [quota, document.querySelector('[data-testid=language-switch]').getBoundingClientRect(),
                              buttons[buttons.length - 1].getBoundingClientRect()].map((r) => r ? middle(r) : NaN);
                // An item whose words wrap inside it is taller than one line of text.
                const heights = [...nav.querySelectorAll('button, span')].map((n) => n.getBoundingClientRect().height);
                return {h: Math.round(nav.getBoundingClientRect().height), text: nav.innerText,
                        tallest: Math.round(Math.max(...heights)),
                        together: Math.max(...rows) - Math.min(...rows) < 6,
                        screen: window.innerWidth, page: document.scrollingElement.scrollWidth,
                        opener: document.querySelector('[data-testid=open-conversations]').getAttribute('aria-label'),
                        heading: document.querySelector('aside h2')?.textContent || null};
            }"""
            seen = {}
            for lang, other in (("en", "Gửi"), ("vi", "Send")):
                for width in (320, 344, 360, 390):
                    small.set_viewport_size({"width": width, "height": 844})
                    small.wait_for_timeout(250)
                    seen[(lang, width)] = small.evaluate(shape)
                small.click("[data-testid=language-switch]", timeout=5000)
                small.wait_for_selector("button:has-text('{}')".format(other), timeout=5000)
            small.set_viewport_size({"width": 1024, "height": 800})
            small.wait_for_timeout(250)
            brand = small.locator("nav").get_by_text("AI Platform").first.is_visible()
            small.set_viewport_size({"width": 390, "height": 844})
            one_row = {(l, w): seen[(l, w)]["h"] for l in ("en", "vi") for w in (360, 390)}
            apart = [k for k, v in seen.items() if not v["together"] or v["page"] > v["screen"] or v["tallest"] >= 30]
            words = (re.search(r"\b\d+ left\b", seen[("en", 390)]["text"]) is not None
                     and re.search(r"\bcòn \d+", seen[("vi", 390)]["text"]) is not None)
            record("on a phone the nav is one row from 360px in both languages, its right side kept together",
                   all(h < 50 for h in one_row.values()) and not apart and words and brand,
                   "nav heights {}, right side split, page too wide or words wrapped inside an item at {}"
                   " (tallest item {}), quota words {}, brand from 640px {}"
                   .format(one_row, apart, {k: v["tallest"] for k, v in seen.items()}, words, brand))
            record("the list's title and its button's name read right in both languages",
                   seen[("en", 390)]["opener"] == "Open conversations" and seen[("en", 390)]["heading"] == "Conversations"
                   and seen[("vi", 390)]["opener"] == "Mở danh sách trò chuyện"
                   and seen[("vi", 390)]["heading"] == "Các cuộc trò chuyện",
                   "en {!r} / {!r}, vi {!r} / {!r}".format(seen[("en", 390)]["opener"], seen[("en", 390)]["heading"],
                                                          seen[("vi", 390)]["opener"], seen[("vi", 390)]["heading"]))
        except Exception as exc:
            for check in ("on a phone the nav is one row from 360px in both languages, its right side kept together",
                          "the list's title and its button's name read right in both languages"):
                record(check, False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            phone.close()

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

        real_errors = [e for i, e in enumerate(errors) if "favicon" not in e.lower() and i not in provoked]
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
