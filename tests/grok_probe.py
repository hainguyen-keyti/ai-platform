#!/usr/bin/env python3
"""Measure the Grok behaviours a provider would depend on, against the real site.

    ~/cloakbrowser-env/bin/python tests/grok_probe.py [open|composer|turn|image|cleanup|all]

Each probe prints what it saw; nothing here asserts a wish. The account is on a
free tier that allows very few turns per day, so `open` and `composer` cost
nothing and the others cost one turn each: run them by name, not `all`, unless
the budget is known to be there. Opens the provider's own profile, storage/sessions/grok/, as
the worker does: take grok off the host worker first, the profile opens in one
browser at a time.
"""

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.base import ProviderError  # noqa: E402
from src.providers.session import open_session  # noqa: E402

SESSIONS = ROOT / "storage" / "sessions"
HOME = "https://grok.com/"

COMPOSER = ('[data-testid="chat-input"] .ProseMirror[contenteditable="true"]',
            '.ProseMirror[contenteditable="true"]',
            'textarea[aria-label="Ask Grok anything"]',
            '[data-testid="chat-input"] textarea')
# Measured 2026-10-28 and again 2026-11-16: the textarea is a placeholder the page shows first (seen
# at 11s) and replaces with the real editor; a click on it times out once it is gone.
EDITORS = COMPOSER[:2]
EDITOR_WAIT = 60
# How long a sent turn is watched for a thread's address before the probe says there is none.
NO_THREAD_SECONDS = 75
DIAGNOSTICS = ROOT / "storage" / "diagnostics"
STOPPING = ('button[data-testid="chat-stop"]', 'button[aria-label="Stop"]',
            '[data-streaming="true"]', '[data-is-streaming="true"]')

# Every editable thing on the page, as the page has it: which one is the composer is read, not assumed.
EDITABLES = """
() => [...document.querySelectorAll('textarea, [contenteditable], input[type="text"]')].map(e => {
    const r = e.getBoundingClientRect();
    return {tag: e.tagName, ce: e.getAttribute('contenteditable'), label: e.getAttribute('aria-label'),
            placeholder: e.getAttribute('placeholder') || e.getAttribute('data-placeholder'),
            cls: (e.className || '').toString().slice(0, 50), testid: e.closest('[data-testid]')
                ? e.closest('[data-testid]').getAttribute('data-testid') : null,
            w: Math.round(r.width), h: Math.round(r.height), x: Math.round(r.x), y: Math.round(r.y)};
})
"""
# The controls around the composer and the Private switch: their words and their state.
CONTROLS = """
() => [...document.querySelectorAll('button, [role=button], [role=switch], [role=combobox]')]
    .map(e => ({text: (e.innerText || '').trim().slice(0, 30), label: e.getAttribute('aria-label'),
                pressed: e.getAttribute('aria-pressed'), expanded: e.getAttribute('aria-expanded'),
                haspopup: e.getAttribute('aria-haspopup'), y: Math.round(e.getBoundingClientRect().y),
                x: Math.round(e.getBoundingClientRect().x)}))
    .filter(c => /private|bot|model|grok|auto|fast|expert|send|submit/i.test((c.text || '') + ' ' + (c.label || '')))
    .slice(0, 20)
"""
MENU = """
() => [...document.querySelectorAll('[role=menu] [role^=menuitem], [role=listbox] [role=option]')]
    .map(e => (e.innerText || '').trim().replace(/\\s+/g, ' ').slice(0, 80)).slice(0, 16)
"""
LINKS = """
() => [...new Set([...document.querySelectorAll('a[href]')].map(a => a.getAttribute('href'))
    .filter(h => h && !h.startsWith('http') && h !== '/' && !h.startsWith('#'))
    .map(h => h.replace(/[0-9a-f]{8}-[0-9a-f-]{27}/g, '<id>')))].slice(0, 16)
"""

# Measured 2026-09-24: the server is the honest witness. /responses carries each
# turn with partial=false once it is finished, and response-node carries
# inflightResponses, empty when nothing is generating. The page shows "Working
# for 2s" inside the assistant bubble while it thinks, which is what made a
# DOM-only reader call the turn finished three seconds in.
SERVER_TURNS = "/rest/app-chat/conversations/{}/responses?includeThreads=true"
SERVER_NODES = "/rest/app-chat/conversations/{}/response-node?includeThreads=true"

# The body is returned whole: an earlier version cut it at 600 characters, and
# an image turn's /responses is 5kB, so every read parsed as nothing and the
# settle never fired. Callers print slices; the parser gets the real thing.
FETCH = """
async ([path, method, body]) => {
    const opts = {method: method, credentials: 'include'};
    if (body) { opts.headers = {'Content-Type': 'application/json'}; opts.body = body; }
    const r = await fetch(path, opts);
    let t = ''; try { t = await r.text(); } catch (e) {}
    return {status: r.status, body: t};
}
"""

GROK_RENDER = re.compile(r"<grok:render[^>]*>.*?</grok:render>|<grok:render[^>]*/?>", re.S)


def assistant_media(turn):
    """Asset ids of whatever the turn produced, with their mime types."""
    out = []
    for item in (turn.get("fileAttachmentsMetadata") or turn.get("fileAttachmentAssetMetadata") or []):
        ident = item.get("fileMetadataId") or item.get("assetId")
        if ident:
            out.append((ident, item.get("fileMimeType") or item.get("mimeType") or "?"))
    return out

REPLY = """
() => {
    const sels = ['[data-testid="assistant-message"]', '.response-content-markdown',
                  '.message-bubble.assistant', '[data-testid="message-bubble"]'];
    for (const s of sels) {
        const els = document.querySelectorAll(s);
        if (els.length) return els[els.length - 1].innerText.trim();
    }
    return '';
}
"""

IMAGES = """
() => Array.from(document.querySelectorAll('main img, [data-testid="assistant-message"] img'))
        .map(i => i.src).filter(s => s && !s.startsWith('data:')).slice(0, 8)
"""

say = lambda tag, detail: print("[{}] {}".format(tag, detail), flush=True)


def open_page(account, watch=False):
    page = account.new_page()
    seen = {"ws": [], "posts": [], "answers": []}
    if watch:
        page.on("websocket", lambda ws: seen["ws"].append(ws.url[:80]))
        page.on("request", lambda r: seen["posts"].append(
            (r.method, r.url.split("grok.com", 1)[-1][:60]))
            if r.method in ("POST", "PUT", "DELETE") and "/rest/" in r.url else None)
        # What the server answered, not only what the page asked: a send the server refuses is a
        # request too.
        page.on("response", lambda r: seen["answers"].append(
            (r.request.method, r.url.split("grok.com", 1)[-1].split("?")[0][:60], r.status))
            if r.request.method in ("POST", "PUT", "DELETE") and "grok.com" in r.url else None)

    t0 = time.time()
    page.goto(HOME, wait_until="domcontentloaded", timeout=90000)
    cleared = None
    for _ in range(14):
        page.wait_for_timeout(3000)
        if "security verification" not in (page.inner_text("body") or "").lower():
            cleared = time.time() - t0
            break
    say("open", "challenge cleared after {}".format(
        "{:.0f}s".format(cleared) if cleared else "NEVER"))

    # The cookie dialog can sit over the composer; the saved session usually
    # carries the answer already, so this is a belt-and-braces click on its own
    # close control, never on "accept".
    for sel in ("#onetrust-reject-all-handler", "#onetrust-close-btn-container button",
                "button[aria-label='Close']"):
        try:
            if page.locator(sel).count() and page.locator(sel).first.is_visible():
                page.locator(sel).first.click(timeout=3000)
                say("open", "dismissed a cookie dialog with {}".format(sel))
                break
        except Exception:
            continue

    # Measured 2026-11-16: looked at right after the challenge the page had painted nothing (a
    # composer at 11s, its text at 33s), and "NONE" was this probe's haste. Wait for a real editor.
    first_seen = {}
    while time.time() - t0 < EDITOR_WAIT:
        for sel in COMPOSER:
            try:
                if sel not in first_seen and page.locator(sel).count() and page.locator(sel).first.is_visible():
                    first_seen[sel] = round(time.time() - t0, 1)
            except Exception:
                continue
        if any(sel in first_seen for sel in EDITORS):
            break
        page.wait_for_timeout(1000)
    say("open", "composer first seen, seconds after the load began: {}".format(first_seen or "nothing"))
    page.wait_for_timeout(1500)
    cohort = [s for s in COMPOSER if page.locator(s).count() and page.locator(s).first.is_visible()]
    threads = page.locator('a[href^="/c/"]').count()
    say("open", "composer cohort: {}".format(cohort or "NONE"))
    say("open", "threads in sidebar: {} (0 would mean signed out)".format(threads))
    listing = page.evaluate(FETCH, ["/rest/app-chat/conversations?pageSize=1", "GET", None])
    say("open", "the account's conversation list answers {}".format(listing["status"]))
    return page, seen, (cohort[0] if cohort else None)


def newest(page, tag):
    """The server's newest conversations: whether a turn made a thread is the server's to say."""
    got = page.evaluate(FETCH, ["/rest/app-chat/conversations?pageSize=4", "GET", None])
    try:
        rows = [((c.get("conversationId") or "")[:8], c.get("createTime"), c.get("temporary"), (c.get("title") or "")[:30])
                for c in json.loads(got["body"]).get("conversations") or []]
    except ValueError:
        rows = got["body"][:120]
    say(tag, "server's newest conversations ({}): {}".format(got["status"], rows))


MODEL_BUTTON = 'button[aria-haspopup="menu"][aria-label^="Model"]'
MENU_ITEMS = """
() => [...document.querySelectorAll('[role=menu] [role^=menuitem], [role=listbox] [role=option]')].map(e => ({
    role: e.getAttribute('role'), first: (e.innerText || '').trim().split('\\n')[0].slice(0, 30),
    checked: e.getAttribute('aria-checked'), state: e.getAttribute('data-state'),
    disabled: e.getAttribute('aria-disabled') || e.getAttribute('data-disabled')}))
"""


def model_label(page):
    button = page.locator(MODEL_BUTTON)
    return button.first.get_attribute("aria-label") if button.count() else None


def probe_model(account):
    """Choose a model in the selector beside the composer (the second argument, Auto when none) and see
    whether the choice holds across a load. Changes which model the account's next chat uses; no turn."""
    wanted = ([a for a in sys.argv[2:] if a.isalpha()] or ["Auto"])[0]
    page, _, cohort = open_page(account)
    say("model", "the selector reads {!r}; buttons matching {}: {}".format(
        model_label(page), MODEL_BUTTON, page.locator(MODEL_BUTTON).count()))
    page.locator(MODEL_BUTTON).first.click(timeout=8000)
    page.wait_for_timeout(1200)
    items = page.evaluate(MENU_ITEMS)
    for item in items:
        say("model", "menu item: {}".format(item))
    choice = page.locator('[role=menu] [role^=menuitem]').filter(has_text=re.compile(r"^\s*" + wanted + r"\b"))
    say("model", "items whose words begin with {!r}: {}".format(wanted, choice.count()))
    if not choice.count():
        page.keyboard.press("Escape")
        return
    choice.first.click(timeout=5000)
    page.wait_for_timeout(1500)
    say("model", "after choosing, the selector reads {!r}; a menu is still open: {}; the page is at {}".format(
        model_label(page), bool(page.locator('[role=menu]').count()), page.url[:60]))
    page.goto(HOME, wait_until="domcontentloaded", timeout=90000)
    for _ in range(40):
        page.wait_for_timeout(1000)
        if page.locator(MODEL_BUTTON).count():
            break
    page.wait_for_timeout(2000)
    say("model", "after a fresh load the selector reads {!r}".format(model_label(page)))


def probe_composer(account):
    """The page around the composer, measured without a turn: what is editable, what the controls
    beside it say, what the selector offers, where the links go, and whether text typed into the
    editor is read back from it. The text is removed again; nothing is sent."""
    page, _, cohort = open_page(account)
    for item in page.evaluate(EDITABLES):
        say("composer", "editable: {}".format(item))
    for item in page.evaluate(CONTROLS):
        say("composer", "control: {}".format(item))
    say("composer", "link shapes: {}".format(page.evaluate(LINKS)))
    say("composer", "body, last 300 chars: {!r}".format((page.inner_text("body") or "")[-300:]))
    # The selector beside the composer ("Bot" on 2026-11-16): opened, read, closed with Escape.
    try:
        picker = page.locator('button[aria-haspopup="menu"]').filter(has_text=re.compile(r"^(Bot|Auto|Fast|Expert|Grok)", re.I))
        say("composer", "selector buttons matching: {}".format(picker.count()))
        if picker.count():
            picker.first.click(timeout=5000)
            page.wait_for_timeout(1200)
            say("composer", "selector offers: {}".format(page.evaluate(MENU) or "nothing read"))
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
    except Exception as exc:
        say("composer", "selector not opened, {}: {}".format(type(exc).__name__, str(exc)[:120]))
    if not cohort:
        say("composer", "no composer, nothing typed")
        return
    box = page.locator(cohort).first
    try:
        box.click(timeout=8000)
        how = "clicked"
    except Exception as exc:
        box.evaluate("(el) => el.focus()")
        how = "click raised {}, focused instead".format(type(exc).__name__)
    page.keyboard.insert_text("probe text, not sent")
    page.wait_for_timeout(500)
    say("composer", "{} {}; read back {!r}".format(how, cohort, (box.inner_text() or "")[:60]))
    page.keyboard.press("ControlOrMeta+a")
    page.keyboard.press("Backspace")
    page.wait_for_timeout(400)
    say("composer", "after clearing, the editor holds {!r}".format((box.inner_text() or "").strip()[:40]))
    page.screenshot(path=str(DIAGNOSTICS / "grok-probe-composer.png"))


def quota(page, tag="quota"):
    for kind in ("DEFAULT", "REASONING"):
        got = page.evaluate(FETCH, ["/rest/rate-limits", "POST",
                                    json.dumps({"requestKind": kind, "modelName": "grok-4"})])
        say(tag, "{} -> {} {}".format(kind, got["status"], got["body"][:150]))


def send(page, cohort, prompt):
    box = page.locator(cohort).first
    box.click(timeout=15000)
    # ProseMirror ignores fill(), and keyboard.type() presses a key per
    # character with "\n" mapped to Enter, which on grok.com sends. insert_text
    # is one CDP call and cannot split a prompt into several turns.
    page.keyboard.insert_text(prompt)
    page.wait_for_timeout(400)
    say("send", "the editor {} holds {!r} before Enter".format(cohort, (box.inner_text() or "")[:60]))
    page.keyboard.press("Enter")
    page.wait_for_timeout(1500)
    say("send", "1.5s after Enter the editor holds {!r}, the page is at {}".format(
        (box.inner_text() or "").strip()[:60] if box.count() else "(editor gone)", page.url[:80]))


def thread_id(url):
    return url.rsplit("/c/", 1)[-1].split("?")[0].split("#")[0] if url and "/c/" in url else None


def server_turn(page, cid):
    """The last assistant turn as the server tells it, and whether it is done."""
    turns = page.evaluate(FETCH, [SERVER_TURNS.format(cid), "GET", None])
    nodes = page.evaluate(FETCH, [SERVER_NODES.format(cid), "GET", None])
    try:
        body = json.loads(turns["body"]) if turns["status"] == 200 else {}
    except ValueError:
        body = {}
    try:
        node_body = json.loads(nodes["body"]) if nodes["status"] == 200 else {}
    except ValueError:
        node_body = {}
    answers = [r for r in (body.get("responses") or []) if r.get("sender") == "assistant"]
    last = answers[-1] if answers else {}
    inflight = node_body.get("inflightResponses")
    done = bool(last) and not last.get("partial") and inflight == []
    return last, done, turns["status"]


def await_reply(page, budget=180):
    """Settle on the server's word; the page only says when to ask."""
    t0 = time.time()
    reply, thread, cid = "", None, None
    address = page.url
    while time.time() - t0 < budget:
        page.wait_for_timeout(3000)
        if page.url != address:
            address = page.url
            say("turn", "the page moved after {:.0f}s to {}".format(time.time() - t0, address[:90]))
        if not thread and "/c/" not in page.url and time.time() - t0 > NO_THREAD_SECONDS:
            say("turn", "no /c/ address after {:.0f}s; giving up the wait".format(time.time() - t0))
            break
        if not thread and "/c/" in page.url:
            thread = page.url
            cid = thread_id(thread)
            say("turn", "thread url appeared after {:.0f}s: {}".format(time.time() - t0, thread))
        if not cid:
            continue
        last, done, status = server_turn(page, cid)
        if status != 200:
            continue
        if done:
            reply = (last.get("message") or "").strip()
            say("turn", "server says finished at {:.0f}s (partial={}, responseId={})".format(
                time.time() - t0, last.get("partial"), (last.get("responseId") or "")[:8]))
            break
    if not reply:
        reply = page.evaluate(REPLY)
        say("turn", "fell back to the page after {:.0f}s".format(time.time() - t0))
    return reply, thread, time.time() - t0


def probe_turn(account):
    page, seen, cohort = open_page(account, watch=True)
    if not cohort:
        say("turn", "no composer, stopping")
        return
    quota(page, "quota before")
    say("turn", "the model selector reads {!r}".format(model_label(page)))
    newest(page, "before")
    del seen["answers"][:]
    send(page, cohort, "Reply with the single word: pong")
    reply, thread, took = await_reply(page)
    say("turn", "{:.0f}s reply={!r}".format(took, reply[:160]))
    say("turn", "thread: {}".format(thread or "NONE"))
    say("turn", "websockets: {}".format(seen["ws"] or "none"))
    posts = []
    for entry in seen["posts"]:
        if entry not in posts:
            posts.append(entry)
    say("turn", "rest posts during the turn: {}".format(posts or "none"))
    say("turn", "answers to the page's writes since the send: {}".format(seen["answers"][:16] or "none"))
    newest(page, "after")
    if not thread:
        say("turn", "link shapes: {}".format(page.evaluate(LINKS)))
        say("turn", "body, last 400 chars: {!r}".format((page.inner_text("body") or "")[-400:]))
        page.screenshot(path=str(DIAGNOSTICS / "grok-probe-turn-no-thread.png"))

    if thread:
        cid = thread_id(thread)
        node = page.evaluate(FETCH, [SERVER_NODES.format(cid), "GET", None])
        say("settle", "response-node {} raw: {}".format(node["status"], node["body"][:220]))
        # Reload to prove the thread persists, which is what thread_url depends on.
        page.goto(thread, wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        say("turn", "after reload the thread shows {} chars of conversation".format(
            len(page.evaluate(REPLY) or "")))
    quota(page, "quota after")


def probe_image(account):
    page, seen, cohort = open_page(account, watch=True)
    if not cohort:
        say("image", "no composer, stopping")
        return
    send(page, cohort, "Generate an image: a plain orange circle on a white background")
    reply, thread, took = await_reply(page, budget=240)
    images = page.evaluate(IMAGES)
    say("image", "{:.0f}s reply={!r}".format(took, (reply or "")[:140]))
    say("image", "thread: {}".format(thread or "NONE"))
    say("image", "image urls: {}".format(images or "none"))
    for url in images[:1]:
        got = page.evaluate("""async (u) => { const r = await fetch(u, {credentials:'include'});
            return {status: r.status, type: r.headers.get('content-type'),
                    bytes: r.ok ? (await r.blob()).size : 0}; }""", url)
        say("image", "fetch in page {} -> {}".format(url[:70], got))


def probe_thread(account):
    """Read one finished thread as the server tells it; costs no turn."""
    wanted = [a for a in sys.argv[2:] if re.match(r"^[0-9a-f-]{20,}$", a)]
    if not wanted:
        say("thread", "pass a conversation id to inspect")
        return
    cid = wanted[0]
    page, _, _ = open_page(account)
    last, done, status = server_turn(page, cid)
    say("thread", "responses {} done={} partial={}".format(status, done, last.get("partial")))
    text = GROK_RENDER.sub("", last.get("message") or "").strip()
    say("thread", "assistant text after stripping render tags: {!r}".format(text[:160]))
    say("thread", "media: {}".format(assistant_media(last) or "none"))
    say("thread", "keys on the turn: {}".format(sorted(last)[:14]))
    # The thread's own page, as a follow-up turn opens it: is the model selector there, and what does it read?
    page.goto("{}c/{}".format(HOME, cid), wait_until="domcontentloaded", timeout=90000)
    seen_at, t0 = None, time.time()
    while time.time() - t0 < EDITOR_WAIT and seen_at is None:
        page.wait_for_timeout(1000)
        if any(page.locator(s).count() and page.locator(s).first.is_visible() for s in EDITORS):
            seen_at = round(time.time() - t0, 1)
    page.wait_for_timeout(2000)
    say("thread", "on the thread's page: editor after {}s, landed {}, the selector reads {!r} ({} button(s))".format(
        seen_at, page.url[:60], model_label(page), page.locator(MODEL_BUTTON).count()))


def probe_cleanup(account):
    """Delete one thread this probe made, then prove it is gone.

    The id comes from the command line so a probe can never remove a thread a
    person wrote; with no id it reports the newest and deletes nothing.
    """
    page, _, _ = open_page(account)
    listing = page.evaluate(FETCH, ["/rest/app-chat/conversations?pageSize=3", "GET", None])
    say("cleanup", "list {} {}".format(listing["status"], listing["body"][:200]))
    wanted = [a for a in sys.argv[2:] if re.match(r"^[0-9a-f-]{20,}$", a)]
    if not wanted:
        say("cleanup", "no conversation id given, nothing deleted (pass one to delete it)")
        return
    cid = wanted[0]
    gone = page.evaluate(FETCH, ["/rest/app-chat/conversations/soft/{}".format(cid), "DELETE", None])
    say("cleanup", "DELETE soft/{} -> {} {}".format(cid[:8], gone["status"], gone["body"][:80]))
    again = page.evaluate(FETCH, ["/rest/app-chat/conversations/soft/{}".format(cid), "DELETE", None])
    say("cleanup", "DELETE again -> {} (404 means idempotent)".format(again["status"]))
    read = page.evaluate(FETCH, ["/rest/app-chat/conversations/{}/response-node".format(cid), "GET", None])
    say("cleanup", "read after delete -> {}".format(read["status"]))


PROBES = {"open": lambda b: open_page(b), "composer": probe_composer, "model": probe_model,
          "turn": probe_turn, "image": probe_image,
          "thread": probe_thread, "cleanup": probe_cleanup}


def main():
    wanted = sys.argv[1] if len(sys.argv) > 1 else "open"
    names = list(PROBES) if wanted == "all" else [w for w in wanted.split(",") if w in PROBES]
    if not names:
        sys.exit("usage: grok_probe.py [{}|all], comma separated".format("|".join(PROBES)))

    try:
        account = open_session(SESSIONS, "grok")
    except ProviderError as exc:
        sys.exit(str(exc))
    crashed = []
    try:
        for name in names:
            say(name, "starting")
            try:
                PROBES[name](account)
            except Exception as exc:
                crashed.append(name)
                say(name, "PROBE CRASHED {}: {}".format(type(exc).__name__, str(exc)[:220]))
    finally:
        account.close()
    print("=" * 50)
    print("{} probe(s) ran, {} crashed{}".format(
        len(names), len(crashed), ": " + ", ".join(crashed) if crashed else ""))
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
