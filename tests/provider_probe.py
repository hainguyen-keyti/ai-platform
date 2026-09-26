#!/usr/bin/env python3
"""Measure the ChatGPT behaviours the worker depends on, against the real site.

    ~/cloakbrowser-env/bin/python tests/provider_probe.py [all|send|dom-settle|memory|banner|cleanup]
    ~/cloakbrowser-env/bin/python tests/provider_probe.py send,cleanup    # comma-separated; always run in PROBES order
    ~/cloakbrowser-env/bin/python tests/provider_probe.py memory-toggle   # by name only

Each probe prints what it saw; nothing here asserts a wish. The output is copied
into docs/research as the record of what the site did that day. It drives the
worker's own provider class against the saved session in storage/sessions, so
the code paths measured are the ones in production. It creates one thread of its
own and deletes only that one. Stop the host worker first: memory-toggle must
never overlap a real turn, and the browser may refuse a second session.
"""

import json
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.chatgpt import (  # noqa: E402
    ASSISTANT_TURN, MEMORY_KEYS, SESSION_TOKEN, STOP_BUTTON, ChatGPTProvider,
)

PROMPT = "Reply with the single word: ok"
LONG_PROMPT = "Write three short sentences about the sea. Plain text, no list."

# Places an account-level memory setting might be readable without spending a turn.
CANDIDATE_ENDPOINTS = (
    "/backend-api/settings/user",
    "/backend-api/settings/account_user_setting",
    "/backend-api/settings/beta_features",
    "/backend-api/memories?gizmo_id=",
    "/backend-api/user_system_messages",
    "/backend-api/me",
    "/backend-api/accounts/check/v4-2023-04-27",
)

FETCH_JSON = """
async ([url, token, method, body]) => {
    const opts = {method: method || "GET", credentials: "include",
                  headers: {Authorization: "Bearer " + token}};
    if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = body; }
    const r = await fetch(url, opts);
    let j = null;
    try { j = await r.json(); } catch (e) { j = null; }
    return {status: r.status, json: j};
}
"""

LAST_TURN_HTML = """
() => {
    const turns = document.querySelectorAll('article, [data-testid^="conversation-turn"]');
    const last = turns[turns.length - 1];
    return last ? last.outerHTML : null;
}
"""

ELEMENT_KEYS = """
() => Array.from(document.querySelectorAll('main *')).map((el) =>
    el.tagName + '|' + (el.getAttribute('class') || '') + '|' +
    (el.getAttribute('data-testid') || '') + '|' + (el.getAttribute('role') || ''))
"""

NEW_ELEMENTS = """
(beforeKeys) => {
    const seen = new Set(beforeKeys);
    const out = [];
    for (const el of document.querySelectorAll('main *')) {
        const key = el.tagName + '|' + (el.getAttribute('class') || '') + '|' +
            (el.getAttribute('data-testid') || '') + '|' + (el.getAttribute('role') || '');
        if (seen.has(key)) continue;
        const cls = el.getAttribute('class') || '';
        const testid = el.getAttribute('data-testid') || '';
        const interesting = el.getAttribute('role') === 'alert' || el.tagName === 'BUTTON'
            || /error|danger|retry|regenerat/i.test(cls) || /error|retry/i.test(testid);
        if (!interesting) continue;
        const text = (el.textContent || '').trim();
        out.push({tag: el.tagName, role: el.getAttribute('role'), testid: testid || null,
                  cls: cls.slice(0, 140), text: text.slice(0, 80), textLen: text.length});
    }
    return out;
}
"""

ERRORISH_HTML = """
() => Array.from(document.querySelectorAll(
        'main [role=alert], main [class*=error], main [class*=text-token-text-error]'))
    .map((el) => el.outerHTML)
"""

SWITCHES = """
() => Array.from(document.querySelectorAll('[role=switch]')).map((el, i) => {
    const by = el.getAttribute('aria-labelledby');
    const ref = by ? document.getElementById(by) : null;
    return {index: i, checked: el.getAttribute('aria-checked'),
            label: ref ? ref.textContent.trim().slice(0, 60) : (el.getAttribute('aria-label') || '')};
})
"""

DIALOGS = """
() => Array.from(document.querySelectorAll('[role=dialog], [role=alertdialog]')).map((d) => ({
    role: d.getAttribute('role'),
    heading: ((d.querySelector('h1,h2,h3') || {}).textContent || '').trim().slice(0, 60)}))
"""

SETTINGS_ENDPOINTS = (
    "/backend-api/settings/user",
    "/backend-api/memories?include_memory_entries=false",
    "/backend-api/accounts/check/v4-2023-04-27",
)

crashed = []


def say(name, detail):
    print("[{}] {}".format(name, detail), flush=True)


def walk(value, prefix=""):
    if isinstance(value, dict):
        for k, v in value.items():
            path = "{}.{}".format(prefix, k) if prefix else str(k)
            yield path, v
            yield from walk(v, path)
    elif isinstance(value, list):
        for i, v in enumerate(value[:5]):
            yield from walk(v, "{}[{}]".format(prefix, i))


def sanitize(html):
    # Fixtures are committed: no scripts, no image urls, and the audit below
    # counts anything that looks like an address so it can be looked at first.
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    html = re.sub(r'\s(src|srcset|href)="[^"]*"', ' \\1=""', html)
    return html


def save_fixture(name, html):
    FIXTURES.mkdir(parents=True, exist_ok=True)
    clean = sanitize(html)
    emails = len(re.findall(r"[\w.+-]+@[\w-]+\.[\w.]+", clean))
    (FIXTURES / name).write_text("<main>\n{}\n</main>\n".format(clean))
    say("fixture", "{} written, {} chars, {} address-like strings".format(name, len(clean), emails))


class Probe:
    def __init__(self):
        self.media = Path(tempfile.mkdtemp(prefix="probe-media-"))
        self.provider = ChatGPTProvider(self.media, ROOT / "storage" / "sessions")
        self.provider.start()
        self.thread_id = None
        self.send_endpoint = None

    def page(self):
        return self.provider._ensure_page()

    def token(self, page):
        if not self.provider._access_token:
            self.provider._access_token = page.evaluate(SESSION_TOKEN)
        return self.provider._access_token

    def thread_url(self):
        return "https://chatgpt.com/c/{}".format(self.thread_id) if self.thread_id else None

    def close(self):
        try:
            self.provider.stop()
        finally:
            shutil.rmtree(self.media, ignore_errors=True)


def probe_send(p):
    page = p.page()
    requests = []

    def on_request(req):
        if req.method in ("POST", "PATCH", "PUT") and "backend-a" in req.url:
            requests.append((req.method, req.url.split("chatgpt.com", 1)[-1].split("?")[0]))

    page.on("request", on_request)
    started = time.time()
    result = p.provider._run(PROMPT)
    page.remove_listener("request", on_request)
    p.thread_id = p.provider._thread_id(page)
    say("send: result", "success={} settle={} memory={} {:.0f}s text={!r} thread={}".format(
        result.success, p.provider.last_settle, p.provider.memory, time.time() - started,
        (result.text or "")[:40], (p.thread_id or "none")[:8]))
    seen = []
    for entry in requests:
        if entry not in seen:
            seen.append(entry)
    for method, path in seen:
        say("send: request", "{} {}".format(method, path))
    # The streaming request itself ends in /conversation; init and prepare
    # calls go before it (measured: init, f/conversation/prepare, f/conversation).
    turn_posts = sorted((path for method, path in seen if method == "POST" and "conversation" in path),
                        key=lambda path: (not path.endswith("/conversation"), path))
    p.send_endpoint = turn_posts[0] if turn_posts else None
    say("send: the turn's own request", p.send_endpoint or "none matched POST *conversation*")
    html = page.evaluate(LAST_TURN_HTML)
    if html:
        save_fixture("chatgpt_reply.html", html)
    else:
        say("fixture", "chatgpt_reply.html not written: no article or conversation-turn element")
    # The whole healthy page as well, composer included, so a detector that
    # fires on something ordinary outside the turn is caught by the fixtures.
    main_html = page.evaluate("() => (document.querySelector('main') || {}).outerHTML || ''")
    if main_html:
        save_fixture("chatgpt_main_reply.html", main_html)


def probe_dom_settle(p):
    page = p.page()
    pattern = re.compile(r"/backend-api/conversation/[0-9a-fA-F-]{20,}$")
    blocked = {"n": 0}

    def withhold(route):
        if route.request.method == "GET":
            blocked["n"] += 1
            route.fulfill(status=500, content_type="application/json",
                          body='{"detail": "probe: server view withheld"}')
        else:
            route.continue_()

    page.route(pattern, withhold)
    started = time.time()
    try:
        result = p.provider._run("Reply with exactly these words: dom fallback check",
                                 thread_url=p.thread_url())
    finally:
        page.unroute(pattern, withhold)
    say("dom-settle: forced fallback", "settle={} reads_withheld={} success={} {:.0f}s text={!r}".format(
        p.provider.last_settle, blocked["n"], result.success, time.time() - started,
        (result.text or "")[:60]))
    p.thread_id = p.provider._thread_id(page) or p.thread_id

    data = p.provider._thread_nodes(page, p.thread_id) if p.thread_id else None
    if data and data.get("status") == 200:
        answers = sorted((n for n in data["nodes"]
                          if n["role"] == "assistant" and n["content_type"] == "text"),
                         key=lambda n: n["create_time"])
        server_text = (answers[-1]["text"] if answers else "").strip()
        same = " ".join(server_text.split()) == " ".join((result.text or "").split())
        say("dom-settle: dom vs server", "identical={} dom={!r} server={!r}".format(
            same, (result.text or "")[:60], server_text[:60]))
    else:
        say("dom-settle: dom vs server", "server view unavailable, status {}".format(
            data.get("status") if data else None))

    # A normal turn watched at 4Hz: how long after the stop button leaves does
    # the text still change? That number is what SETTLE_SECONDS must cover.
    baseline = page.locator(ASSISTANT_TURN).count()
    p.provider._send(page, LONG_PROMPT)
    t0 = time.time()
    stop_seen = stop_gone = last_change = None
    last_text = ""
    while time.time() < t0 + 180:
        page.wait_for_timeout(250)
        has_stop = page.locator(STOP_BUTTON).count() > 0
        if has_stop and stop_seen is None:
            stop_seen = time.time()
        if stop_seen is not None and not has_stop and stop_gone is None:
            stop_gone = time.time()
        text = p.provider._reply_text(page, baseline)
        if text != last_text:
            last_text, last_change = text, time.time()
        if stop_gone is not None and time.time() - stop_gone > 12:
            break
    if stop_seen is None:
        say("dom-settle: timeline", "stop button never seen; final text {} chars".format(len(last_text)))
    else:
        say("dom-settle: timeline", (
            "stop button seen at +{:.1f}s, gone at +{:.1f}s, last text change at +{:.1f}s, "
            "so {:.1f}s after the button left; final {} chars").format(
                stop_seen - t0, (stop_gone or time.time()) - t0, (last_change or t0) - t0,
                (last_change or t0) - (stop_gone or time.time()), len(last_text)))


def probe_memory(p):
    page = p.page()
    token = p.token(page)
    if not token:
        say("memory: token", "no session token; is the session logged in?")
        return
    for path in CANDIDATE_ENDPOINTS:
        got = page.evaluate(FETCH_JSON, [path, token, "GET", None])
        body = got.get("json")
        keys = sorted(body.keys())[:14] if isinstance(body, dict) else type(body).__name__
        # Flags only. Stored memories are user text and are counted, never printed.
        related = {k: v for k, v in walk(body) if "memor" in k.lower()
                   and not k.startswith("memories[") and isinstance(v, (bool, int, float, type(None)))}
        stored = len(body.get("memories") or []) if isinstance(body, dict) else 0
        say("memory: GET " + path.split("?")[0], "status {} keys {} flags {} stored memories {}".format(
            got["status"], keys, json.dumps(related, ensure_ascii=False)[:300], stored))
    got = page.evaluate(FETCH_JSON, ["/backend-api/settings/user", token, "GET", None])
    values = ((got.get("json") or {}).get("settings") or {}) if isinstance(got.get("json"), dict) else {}
    say("memory: settings/user switch keys", "status {} {}".format(
        got["status"], json.dumps({k: values.get(k, "<absent>") for k in MEMORY_KEYS})))
    if p.thread_id:
        got = page.evaluate(FETCH_JSON, ["/backend-api/conversation/" + p.thread_id, token, "GET", None])
        body = got.get("json") if isinstance(got.get("json"), dict) else {}
        say("memory: conversation json", "status {} memory_scope={!r} is_temporary_chat={!r}".format(
            got["status"], body.get("memory_scope"), body.get("is_temporary_chat")))

    seen = []

    def on_request(req):
        if "chatgpt.com" in req.url and re.search(r"setting|memor|personaliz", req.url, re.I):
            entry = (req.method, req.url.split("chatgpt.com", 1)[-1][:120])
            if entry not in seen:
                seen.append(entry)

    page.on("request", on_request)
    page.goto("https://chatgpt.com/#settings/Personalization", wait_until="domcontentloaded",
              timeout=60000)
    page.wait_for_timeout(6000)
    page.remove_listener("request", on_request)
    for method, path in seen:
        say("memory: settings dialog request", "{} {}".format(method, path))
    if not seen:
        say("memory: settings dialog request", "none matched setting|memor|personaliz")
    for switch in page.evaluate(SWITCHES)[:12]:
        say("memory: switch", json.dumps(switch, ensure_ascii=False))
    page.keyboard.press("Escape")


def probe_memory_toggle(p):
    """Flip "Enable memory" on and straight back off to see which request and
    which JSON field carry it. Sends no turn while it is on, and refuses to
    start unless the switch is off to begin with. Not part of `all`: it changes
    an account setting, even if only for a few seconds."""
    page = p.provider._open()
    token = p.token(page)

    def snapshot():
        out = {}
        for url in SETTINGS_ENDPOINTS:
            got = page.evaluate(FETCH_JSON, [url, token, "GET", None])
            out[url.split("?")[0]] = {k: v for k, v in walk(got.get("json"))
                                      if not isinstance(v, (dict, list))}
        return out

    def changed(a, b):
        out = {}
        for url in a:
            for key in set(a[url]) | set(b[url]):
                if a[url].get(key, "<absent>") != b[url].get(key, "<absent>"):
                    out["{} :: {}".format(url, key)] = (a[url].get(key, "<absent>"),
                                                        b[url].get(key, "<absent>"))
        return out

    def memory_switch():
        found = [s for s in page.evaluate(SWITCHES) if "memory" in s["label"].lower()]
        return found[0] if len(found) == 1 else None

    before = snapshot()
    page.goto("https://chatgpt.com/#settings/Personalization", wait_until="domcontentloaded",
              timeout=60000)
    page.wait_for_timeout(5000)
    switch = memory_switch()
    say("memory-toggle: switch before", json.dumps(switch, ensure_ascii=False))
    if not switch or switch["checked"] != "false":
        say("memory-toggle", "not flipping: the switch is missing, ambiguous, or already on")
        return
    requests = []
    page.on("request", lambda r: requests.append((r.method, r.url.split("chatgpt.com", 1)[-1][:120]))
            if r.method != "GET" and "backend-api" in r.url else None)
    dialogs_before = len(page.evaluate(DIALOGS))
    try:
        page.locator("[role=switch]").nth(switch["index"]).click(timeout=10000)
        page.wait_for_timeout(2500)
        for entry in requests:
            say("memory-toggle: request after switching on", "{} {}".format(*entry))
        if len(page.evaluate(DIALOGS)) > dialogs_before:
            say("memory-toggle", "a confirmation dialog appeared; nothing in it is clicked")
        else:
            say("memory-toggle: switch after", json.dumps(memory_switch(), ensure_ascii=False))
            page.wait_for_timeout(1500)
            say("memory-toggle: json changed while on",
                json.dumps(changed(before, snapshot()), default=str)[:800])
    finally:
        # Whatever happened above, the switch goes back to off before leaving.
        requests.clear()
        current = memory_switch()
        if current and current["checked"] == "true":
            page.locator("[role=switch]").nth(current["index"]).click(timeout=10000)
            page.wait_for_timeout(2500)
            for entry in requests:
                say("memory-toggle: request after switching off", "{} {}".format(*entry))
        final = memory_switch()
        say("memory-toggle: switch final", json.dumps(final, ensure_ascii=False))
        page.wait_for_timeout(1500)
        say("memory-toggle: json changed off vs original",
            json.dumps(changed(before, snapshot()), default=str)[:400])
        if not final or final["checked"] != "false":
            say("memory-toggle", "WARNING: the switch did not read off at the end; "
                                 "check Settings, Personalization by hand")
        page.keyboard.press("Escape")


def probe_banner(p):
    page = p.provider._open()
    before = page.evaluate(ELEMENT_KEYS)
    pattern = re.compile(r"/backend-api/.*conversation")
    hits = {"n": 0}

    def fail_send(route):
        if route.request.method == "POST":
            hits["n"] += 1
            route.fulfill(status=500, content_type="application/json",
                          body='{"detail": "probe: the model is unwell"}')
        else:
            route.continue_()

    page.route(pattern, fail_send)
    try:
        p.provider._send(page, "probe: this request is made to fail on purpose")
        page.wait_for_timeout(12000)
        say("banner: requests failed on purpose", str(hits["n"]))
        appeared = page.evaluate(NEW_ELEMENTS, before)
        for el in appeared[:25]:
            say("banner: appeared", json.dumps(el, ensure_ascii=False)[:300])
        if not appeared:
            say("banner: appeared", "nothing new matched alert, error, retry or button")
        errorish = page.evaluate(ERRORISH_HTML)
        turn = page.evaluate(LAST_TURN_HTML)
        say("banner: error-like elements", str(len(errorish)))
        snippet = "\n".join(errorish) + "\n" + (turn or "")
        if snippet.strip():
            save_fixture("chatgpt_error_banner.html", snippet)
        else:
            say("fixture", "chatgpt_error_banner.html not written: nothing error-like appeared")
        main_html = sanitize(page.evaluate("() => (document.querySelector('main') || {}).outerHTML || ''"))
        Path("/tmp/chatgpt_banner_main.html").write_text(main_html)
        say("banner: whole main saved", "/tmp/chatgpt_banner_main.html, {} chars, for inspection only".format(
            len(main_html)))
        say("banner: url after the failure", page.url[:80])
    finally:
        page.unroute(pattern, fail_send)


def probe_cleanup(p):
    if not p.thread_id:
        say("cleanup", "no probe thread of our own to delete")
        return
    page = p.page()
    token = p.token(page)
    got = page.evaluate(FETCH_JSON, ["/backend-api/conversation/" + p.thread_id, token, "PATCH",
                                     json.dumps({"is_visible": False})])
    say("cleanup: PATCH is_visible=false on the probe thread", "status {} body {}".format(
        got["status"], json.dumps(got.get("json"))[:120]))
    after = page.evaluate(FETCH_JSON, ["/backend-api/conversation/" + p.thread_id, token, "GET", None])
    body = after.get("json") if isinstance(after.get("json"), dict) else {}
    say("cleanup: GET afterwards", "status {} is_visible={!r}".format(
        after["status"], body.get("is_visible")))


# Measured 2026-09-27: #prompt-textarea is gone. These are hypotheses to count,
# and the editables dump below is what decides, not this list.
COMPOSER_CANDIDATES = (
    "#prompt-textarea",
    'div.ProseMirror[contenteditable="true"][aria-label="Ask ChatGPT"]',
    'div.ProseMirror[contenteditable="true"]',
    '[contenteditable="true"][role="textbox"]',
    "textarea",
)
USER_TURN = '[data-message-author-role="user"]'
MULTI_LINE = "Reply with the single word: ok\n\nThis second line belongs to the same turn."

EDITABLES = """
() => Array.from(document.querySelectorAll('[contenteditable="true"], textarea'))
    .map(n => ({tag: n.tagName.toLowerCase(), id: n.id || null,
                label: n.getAttribute('aria-label'), role: n.getAttribute('role'),
                cls: (n.className || '').toString().slice(0, 60),
                visible: n.getBoundingClientRect().width > 0}))
"""

MODE_TABS = """
() => Array.from(document.querySelectorAll('button, [role="tab"], [role="radio"], a'))
    .filter(n => ['Chat', 'Work'].includes((n.innerText || '').trim()))
    .map(n => ({text: n.innerText.trim(), tag: n.tagName.toLowerCase(), role: n.getAttribute('role'),
                selected: n.getAttribute('aria-selected'), pressed: n.getAttribute('aria-pressed'),
                checked: n.getAttribute('aria-checked'), state: n.getAttribute('data-state'),
                current: n.getAttribute('aria-current')}))
"""

FILE_INPUTS = """
() => Array.from(document.querySelectorAll('input[type=file]'))
    .map(n => ({id: n.id || null, accept: (n.accept || '').slice(0, 60), multiple: n.multiple}))
"""


def flat(text):
    return " ".join((text or "").split())


def probe_composer(p):
    """The new page, measured with one real turn at most.

    fill() and a multi-line insert_text are read back from the composer before
    anything is sent, because a composer that ignores fill() sends an empty turn
    and a type() that maps newlines to Enter sends several.
    """
    from src.providers.chatgpt import HOME, SEND_BUTTON, UPLOAD_INPUT

    page = p.page()
    started = time.time()
    page.goto(HOME, timeout=90000, wait_until="domcontentloaded")
    # Measured 2026-09-27 morning: the page first paints textarea#pending-home-input
    # and swaps in the ProseMirror later, so "any composer" is not "ready".
    first_seen = {}
    for _ in range(120):
        page.wait_for_timeout(500)
        for sel in COMPOSER_CANDIDATES:
            if sel not in first_seen and page.locator(sel).count():
                first_seen[sel] = round(time.time() - started, 1)
        if 'div.ProseMirror[contenteditable="true"]' in first_seen:
            break
    say("composer: first seen after load", first_seen)
    page.wait_for_timeout(1500)
    for sel in COMPOSER_CANDIDATES:
        loc = page.locator(sel)
        say("composer: candidate", "{} count {} visible {}".format(
            sel, loc.count(), loc.first.is_visible() if loc.count() else False))
    for item in page.evaluate(EDITABLES):
        say("composer: editable", item)
    say("composer: mode tabs", page.evaluate(MODE_TABS) or "none found")
    say("composer: file inputs", page.evaluate(FILE_INPUTS) or "none")
    say("composer: " + UPLOAD_INPUT, page.locator(UPLOAD_INPUT).count())
    say("composer: send button before typing", page.locator(SEND_BUTTON).count())
    say("composer: memory", p.provider._read_memory(page))

    box_sel = 'div.ProseMirror[contenteditable="true"]'
    box = page.locator(box_sel).first
    if not page.locator(box_sel).count():
        say("composer", "no ProseMirror composer; stopping before spending a turn")
        return

    def clear():
        box.click(timeout=8000)
        page.keyboard.press("ControlOrMeta+a")
        page.keyboard.press("Backspace")
        page.wait_for_timeout(300)

    try:
        box.fill("fill probe text")
        page.wait_for_timeout(500)
        say("composer: fill() read back", repr(flat(box.inner_text())))
    except Exception as exc:
        say("composer: fill() raised", "{}: {}".format(type(exc).__name__, str(exc)[:160]))
    clear()
    say("composer: after clearing", repr(flat(box.inner_text())))

    users_before = page.locator(USER_TURN).count()
    box.click(timeout=8000)
    page.keyboard.insert_text(MULTI_LINE)
    page.wait_for_timeout(500)
    say("composer: insert_text read back", repr(flat(box.inner_text())))
    say("composer: read back matches the prompt", flat(box.inner_text()) == flat(MULTI_LINE))
    say("composer: send button after typing", page.locator(SEND_BUTTON).count())
    say("composer: buttons around the composer", box.evaluate("""
        (el) => {
            const form = el.closest('form') || el.parentElement.parentElement.parentElement;
            return Array.from(form.querySelectorAll('button')).map(b => ({
                testid: b.getAttribute('data-testid'), label: b.getAttribute('aria-label'),
                id: b.id || null, type: b.getAttribute('type'), disabled: b.disabled,
                text: (b.innerText || '').trim().slice(0, 20)}));
        }"""))

    started = time.time()
    page.keyboard.press("Enter")
    emptied = None
    for _ in range(20):
        page.wait_for_timeout(500)
        if not flat(box.inner_text()):
            emptied = round(time.time() - started, 1)
            break
    say("composer: emptied after Enter", "{}s".format(emptied))
    if emptied is None:
        for sel in ('button[data-testid*="send"]', 'button[aria-label*="Send"]',
                    'button[aria-label*="send"]', 'form button[type="submit"]'):
            if page.locator(sel).count():
                say("composer: Enter did not send, clicking", sel)
                page.locator(sel).first.click(timeout=8000)
                for _ in range(20):
                    page.wait_for_timeout(500)
                    if not flat(box.inner_text()):
                        emptied = round(time.time() - started, 1)
                        break
                say("composer: emptied after the click", "{}s".format(emptied))
                break
        else:
            say("composer", "Enter did not send and no send-like button matched")

    saw_stop, settled_at, last = False, None, None
    while time.time() - started < 120:
        page.wait_for_timeout(1000)
        if page.locator(STOP_BUTTON).count():
            saw_stop = True
        answers = page.locator(ASSISTANT_TURN)
        text = answers.last.inner_text() if answers.count() else ""
        if text and text == last and not page.locator(STOP_BUTTON).count():
            settled_at = round(time.time() - started, 1)
            break
        last = text
    users_after = page.locator(USER_TURN).count()
    say("composer: user turns", "{} -> {} (one turn is +1)".format(users_before, users_after))
    bubbles = page.locator(USER_TURN)
    say("composer: the user bubble", repr(flat(bubbles.last.inner_text()) if bubbles.count() else ""))
    say("composer: stop button seen", saw_stop)
    say("composer: assistant turns", "{} last {!r} settled {}s".format(
        page.locator(ASSISTANT_TURN).count(), flat(last)[:60], settled_at))

    p.thread_id = p.provider._thread_id(page)
    say("composer: thread", p.thread_id or "none: url {}".format(page.url[:60]))
    if p.thread_id:
        data = p.provider._thread_nodes(page, p.thread_id) or {}
        nodes = data.get("nodes") or []
        say("composer: server view", "status {} nodes {}".format(data.get("status"), len(nodes)))
        for node in nodes[-3:]:
            say("composer: server node", {k: (str(v)[:60] if isinstance(v, str) else v)
                                          for k, v in node.items() if k != "text"})


TURN_MARKUP = """
() => {
    const out = {};
    for (const sel of ['[data-message-author-role]', 'article', '[data-testid^="conversation-turn"]',
                       '[data-turn]', '[data-message-id]', '[data-turn-id]', 'main [class*="markdown"]']) {
        out[sel] = document.querySelectorAll(sel).length;
    }
    const attrs = {};
    for (const n of document.querySelectorAll('main *')) {
        for (const a of n.getAttributeNames()) {
            if (a.startsWith('data-') && /turn|message|author|role/i.test(a)) {
                attrs[a] = (attrs[a] || 0) + 1;
            }
        }
    }
    out.data_attrs = attrs;
    return out;
}
"""


def probe_turn_dom(p):
    """How a finished turn is marked up now. Opens an existing thread; costs no turn."""
    import os
    thread = os.environ.get("PROBE_THREAD")
    if not thread:
        say("turn-dom", "set PROBE_THREAD to a thread id this probe made")
        return
    page = p.page()
    page.goto("https://chatgpt.com/c/" + thread, timeout=90000, wait_until="domcontentloaded")
    for _ in range(60):
        page.wait_for_timeout(500)
        if page.locator('div.ProseMirror[contenteditable="true"]').count():
            break
    page.wait_for_timeout(4000)
    say("turn-dom: url", page.url[:70])
    for key, value in page.evaluate(TURN_MARKUP).items():
        say("turn-dom: " + key, value)
    say("turn-dom: main text head", repr(flat(page.evaluate(
        "() => (document.querySelector('main') || document.body).innerText"))[:300]))


PROBES = (
    ("composer", probe_composer),
    ("turn-dom", probe_turn_dom),
    ("send", probe_send),
    ("dom-settle", probe_dom_settle),
    ("memory", probe_memory),
    ("banner", probe_banner),
    ("cleanup", probe_cleanup),
    ("memory-toggle", probe_memory_toggle),
)
# Changes an account setting for a few seconds; run it by name, on purpose.
NOT_IN_ALL = {"memory-toggle", "composer"}


def main():
    wanted = (sys.argv[1] if len(sys.argv) > 1 else "all").split(",")
    names = [n for n, _ in PROBES]
    for w in wanted:
        if w != "all" and w not in names:
            sys.exit("unknown probe {}; one of {}, comma-separated".format(w, ", ".join(["all"] + names)))
    chosen = [n for n in names if n in wanted or ("all" in wanted and n not in NOT_IN_ALL)]
    p = Probe()
    try:
        for name, fn in PROBES:
            if name not in chosen:
                continue
            say(name, "starting")
            try:
                fn(p)
            except Exception as exc:
                crashed.append(name)
                say(name, "PROBE CRASHED {}: {}".format(type(exc).__name__, str(exc)[:300]))
    finally:
        p.close()
    print("=" * 50)
    print("{} probe(s) ran, {} crashed{}".format(
        len(chosen), len(crashed), ": " + ", ".join(crashed) if crashed else ""))
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
