#!/usr/bin/env python3
"""Measure the Grok behaviours a provider would depend on, against the real site.

    ~/cloakbrowser-env/bin/python tests/grok_probe.py [open|turn|image|cleanup|all]

Each probe prints what it saw; nothing here asserts a wish. The account is on a
free tier that allows very few turns per day, so `open` costs nothing and the
others cost one turn each: run them by name, not `all`, unless the budget is
known to be there. Reads the saved session in storage/sessions/grok.json.
Stop the host worker first if the browser refuses a second session.
"""

import json
import re
import sys
import time
from pathlib import Path

import cloakbrowser

ROOT = Path(__file__).resolve().parents[1]
SESSION = ROOT / "storage" / "sessions" / "grok.json"
HOME = "https://grok.com/"

COMPOSER = ('[data-testid="chat-input"] .ProseMirror[contenteditable="true"]',
            '.ProseMirror[contenteditable="true"]',
            'textarea[aria-label="Ask Grok anything"]',
            '[data-testid="chat-input"] textarea')
STOPPING = ('button[data-testid="chat-stop"]', 'button[aria-label="Stop"]',
            '[data-streaming="true"]', '[data-is-streaming="true"]')

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


def open_page(browser, watch=False):
    context = browser.new_context(storage_state=str(SESSION))
    page = context.new_page()
    seen = {"ws": [], "posts": []}
    if watch:
        page.on("websocket", lambda ws: seen["ws"].append(ws.url[:80]))
        page.on("request", lambda r: seen["posts"].append(
            (r.method, r.url.split("grok.com", 1)[-1][:60]))
            if r.method in ("POST", "PUT", "DELETE") and "/rest/" in r.url else None)

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

    cohort = [s for s in COMPOSER if page.locator(s).count()]
    threads = page.locator('a[href^="/c/"]').count()
    say("open", "composer cohort: {}".format(cohort or "NONE"))
    say("open", "threads in sidebar: {} (0 would mean signed out)".format(threads))
    return page, seen, (cohort[0] if cohort else None)


def quota(page, tag="quota"):
    for kind in ("DEFAULT", "REASONING"):
        got = page.evaluate(FETCH, ["/rest/rate-limits", "POST",
                                    json.dumps({"requestKind": kind, "modelName": "grok-4"})])
        say(tag, "{} -> {} {}".format(kind, got["status"], got["body"][:150]))


def send(page, cohort, prompt):
    box = page.locator(cohort).first
    box.click(timeout=15000)
    # ProseMirror ignores fill(); it listens to the keyboard pipeline only.
    page.keyboard.type(prompt)
    page.wait_for_timeout(400)
    page.keyboard.press("Enter")


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
    while time.time() - t0 < budget:
        page.wait_for_timeout(3000)
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


def probe_turn(browser):
    page, seen, cohort = open_page(browser, watch=True)
    if not cohort:
        say("turn", "no composer, stopping")
        return
    quota(page, "quota before")
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


def probe_image(browser):
    page, seen, cohort = open_page(browser, watch=True)
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


def probe_thread(browser):
    """Read one finished thread as the server tells it; costs no turn."""
    wanted = [a for a in sys.argv[2:] if re.match(r"^[0-9a-f-]{20,}$", a)]
    if not wanted:
        say("thread", "pass a conversation id to inspect")
        return
    cid = wanted[0]
    page, _, _ = open_page(browser)
    last, done, status = server_turn(page, cid)
    say("thread", "responses {} done={} partial={}".format(status, done, last.get("partial")))
    text = GROK_RENDER.sub("", last.get("message") or "").strip()
    say("thread", "assistant text after stripping render tags: {!r}".format(text[:160]))
    say("thread", "media: {}".format(assistant_media(last) or "none"))
    say("thread", "keys on the turn: {}".format(sorted(last)[:14]))


def probe_cleanup(browser):
    """Delete one thread this probe made, then prove it is gone.

    The id comes from the command line so a probe can never remove a thread a
    person wrote; with no id it reports the newest and deletes nothing.
    """
    page, _, _ = open_page(browser)
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


PROBES = {"open": lambda b: open_page(b), "turn": probe_turn, "image": probe_image,
          "thread": probe_thread, "cleanup": probe_cleanup}


def main():
    if not SESSION.exists():
        sys.exit("no session at {}; run scripts/login_provider.py grok".format(SESSION))
    wanted = sys.argv[1] if len(sys.argv) > 1 else "open"
    names = list(PROBES) if wanted == "all" else [w for w in wanted.split(",") if w in PROBES]
    if not names:
        sys.exit("usage: grok_probe.py [{}|all], comma separated".format("|".join(PROBES)))

    browser = cloakbrowser.launch(headless=True)
    crashed = []
    try:
        for name in names:
            say(name, "starting")
            try:
                PROBES[name](browser)
            except Exception as exc:
                crashed.append(name)
                say(name, "PROBE CRASHED {}: {}".format(type(exc).__name__, str(exc)[:220]))
    finally:
        browser.close()
    print("=" * 50)
    print("{} probe(s) ran, {} crashed{}".format(
        len(names), len(crashed), ": " + ", ".join(crashed) if crashed else ""))
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main())
