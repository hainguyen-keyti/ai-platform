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
import struct
import sys
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from pathlib import Path
from urllib.parse import urlparse

import cloakbrowser

WEB_URL = os.environ.get("WEB_URL", "http://localhost:5173")
API_URL = os.environ.get("API_URL", "http://localhost:3000")
INVITE_CODE = os.environ.get("INVITE_CODE", "")
SHOT_DIR = Path(os.environ.get("SHOT_DIR", "/tmp/ui_shots"))
# Prefix match so a reworded placeholder does not break every step at once.
COMPOSER = "input[placeholder^='Type a message']"

steps = []


def record(name, ok, detail=""):
    steps.append((name, ok, detail))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)
    return ok


# The last screenshot taken: a console error is kept with it, so a run says where the error came.
STEP = ["start"]


def heard(errors):
    """A console listener that keeps each error with the address it came from and the step."""
    def listen(message):
        if message.type == "error":
            errors.append("{} @ {} after {}".format(
                message.text, (message.location or {}).get("url", "")[:100], STEP[0]))
    return listen


def quota_number(page):
    text = page.locator("text=/\\d+ left/").first.inner_text()
    return int("".join(c for c in text.split("·")[-1] if c.isdigit()))


# The page's own smooth scroll made slow, as on a busy or slow device: a scrollTo with behavior
# 'smooth' becomes a 4 second animation, and a new one replaces the one running. A frame can be
# stamped before the call that started it; its progress is held at 0, since a real smooth scroll
# never moves back (it did here by half a pixel, about 1 run in 7, and the page let go of the tail).
SLOW_SMOOTH = """(() => {
  const native = Element.prototype.scrollTo;
  const running = new WeakMap();
  Element.prototype.scrollTo = function (options) {
    if (!options || typeof options !== 'object' || options.behavior !== 'smooth') return native.apply(this, arguments);
    const el = this, start = el.scrollTop, began = performance.now(), token = {};
    const target = Math.min(options.top, el.scrollHeight - el.clientHeight);
    running.set(el, token);
    const step = (now) => {
      if (running.get(el) !== token) return;
      const t = Math.min(1, Math.max(0, now - began) / 4000);
      el.scrollTop = start + (target - start) * t;
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  };
})();"""


def png(width, height):
    """A plain picture, so one can be answered in the browser without a file on disk."""
    raw = b"".join(b"\x00" + b"\x80\x80\xff" * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xffffffff)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


# The first video on screen, once it knows its length (or has given up): what a person can play.
PLAYABLE = """() => new Promise((resolve) => {
  const v = document.querySelector('[data-testid=media-video]');
  if (!v) return resolve({found: false});
  let told = false;
  const done = () => {
    if (told) return;
    told = true;
    resolve({found: true, state: v.readyState, duration: v.duration, width: v.videoWidth,
             blob: (v.currentSrc || v.src || '').startsWith('blob:'), named: !!v.getAttribute('aria-label'),
             download: !!document.querySelector('[data-testid=video-download][download]')});
  };
  if (v.readyState >= 1) return done();
  v.addEventListener('loadedmetadata', done, {once: true});
  v.addEventListener('error', done, {once: true});
  setTimeout(done, 10000);
})"""


def playable(found):
    return bool(found.get("found") and found.get("state", 0) >= 1 and (found.get("duration") or 0) > 0
                and found.get("width", 0) > 0 and found.get("blob") and found.get("download")
                and found.get("named"))


def shot(page, name):
    STEP[0] = name
    SHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SHOT_DIR / "{}.png".format(name)
    page.screenshot(path=str(path), full_page=False)
    return path


# Every text on screen against WCAG AA: 4.5:1, or 3:1 from 24px (18.66px bold). A text's background
# is the nearest opaque one behind it, with the translucent ones between laid over it; a placeholder
# is measured in its empty field. Disabled controls and the chat under the phone's open list are not.
FAINT = r"""() => {
  const parse = (c) => {
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
  };
  const over = (top, under) => [0, 1, 2].map((i) => top[i] * top[3] + under[i] * (1 - top[3])).concat([1]);
  const behind = (el) => {
    const layers = [];
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const c = parse(getComputedStyle(n).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    return layers.reverse().reduce((bg, c) => over(c, bg), [255, 255, 255, 1]);
  };
  const opacity = (el) => {
    let o = 1;
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) o *= Number(getComputedStyle(n).opacity);
    return o;
  };
  const shown = (el) => el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden'
    && !el.closest('[disabled], [inert]');
  const ratio = (el, color) => {
    const bg = behind(el), c = parse(color);
    const fg = over([c[0], c[1], c[2], c[3] * opacity(el)], bg);
    const a = lum(fg), b = lum(bg);
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  };
  const floor = (cs) => {
    const size = parseFloat(cs.fontSize);
    return size >= 24 || (Number(cs.fontWeight) >= 700 && size >= 18.66) ? 3 : 4.5;
  };
  let measured = 0;
  const faint = [];
  for (const el of document.querySelectorAll('body *')) {
    const own = [...el.childNodes].filter((n) => n.nodeType === 3 && n.textContent.trim())
      .map((n) => n.textContent.trim()).join(' ');
    if (!own || !shown(el)) continue;
    const cs = getComputedStyle(el), r = ratio(el, cs.color);
    measured += 1;
    if (r < floor(cs)) faint.push({text: own.slice(0, 30), ratio: Math.round(r * 100) / 100});
  }
  for (const el of document.querySelectorAll('input[placeholder], textarea[placeholder]')) {
    if (el.value || !el.placeholder || !shown(el)) continue;
    const cs = getComputedStyle(el), r = ratio(el, getComputedStyle(el, '::placeholder').color);
    measured += 1;
    if (r < floor(cs)) faint.push({text: 'placeholder ' + el.placeholder.slice(0, 20), ratio: Math.round(r * 100) / 100});
  }
  return {measured, faint};
}"""


def faint_texts(page, where, found, seen):
    """Adds each text on the page under its contrast floor to found; seen[where] counts the texts measured."""
    try:
        got = page.evaluate(FAINT)
        seen[where] = got["measured"]
        found += ["{}: {!r} {}:1".format(where, f["text"], f["ratio"]) for f in got["faint"]]
    except Exception as exc:
        seen[where] = 0
        found.append("{}: not measured, {}: {}".format(where, type(exc).__name__, str(exc)[:80]))


def select_name(page):
    """The provider select's accessible name as a screen reader gets it, None when it has none."""
    first = page.locator("[data-testid=provider-select]").aria_snapshot().splitlines()[0]
    named = re.match(r'- combobox "((?:[^"\\]|\\.)*)"', first)
    return named.group(1) if named else None


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
    page.on("console", heard(errors))
    # Texts under their contrast floor and the texts measured, by screen; the select's names by state.
    faint, texts_on, select_names = [], {}, {}

    try:
        page.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_selector("text=AI Platform", timeout=20000)
        shot(page, "01-login")
        record("login page renders", True, page.title())
        faint_texts(page, "login, sign in", faint, texts_on)

        page.click("button:has-text('Create account')")
        faint_texts(page, "login, create account", faint, texts_on)
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

        # A new person's list is empty and says so, but only once it has answered (444ms after a
        # load, measured): its first answer after a reload is held here, and a note shown while it
        # is held would be a guess.
        held_list = []

        def hold_list(route):
            if route.request.method == "GET":
                held_list.append(route)
            else:
                route.continue_()

        empty = {}
        try:
            page.route("**/conversations", hold_list)
            try:
                page.reload(wait_until="domcontentloaded")
                page.wait_for_selector("aside button:has-text('New chat')", timeout=20000)
                page.wait_for_timeout(1000)
                empty["held"] = len(held_list)
                empty["while held"] = page.locator("aside").get_by_text("No conversations yet.").count()
            finally:
                for route in held_list:
                    route.continue_()
                page.unroute("**/conversations")
            page.wait_for_timeout(1000)
            empty["after"] = page.locator("aside").get_by_text("No conversations yet.", exact=True).is_visible()
            shot(page, "03c-empty-list")
            record("the empty list's note waits for the list's first answer",
                   empty["held"] >= 1 and empty["while held"] == 0 and empty["after"],
                   "requests held {}, notes while held {}, note after the answer {}".format(
                       empty["held"], empty["while held"], empty["after"]))
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Gửi')", timeout=5000)
            empty["vi"] = page.locator("aside").get_by_text("Chưa có cuộc trò chuyện nào.", exact=True).is_visible()
            select_names["new chat, vi"] = select_name(page)
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Send')", timeout=5000)
            select_names["new chat, en"] = select_name(page)
        except Exception as exc:
            record("the empty list's note waits for the list's first answer", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        faint_texts(page, "a new chat, the list empty", faint, texts_on)
        page.click("nav button:has-text('gallery')")
        page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
        page.wait_for_timeout(500)
        faint_texts(page, "the gallery, empty", faint, texts_on)
        page.click("nav button:has-text('chat')")
        page.wait_for_selector("[data-testid=message-scroll]", timeout=10000)

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

        # The list has answered, empty, before the first send: a list first asked after the send would
        # already hold the new conversation and prove nothing about the reply's wait.
        first_turn = {}
        try:
            page.wait_for_selector("aside >> text=No conversations yet.", timeout=10000)
            first_turn["empty before the send"] = True
        except Exception as exc:
            first_turn["empty before the send"] = "{}: not seen".format(type(exc).__name__)

        page.fill(COMPOSER, "hello from the ui smoke test")
        shot(page, "04-message-typed")
        page.click("button:has-text('Send')")

        # Needs MOCK_DELAY_SECONDS on the worker: a mock that answers instantly
        # leaves no waiting state to look at.
        try:
            page.wait_for_selector("[data-testid=typing-bubble]", timeout=15000)
            page.wait_for_timeout(1200)
            faint_texts(page, "the typing bubble", faint, texts_on)
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
        # The api makes the conversation before it answers the send: the list shows it during the first
        # reply instead of calling itself empty, and its note's live region is there before any note.
        try:
            first_turn.update({"rows": page.locator("[data-testid=conversation-item]").count(),
                               "notes": page.locator("aside").get_by_text("No conversations yet.").count(),
                               "status regions": page.locator("aside [role=status]").count(),
                               "reply pending": page.locator("[data-testid=typing-bubble]").count() == 1})
        except Exception as exc:
            first_turn["error"] = "{}: {}".format(type(exc).__name__, str(exc)[:120])

        page.wait_for_selector("text=mock reply from chatgpt", timeout=60000)
        shot(page, "05-chat-reply")
        record("chat message round trip", True, "assistant bubble rendered")

        # The select is named for what it picks, also once a conversation holds it (its title then
        # says why it is locked, which is a description, not a name).
        try:
            select_names["open, en"] = select_name(page)
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Gửi')", timeout=5000)
            select_names["open, vi"] = select_name(page)
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Send')", timeout=5000)
        except Exception as exc:
            select_names["error"] = "{}: {}".format(type(exc).__name__, str(exc)[:120])
        wanted = {"new chat, en": "Provider", "new chat, vi": "Nhà cung cấp",
                  "open, en": "Provider", "open, vi": "Nhà cung cấp"}
        record("the provider select is named, with or without a conversation, in both languages",
               select_names == wanted, repr(select_names))

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
                const bubbles = document.querySelectorAll('[data-testid=message-scroll] [data-testid=user-bubble], '
                    + '[data-testid=message-scroll] [data-testid=reply-bubble]');
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

        # The open conversation's row is highlighted; the pointer on its controls changes their colour.
        faint_texts(page, "a reply with a picture and a file card", faint, texts_on)
        for control, where in (("delete-conversation", "the pointer on a row's delete"),
                               ("rename-conversation", "the pointer on a row's rename")):
            try:
                page.locator("[data-testid=conversation-item]").first.locator(
                    "[data-testid={}]".format(control)).hover(timeout=5000)
                page.wait_for_timeout(300)
                faint_texts(page, where, faint, texts_on)
            except Exception as exc:
                faint.append("{}: not measured, {}".format(where, type(exc).__name__))
        page.hover(COMPOSER)

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

        # Gemini makes a video when asked for one (2026-10-06); the mock answers this phrase with a
        # one second clip. It plays where it was made, and can be saved.
        try:
            page.fill(COMPOSER, "make a short video of a cat asleep in the sun")
            page.click("button:has-text('Send')")
            page.wait_for_selector("text=mock video for", timeout=60000)
            page.wait_for_timeout(1500)
            in_chat = page.evaluate(PLAYABLE)
            shot(page, "07h-video")
            record("a video plays in the chat, and can be saved", playable(in_chat), repr(in_chat))
        except Exception as exc:
            record("a video plays in the chat, and can be saved", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))

        page.click("nav button:has-text('gallery')")
        page.wait_for_selector("text=/Gallery \\(\\d+\\)/", timeout=20000)
        page.wait_for_timeout(1500)
        faint_texts(page, "the gallery with items", faint, texts_on)
        shot(page, "08-gallery")
        heading = page.locator("text=/Gallery \\(\\d+\\)/").first.inner_text()
        gallery_images = page.evaluate(
            "() => Array.from(document.images).filter(i => i.naturalWidth > 0).length"
        )
        record("gallery lists the generated media", gallery_images >= 1,
               "{}, {} thumbnail(s)".format(heading, gallery_images))
        in_gallery = page.evaluate(PLAYABLE)
        record("the gallery plays a video, and it can be saved", playable(in_gallery), repr(in_gallery))

        # The full gate's intermittent console error (2026-10-06 and 07), named by its step: a gallery
        # opened and left at once. A video player given its file and taken off the page in the same
        # moment logged net::ERR_FILE_NOT_FOUND for its revoked blob (reproduced 3 of 3). Here the
        # chat is opened the moment the gallery's player shows, inside that same moment.
        leave_check = "a video left the moment it shows lets go of its file without an error"
        try:
            page.click("nav button:has-text('chat')")
            page.wait_for_selector("[data-testid=message-scroll]", timeout=10000)
            start = len(errors)
            page.evaluate("""() => {
                window.__leftVideo = false;
                const chat = [...document.querySelectorAll('nav button')].find((b) => b.textContent.trim() === 'chat');
                const seen = new MutationObserver(() => {
                    if (!window.__leftVideo && document.querySelector('[data-testid=media-video]')) {
                        window.__leftVideo = true;
                        seen.disconnect();
                        chat.click();
                    }
                });
                seen.observe(document.body, {childList: true, subtree: true});
            }""")
            page.click("nav button:has-text('gallery')")
            page.wait_for_function("() => window.__leftVideo === true", timeout=20000)
            page.wait_for_timeout(1500)
            left = [e for e in errors[start:] if "ERR_FILE_NOT_FOUND" in e]
            record(leave_check, not left, "console errors after leaving: {}".format(left))
        except Exception as exc:
            record(leave_check, False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))

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

        # A search with no hit says so too, in both languages, and the note leaves with the search.
        nothing = {}
        try:
            page.fill("[data-testid=conversation-search]", "zzz-nothing-here")
            page.wait_for_timeout(1000)
            nothing["en"] = page.locator("aside").get_by_text("No conversation matches.", exact=True).is_visible()
            nothing["announced"] = page.locator("aside [role=status]").get_by_text("No conversation matches.",
                                                                                   exact=True).is_visible()
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Gửi')", timeout=5000)
            nothing["vi"] = page.locator("aside").get_by_text("Không tìm thấy cuộc trò chuyện nào.",
                                                              exact=True).is_visible()
            page.click("[data-testid=language-switch]", timeout=5000)
            page.wait_for_selector("button:has-text('Send')", timeout=5000)
            shot(page, "08f-no-hit")
            page.fill("[data-testid=conversation-search]", "")
            page.wait_for_timeout(1000)
            nothing["rows back"] = page.locator("[data-testid=conversation-item]").count()
            nothing["notes left"] = (page.locator("aside").get_by_text("No conversation matches.").count()
                                     + page.locator("aside").get_by_text("No conversations yet.").count())
            record("an empty list and a search with no hit say so, in both languages, to a screen reader too,"
                   " and never beside a conversation",
                   bool(empty.get("after")) and bool(empty.get("vi")) and nothing["en"] and nothing["vi"]
                   and nothing["announced"] and nothing["rows back"] >= 1 and nothing["notes left"] == 0
                   and first_turn.get("empty before the send") is True
                   and first_turn.get("reply pending") and first_turn.get("rows", 0) >= 1
                   and first_turn.get("notes") == 0 and first_turn.get("status regions") == 1,
                   "empty list: en {}, vi {}; during the first reply {}; no hit {}".format(
                       empty.get("after"), empty.get("vi"), first_turn, nothing))
        except Exception as exc:
            record("an empty list and a search with no hit say so, in both languages, to a screen reader too,"
                   " and never beside a conversation", False,
                   "{}: {} (so far {})".format(type(exc).__name__, str(exc)[:160], nothing))

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
            provoked.update(i for i in range(start, len(errors)) if "503" in errors[i].split(" @ ")[0])
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
        small.on("console", heard(errors))
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
            provoked.update(i for i in range(start, len(errors)) if "500" in errors[i].split(" @ ")[0])
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
            faint_texts(small, "a phone's open list", faint, texts_on)

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

        # The open list is a step in the tab's history: Back closes it and the app stays, and closing
        # it any other way takes the step back out, so Back then leaves as it did before the list
        # opened. The page before the app stands for wherever the person came from.
        def fresh_tab():
            small.goto("about:blank#before")
            small.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
            small.wait_for_selector("[data-testid=conversation-item]", state="attached", timeout=20000)
            small.wait_for_timeout(500)

        try:
            fresh_tab()
            small.evaluate("() => { window.__stayed = true }")
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.wait_for_timeout(300)
            small.go_back(timeout=10000)
            small.wait_for_timeout(800)
            stayed = small.evaluate("() => window.__stayed === true")
            still_open = stayed and search.is_visible()
            record("on a phone Back closes the open list and stays in the app",
                   stayed and not still_open and small.url.startswith(WEB_URL),
                   "after Back: at {!r}, the same page {}, the list open {}".format(small.url, stayed, still_open))
        except Exception as exc:
            record("on a phone Back closes the open list and stays in the app", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        landed = {}
        try:
            for how in ("Close", "a row", "chat", "New chat", "Escape", "the gallery", "a wider window"):
                fresh_tab()
                small.click("[data-testid=open-conversations]", timeout=5000)
                small.wait_for_timeout(300)
                if how == "Close":
                    small.click("[data-testid=close-conversations]", timeout=5000)
                elif how == "a row":
                    small.locator("[data-testid=conversation-item] button").first.click(timeout=5000)
                elif how == "chat":
                    small.click("nav button:has-text('chat')", timeout=5000)
                elif how == "New chat":
                    small.click("aside button:has-text('New chat')", timeout=5000)
                elif how == "Escape":
                    small.keyboard.press("Escape")
                elif how == "the gallery":
                    small.click("nav button:has-text('gallery')", timeout=5000)
                else:
                    small.set_viewport_size({"width": 1024, "height": 800})
                    small.wait_for_timeout(500)
                    small.set_viewport_size({"width": 390, "height": 844})
                small.wait_for_timeout(800)
                small.go_back(timeout=10000)
                small.wait_for_timeout(800)
                landed[how] = small.url
            record("on a phone every way of closing the list leaves no step for Back",
                   len(landed) == 7 and all(url == "about:blank#before" for url in landed.values()),
                   "Back after each close lands on {}".format(landed))
        except Exception as exc:
            record("on a phone every way of closing the list leaves no step for Back", False,
                   "{}: {} (so far {})".format(type(exc).__name__, str(exc)[:200], landed))
        try:
            fresh_tab()
            small.click("[data-testid=open-conversations]", timeout=5000)
            small.wait_for_timeout(300)
            small.click("nav button:has-text('chat')", timeout=5000)
            small.wait_for_timeout(500)
            still_open = search.is_visible()
            shot(small, "15b-phone-chat-tapped")
            record("on a phone chat in the nav closes the open list", not still_open,
                   "the list open after tapping chat: {}".format(still_open))
        except Exception as exc:
            record("on a phone chat in the nav closes the open list", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            small.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
            small.wait_for_selector("[data-testid=provider-select]", timeout=20000)
            small.wait_for_timeout(800)

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

        # The view follows the tail whatever the timing. A second context at 1280x900 with this
        # person's session, where the conversation, the send, the job and a picture are answered in
        # the browser (no job is made). Measured before the fix: its own smooth scroll, slowed as on
        # a busy device, let go of the tail on the way down (384px short); a picture arriving after
        # its reply (238px short); the area getting shorter at the bottom (300px short).
        token = page.evaluate("() => localStorage.getItem('token')")

        def tail_gap(case):
            stamp = "2026-09-29 10:00:00"
            earlier = [{"id": "tail-{}".format(i), "role": "user" if i % 2 == 0 else "assistant",
                        "content": "Line {} of the earlier talk, long enough to take a couple of lines. ".format(i) * 2,
                        "created_at": stamp, "media": []} for i in range(20)]
            state = {"messages": earlier, "job": "running"}
            held = []
            json_headers = {"access-control-allow-origin": "*", "content-type": "application/json"}

            def answer(route):
                request = route.request
                path = urlparse(request.url).path
                if request.method == "OPTIONS":
                    route.continue_()
                    return
                if path == "/media/tail-picture/file":
                    held.append(route)
                    return
                if path == "/conversations":
                    body = {"items": [{"id": "tail", "provider": "chatgpt", "title": "Tail", "created_at": stamp,
                                       "updated_at": stamp}]}
                elif path == "/conversations/tail":
                    body = {"id": "tail", "provider": "chatgpt", "title": "Tail", "created_at": stamp,
                            "updated_at": stamp, "orphan_media": [], "messages": state["messages"]}
                elif path == "/providers":
                    body = {"providers": [{"name": n, "served": True} for n in ("chatgpt", "grok", "gemini")]}
                elif path == "/chat" and request.method == "POST":
                    sent = json.loads(request.post_data)["message"]
                    state["messages"] = state["messages"] + [{"id": "tail-sent", "role": "user", "content": sent,
                                                              "created_at": stamp, "media": []}]
                    body = {"job_id": "tail-job", "conversation_id": "tail"}
                elif path == "/jobs/tail-job":
                    body = {"id": "tail-job", "status": state["job"], "phase": None}
                else:
                    route.continue_()
                    return
                route.fulfill(status=200, headers=json_headers, body=json.dumps(body))

            wide = browser.new_context(viewport={"width": 1280, "height": 900})
            wide.add_init_script("localStorage.setItem('token', {!r}); localStorage.setItem('lang', 'en');".format(token))
            if case == "slow":
                wide.add_init_script(SLOW_SMOOTH)
            try:
                view = wide.new_page()
                view.on("console", heard(errors))
                for pattern in ("**/conversations", "**/conversations/tail", "**/providers", "**/chat",
                                "**/jobs/tail-job", "**/media/tail-picture/file"):
                    view.route(pattern, answer)
                view.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
                view.locator("[data-testid=conversation-item] button").first.click(timeout=20000)
                view.wait_for_selector("[data-testid=user-bubble]", timeout=10000)
                view.wait_for_timeout(5000 if case == "slow" else 1500)
                view.evaluate("() => { const el = document.querySelector('[data-testid=message-scroll]');"
                              " el.scrollTop = el.scrollHeight; }")
                view.wait_for_timeout(500)
                if case == "shorter":
                    view.set_viewport_size({"width": 1280, "height": 600})
                    view.wait_for_timeout(1500)
                else:
                    sent = "pad " * 400 if case == "slow" else "draw a blue square"
                    view.fill(COMPOSER, sent)
                    view.click("button:has-text('Send')")
                    view.wait_for_selector("[data-testid=user-bubble]:has-text('{}')".format(sent.split()[-1]),
                                           timeout=10000)
                    view.wait_for_timeout(200)
                    if case == "slow":
                        reply = {"id": "tail-reply", "role": "assistant", "content": "a reply that is long on purpose. " * 60,
                                 "created_at": stamp, "media": []}
                    else:
                        reply = {"id": "tail-reply", "role": "assistant", "content": "Here is the picture.",
                                 "created_at": stamp, "media": [{"id": "tail-picture", "type": "image",
                                                                 "filename": "square.png", "mime_type": "image/png",
                                                                 "created_at": stamp}]}
                    state["messages"] = state["messages"] + [reply]
                    state["job"] = "done"
                    view.wait_for_selector("[data-testid=reply-bubble]:has-text('{}')".format(
                        "long on purpose" if case == "slow" else "Here is the picture"), timeout=10000)
                    if case == "slow":
                        view.wait_for_timeout(6000)
                    else:
                        view.wait_for_timeout(1000)
                        picture = png(512, 512)
                        for route in held:
                            route.fulfill(status=200, headers={"access-control-allow-origin": "*",
                                                               "content-type": "image/png"}, body=picture)
                        view.wait_for_selector("[data-testid=media-thumb]", timeout=10000)
                        view.wait_for_timeout(2500)
                shot(view, "16-tail-{}".format(case))
                return view.evaluate("() => { const el = document.querySelector('[data-testid=message-scroll]');"
                                     " return Math.round(el.scrollHeight - el.scrollTop - el.clientHeight); }")
            finally:
                wide.close()

        for case, name in (("slow", "the view keeps following when its own smooth scroll is slow"),
                           ("picture", "the view follows a picture that arrives after its reply"),
                           ("shorter", "the view stays at the bottom when the chat area gets shorter")):
            try:
                gap = tail_gap(case)
                record(name, gap < 80, "{}px from the bottom".format(gap))
            except Exception as exc:
                record(name, False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))

        # The typing bubble's hint shows only after a minute: a job answered in the browser (none is
        # made) and a fake clock moved on by 61s bring it on screen for the contrast check.
        def hint_after_a_minute():
            stamp = "2026-09-30 10:00:00"
            json_headers = {"access-control-allow-origin": "*", "content-type": "application/json"}

            def answer(route):
                request = route.request
                path = urlparse(request.url).path
                if request.method == "OPTIONS":
                    route.continue_()
                    return
                if path == "/conversations":
                    body = {"items": [{"id": "hint", "provider": "chatgpt", "title": "Hint", "created_at": stamp,
                                       "updated_at": stamp}]}
                elif path == "/conversations/hint":
                    body = {"id": "hint", "provider": "chatgpt", "title": "Hint", "created_at": stamp,
                            "updated_at": stamp, "orphan_media": [],
                            "messages": [{"id": "hint-1", "role": "user", "content": "draw a slow picture",
                                          "created_at": stamp, "media": []}]}
                elif path == "/chat" and request.method == "POST":
                    body = {"job_id": "hint-job", "conversation_id": "hint"}
                elif path == "/jobs/hint-job":
                    body = {"id": "hint-job", "status": "running", "phase": None}
                else:
                    route.continue_()
                    return
                route.fulfill(status=200, headers=json_headers, body=json.dumps(body))

            slow = browser.new_context(viewport={"width": 1280, "height": 900})
            slow.add_init_script("localStorage.setItem('token', {!r}); localStorage.setItem('lang', 'en');".format(token))
            try:
                view = slow.new_page()
                view.on("console", heard(errors))
                view.clock.install()
                for pattern in ("**/conversations", "**/conversations/hint", "**/chat", "**/jobs/hint-job"):
                    view.route(pattern, answer)
                view.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
                view.locator("[data-testid=conversation-item] button").first.click(timeout=20000)
                view.wait_for_selector("[data-testid=user-bubble]", timeout=10000)
                view.fill(COMPOSER, "still drawing")
                view.click("button:has-text('Send')")
                view.wait_for_selector("[data-testid=typing-bubble]", timeout=10000)
                view.clock.fast_forward(61000)
                view.wait_for_selector("[data-testid=typing-bubble] >> text=Still working.", timeout=5000)
                faint_texts(view, "the typing bubble after a minute", faint, texts_on)
                shot(view, "05b-typing-after-a-minute")
            finally:
                slow.close()

        try:
            hint_after_a_minute()
        except Exception as exc:
            faint.append("the typing bubble after a minute: not measured, {}: {}".format(
                type(exc).__name__, str(exc)[:80]))

        # A turn the provider's account refuses (signed out, memory on) means the provider is
        # unavailable until its admin acts: the person is told so in their own language, like for a
        # provider nobody serves, and the admin's instruction stays in the job's record. Measured
        # 2026-10-01: "the gemini session is signed out; run scripts/login_provider.py gemini" in the
        # header. Answered in the browser: no job is made.
        admin_text = "the chatgpt session is signed out; run scripts/login_provider.py chatgpt"

        def refused_by_account(lang):
            stamp = "2026-10-01 10:00:00"
            json_headers = {"access-control-allow-origin": "*", "content-type": "application/json"}
            said = {"messages": []}

            def answer(route):
                request = route.request
                path = urlparse(request.url).path
                if request.method == "OPTIONS":
                    route.continue_()
                    return
                if path == "/providers":
                    body = {"providers": [{"name": n, "served": True} for n in ("chatgpt", "grok", "gemini")]}
                elif path == "/conversations":
                    body = {"items": [{"id": "acct", "provider": "chatgpt", "title": "Account", "created_at": stamp,
                                       "updated_at": stamp}] if said["messages"] else []}
                elif path == "/conversations/acct":
                    body = {"id": "acct", "provider": "chatgpt", "title": "Account", "created_at": stamp,
                            "updated_at": stamp, "orphan_media": [], "messages": said["messages"]}
                elif path == "/chat" and request.method == "POST":
                    said["messages"] = [{"id": "acct-1", "role": "user", "created_at": stamp, "media": [],
                                         "content": json.loads(request.post_data)["message"]}]
                    body = {"job_id": "acct-job", "conversation_id": "acct"}
                elif path == "/jobs/acct-job":
                    body = {"id": "acct-job", "status": "failed", "phase": None, "error": admin_text,
                            "error_kind": "provider_misconfigured", "provider": "chatgpt"}
                else:
                    route.continue_()
                    return
                route.fulfill(status=200, headers=json_headers, body=json.dumps(body))

            refused = browser.new_context(viewport={"width": 1280, "height": 900})
            refused.add_init_script("localStorage.setItem('token', {!r}); localStorage.setItem('lang', {!r});"
                                    .format(token, lang))
            try:
                view = refused.new_page()
                for pattern in ("**/providers", "**/conversations", "**/conversations/acct", "**/chat",
                                "**/jobs/acct-job"):
                    view.route(pattern, answer)
                view.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
                view.wait_for_selector("[data-testid=provider-select]", timeout=20000)
                view.wait_for_timeout(800)
                view.fill("form input", "a turn the account refuses")
                view.click("form button[type=submit]")
                view.wait_for_timeout(3000)
                notice = view.locator("[data-testid=provider-unserved]")
                seen = {"notice": notice.first.inner_text().strip() if notice.count() else None,
                        "header errors": [t.strip() for t in view.locator("header .text-red-600").all_inner_texts()],
                        "admin text shown": "login_provider" in view.locator("body").inner_text()}
                shot(view, "19-refused-by-account-{}".format(lang))
                return seen
            finally:
                refused.close()

        try:
            english, vietnamese = refused_by_account("en"), refused_by_account("vi")
            record("a turn its provider's account refuses shows the unavailable notice, not the admin's instruction",
                   bool(english["notice"]) and "chatgpt" in english["notice"] and "unavailable" in english["notice"]
                   and bool(vietnamese["notice"]) and "tạm ngưng" in vietnamese["notice"]
                   and not english["header errors"] and not vietnamese["header errors"]
                   and not english["admin text shown"] and not vietnamese["admin text shown"],
                   "en {}; vi {}".format(english, vietnamese))
        except Exception as exc:
            record("a turn its provider's account refuses shows the unavailable notice, not the admin's instruction",
                   False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))

        # How a reply and a file look, answered in the browser. The bubble's pre-wrap turned the
        # breaks between a reply's blocks into blank lines (three bullets 166px), and they were the
        # only gap between paragraphs; a fixed 256px file card ran out of a 147px gallery tile.
        stamp = "2026-09-29 10:00:00"
        replies = {"list": "Three places:\n\n1. A lake walk\n2. A cooking class\n3. An escape room\n\nEnjoy the day!",
                   "paragraphs": "First line\nsecond line of the same paragraph\n\nA new paragraph after a blank line.",
                   "bullets": "- one\n- two\n- three"}
        archive = {"id": "look-zip", "type": "file", "filename": "report-with-a-long-name.zip", "provider": "chatgpt",
                   "prompt": "zip the pictures", "created_at": stamp,
                   "metadata": {"name": "report-with-a-long-name.zip", "size": 20480}}
        looked = []
        for key, text in replies.items():
            looked += [{"id": "look-q-" + key, "role": "user", "content": "show " + key, "created_at": stamp, "media": []},
                       {"id": "look-r-" + key, "role": "assistant", "content": text, "created_at": stamp, "media": []}]
        looked.append({"id": "look-r-file", "role": "assistant", "content": "Here is the archive.", "created_at": stamp,
                       "media": [archive]})
        shelf = [{"id": "look-pic", "type": "image", "filename": "square.png", "provider": "chatgpt",
                  "prompt": "a blue square", "created_at": stamp}, archive,
                 {"id": "look-doc", "type": "file", "filename": "notes.docx", "provider": "gemini", "prompt": "write notes",
                  "created_at": stamp, "metadata": {"name": "notes.docx", "size": 4096}}]
        square = png(256, 256)

        def answer_look(route):
            request = route.request
            path = urlparse(request.url).path
            if request.method == "OPTIONS":
                route.continue_()
                return
            if path == "/media/look-pic/file":
                route.fulfill(status=200, headers={"access-control-allow-origin": "*", "content-type": "image/png"},
                              body=square)
                return
            if path == "/conversations":
                body = {"items": [{"id": "look", "provider": "chatgpt", "title": "Look", "created_at": stamp,
                                   "updated_at": stamp}]}
            elif path == "/conversations/look":
                body = {"id": "look", "provider": "chatgpt", "title": "Look", "created_at": stamp,
                        "updated_at": stamp, "orphan_media": [], "messages": looked}
            elif path == "/media":
                body = {"items": shelf, "total": len(shelf)}
            else:
                route.continue_()
                return
            route.fulfill(status=200, headers={"access-control-allow-origin": "*", "content-type": "application/json"},
                          body=json.dumps(body))

        def look(width, lang):
            context = browser.new_context(viewport={"width": width, "height": 900})
            context.add_init_script("localStorage.setItem('token', {!r}); localStorage.setItem('lang', {!r});"
                                    .format(token, lang))
            view = context.new_page()
            view.on("console", heard(errors))
            for pattern in ("**/conversations", "**/conversations/look", "**/media", "**/media/look-pic/file"):
                view.route(pattern, answer_look)
            view.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
            view.wait_for_selector("[data-testid=provider-select]", timeout=20000)
            return context, view

        try:
            context, view = look(1280, "en")
            try:
                view.wait_for_selector("[data-testid=conversation-item]", timeout=20000)
                faint_texts(view, "a new chat with a row", faint, texts_on)
                view.locator("[data-testid=conversation-item] button").first.click(timeout=20000)
                view.wait_for_selector("[data-testid=reply-bubble]", timeout=10000)
                view.wait_for_timeout(800)
                faint_texts(view, "replies with blocks and a file card", faint, texts_on)
                blocks = view.evaluate(
                    """() => {
                        const bubbles = [...document.querySelectorAll('[data-testid=reply-bubble]')];
                        const find = (start) => bubbles.find((b) => b.textContent.trim().startsWith(start));
                        const height = (n) => Math.round(n.getBoundingClientRect().height);
                        const paragraphs = [...find('First line').querySelectorAll('p')].map((p) => p.getBoundingClientRect());
                        return {list: height(find('Three places')), bullets: height(find('one')),
                                firstParagraph: Math.round(paragraphs[0].height),
                                gap: paragraphs.length > 1 ? Math.round(paragraphs[1].top - paragraphs[0].bottom) : null};
                    }"""
                )
                shot(view, "17-reply-blocks")
            finally:
                context.close()
            record("a reply shows its blocks without blank lines, its paragraphs still apart",
                   blocks["list"] <= 150 and blocks["bullets"] <= 90 and blocks["firstParagraph"] >= 38
                   and blocks["gap"] is not None and 4 <= blocks["gap"] <= 16, repr(blocks))
        except Exception as exc:
            record("a reply shows its blocks without blank lines, its paragraphs still apart", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))

        try:
            inside = {}
            for width, lang, gallery in ((390, "en", "gallery"), (320, "vi", "thư viện")):
                context, view = look(width, lang)
                try:
                    view.click("nav button:has-text('{}')".format(gallery), timeout=10000)
                    view.wait_for_selector("[data-testid=file-card]", timeout=10000)
                    view.wait_for_timeout(600)
                    faint_texts(view, "the gallery at {}px in {}".format(width, lang), faint, texts_on)
                    inside[(width, lang)] = view.evaluate(
                        """() => [...document.querySelectorAll('[data-testid=file-card]')].map((card) => {
                            const tile = card.parentElement.getBoundingClientRect(), c = card.getBoundingClientRect();
                            return c.left >= tile.left - 0.5 && c.right <= tile.right + 0.5;
                        })"""
                    )
                    shot(view, "18-gallery-files-{}".format(width))
                finally:
                    context.close()
            context, view = look(1280, "en")
            try:
                view.locator("[data-testid=conversation-item] button").first.click(timeout=20000)
                view.wait_for_selector("[data-testid=file-card]", timeout=10000)
                chat_card = view.evaluate(
                    "() => Math.round(document.querySelector('[data-testid=file-card]').getBoundingClientRect().width)")
            finally:
                context.close()
            record("a file card stays inside its gallery tile on a phone and keeps its size in the chat",
                   all(v and all(v) for v in inside.values()) and chat_card == 256,
                   "inside their tiles {}, the chat's card {}px".format(inside, chat_card))
        except Exception as exc:
            record("a file card stays inside its gallery tile on a phone and keeps its size in the chat", False,
                   "{}: {}".format(type(exc).__name__, str(exc)[:200]))

        # The design review of 2026-10-06: in a gallery tile on a phone the player was 145px wide at
        # 390 and 110px at 320, where Chrome keeps only its menu button; a video that could not load
        # said "could not load image", in English whatever the language. The gallery is answered with
        # the video the mock made above (its file from the api) and one whose file is gone.
        videos_check = "on a phone a video in the gallery is wide enough to play, and one that cannot load says so"
        try:
            listed = urllib.request.Request(API_URL + "/media", headers={"Authorization": "Bearer " + token})
            with urllib.request.urlopen(listed, timeout=20) as resp:
                clip_id = next((m["id"] for m in json.load(resp)["items"] if m["type"] == "video"), None)
            videos = [{"id": clip_id, "type": "video", "filename": "cat.mp4", "provider": "gemini",
                       "prompt": "a cat asleep in the sun", "created_at": stamp},
                      {"id": "look-vid-gone", "type": "video", "filename": "gone.mp4", "provider": "gemini",
                       "prompt": "a video whose file is gone", "created_at": stamp}]
            plain = {"access-control-allow-origin": "*", "content-type": "application/json"}

            def answer_videos(route):
                path = urlparse(route.request.url).path
                if route.request.method == "OPTIONS":
                    route.continue_()
                elif path == "/media":
                    route.fulfill(status=200, headers=plain,
                                  body=json.dumps({"items": shelf + videos, "total": len(shelf) + len(videos)}))
                elif path == "/media/look-vid-gone/file":
                    route.fulfill(status=404, headers=plain, body=json.dumps({"detail": "file missing on disk"}))
                else:
                    route.continue_()

            sizes = {}
            for width, lang, gallery in ((390, "en", "gallery"), (320, "vi", "thư viện")):
                context, view = look(width, lang)
                start = len(errors)
                try:
                    view.route("**/media", answer_videos)
                    view.route("**/media/look-vid-gone/file", answer_videos)
                    view.click("nav button:has-text('{}')".format(gallery), timeout=10000)
                    view.wait_for_selector("[data-testid=media-video]", timeout=15000)
                    view.wait_for_selector("[data-testid=video-failed]", timeout=15000)
                    view.wait_for_timeout(600)
                    faint_texts(view, "the gallery with videos at {}px in {}".format(width, lang), faint, texts_on)
                    sizes[(width, lang)] = view.evaluate(
                        """() => {
                            const v = document.querySelector('[data-testid=media-video]').getBoundingClientRect();
                            const f = document.querySelector('[data-testid=video-failed]');
                            const b = f.getBoundingClientRect();
                            return {video: Math.round(v.width), screen: window.innerWidth, failed: f.textContent.trim(),
                                    shape: Math.round(b.width / b.height * 100) / 100,
                                    page: document.scrollingElement.scrollWidth};
                        }"""
                    )
                    shot(view, "18b-gallery-videos-{}".format(width))
                finally:
                    # The gone file's 404 is this check's own doing.
                    provoked.update(i for i in range(start, len(errors)) if "404" in errors[i].split(" @ ")[0])
                    context.close()
            said = {"en": "Could not load this video.", "vi": "Không tải được video."}
            record(videos_check,
                   len(sizes) == 2 and all(s["video"] >= 0.7 * s["screen"] and s["failed"] == said[lang]
                                           and 1.7 <= s["shape"] <= 1.85 and s["page"] <= s["screen"]
                                           for (width, lang), s in sizes.items()), repr(sizes))
        except Exception as exc:
            record(videos_check, False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))

        # The API page (2026-10-09): a key is made, shown once, listed by its prefix only, works on /v1,
        # survives a revoke that is dismissed, and stops working once a revoke is confirmed.
        def on_v1(key):
            asked = urllib.request.Request(API_URL + "/v1/images/not-a-request",
                                           headers={"Authorization": "Bearer " + key})
            try:
                with urllib.request.urlopen(asked, timeout=20) as resp:
                    return resp.status
            except urllib.error.HTTPError as exc:
                return exc.code

        api_page_check = "the API page makes a key, shows it once, lists it by its prefix, and revokes it on confirm"
        phone_key_check = "on a phone the API page fits, the new key wrapped inside it"
        try:
            page.click("nav button:has-text('API')", timeout=5000)
            page.wait_for_selector("[data-testid=key-name]", timeout=10000)
            faint_texts(page, "the API page, no key yet", faint, texts_on)
            page.fill("[data-testid=key-name]", "smoke key")
            page.click("[data-testid=key-create]")
            page.wait_for_selector("[data-testid=new-key]", timeout=10000)
            key = page.locator("[data-testid=new-key]").inner_text().strip()
            row = page.locator("[data-testid=key-row]", has_text="smoke key")
            row_text = row.inner_text() if row.count() == 1 else ""
            shot(page, "17-api-key-made")
            faint_texts(page, "the API page, a key just made", faint, texts_on)
            works = on_v1(key) if key.startswith("aip_") else None

            pocket = browser.new_context(viewport={"width": 390, "height": 844})
            pocket.add_init_script("localStorage.setItem('token', {!r}); localStorage.setItem('lang', 'en');".format(token))
            try:
                handset = pocket.new_page()
                handset.on("console", heard(errors))
                handset.goto(WEB_URL, wait_until="domcontentloaded", timeout=30000)
                handset.click("nav button:has-text('API')", timeout=20000)
                handset.wait_for_selector("[data-testid=key-name]", timeout=10000)
                handset.fill("[data-testid=key-name]", "phone key")
                handset.click("[data-testid=key-create]")
                handset.wait_for_selector("[data-testid=new-key]", timeout=10000)
                fit = handset.evaluate("""() => {
                    const shown = document.querySelector('[data-testid=new-key]').getBoundingClientRect();
                    return {screen: window.innerWidth, page: document.scrollingElement.scrollWidth,
                            left: Math.round(shown.left), right: Math.round(shown.right)};
                }""")
                shot(handset, "17b-api-key-phone")
            finally:
                pocket.close()
            record(phone_key_check, fit["page"] <= fit["screen"] and fit["left"] >= 0 and fit["right"] <= fit["screen"],
                   "{}".format(fit))

            page.click("nav button:has-text('chat')")
            page.click("nav button:has-text('API')")
            page.wait_for_selector("[data-testid=key-row]", timeout=10000)
            shown_later = key in page.locator("main").inner_text()
            page.once("dialog", lambda d: d.dismiss())
            page.locator("[data-testid=key-row]", has_text="smoke key").locator("[data-testid=key-revoke]").click()
            page.wait_for_timeout(800)
            kept = page.locator("[data-testid=key-row]", has_text="smoke key").count() == 1 and on_v1(key) == 404
            page.once("dialog", lambda d: d.accept())
            page.locator("[data-testid=key-row]", has_text="smoke key").locator("[data-testid=key-revoke]").click()
            page.wait_for_selector("[data-testid=key-row]:has-text('smoke key')", state="detached", timeout=10000)
            after = on_v1(key)
            record(api_page_check,
                   key.startswith("aip_") and len(key) >= 40 and key[:12] in row_text and key not in row_text
                   and works == 404 and not shown_later and kept and after == 401,
                   "key {}..., row {!r}, on /v1 {}, shown again {}, kept on dismiss {}, after revoke {}".format(
                       key[:6], row_text[:60], works, shown_later, kept, after))
        except Exception as exc:
            shot(page, "17-api-failure")
            for check in (api_page_check, phone_key_check):
                if not any(name == check for name, _, _ in steps):
                    record(check, False, "{}: {}".format(type(exc).__name__, str(exc)[:200]))
        finally:
            # The steps after this one work in the chat.
            page.click("nav button:has-text('chat')", timeout=5000)
            page.wait_for_selector("[data-testid=provider-select]", timeout=10000)

        # Each faint text once, with the number of screens it was seen on.
        kinds = {}
        for entry in faint:
            what = entry.split(": ", 1)[-1]
            kinds[what] = kinds.get(what, 0) + 1
        record("every text and placeholder on screen meets its contrast floor",
               not faint and len(texts_on) >= 15 and all(texts_on.values()),
               "{} texts on {} screens {}, {} under the floor: {}".format(
                   sum(texts_on.values()), len(texts_on),
                   sorted(k for k, v in texts_on.items() if not v) or "all measured", len(faint), kinds))

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
