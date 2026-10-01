#!/usr/bin/env python3
"""Measure the Gemini behaviours a provider would depend on, against the real site.

    ~/cloakbrowser-env/bin/python tests/gemini_probe.py <probe>[,<probe>] [ids]

Each probe prints what it saw; nothing here asserts a wish. Costs:
  open, session, settings-read, banner, list, peek   no turn
  settle                                              one turn
  persist                                             two turns (a picture, an upload)
  recall                                              three turns
  purge <id,id>                                       deletes exactly the named threads
Every turn leaves a thread in the owner's account; they are deleted only by name, with the owner's
yes. Opens the provider's own profile, storage/sessions/gemini/, as the worker does: take gemini
off the host worker first, the profile opens in one browser at a time. Never changes an account
setting. Measured first on 2026-09-25 with a throwaway copy of this file; see docs/research.
"""

import base64
import json
import sys
import time
from pathlib import Path

import cloakbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.base import ProviderError  # noqa: E402
from src.providers.session import open_session, profile_of  # noqa: E402

SESSIONS = ROOT / "storage" / "sessions"
HOME = "https://gemini.google.com/app"
COMPOSER = 'rich-textarea .ql-editor[contenteditable="true"]'
SIGN_IN = ("sign in", "đăng nhập")

CONVERSATIONS = """
() => Array.from(document.querySelectorAll('a[href^="/app/"]')).map(a => ({
    href: a.getAttribute('href'), title: (a.innerText || '').trim().slice(0, 60)}))
"""

MENU_ITEMS = """
() => Array.from(document.querySelectorAll('[role="menuitem"], button.mat-mdc-menu-item'))
    .map(n => ({test: n.getAttribute('data-test-id'), label: (n.innerText || '').trim().slice(0, 40)}))
"""

# gstatic serves the product's own decorations; they are on the page before any turn.
BIG_IMAGES = """
() => Array.from(document.querySelectorAll('img'))
    .map(n => ({src: (n.src || '').slice(0, 130), w: n.naturalWidth, h: n.naturalHeight}))
    .filter(o => o.w > 120 && o.src.indexOf('gstatic.com') === -1)
"""

# An 8x8 grey and white checker, the picture the 2026-09-25 upload probe used.
REFERENCE_PNG = ("iVBORw0KGgoAAAANSUhEUgAAAAgAAAAIAQMAAAD+wSzIAAAABlBMVEX///+/v7+jQ3Y5AAAADklEQVQI"
                 "12P4AIX8EAgALgAD/aNpbtEAAAAASUVORK5CYII=")

crashed = []


def say(tag, message):
    print("[{}] {}".format(tag, message), flush=True)


def flat(text):
    return " ".join((text or "").split())


def open_page(account, url=HOME, stored=True):
    """A tab of the account's own browser or, for a comparison, a page of a browser with no account."""
    page = account.new_page() if stored else cloakbrowser.launch(headless=True).new_page()
    t0 = time.time()
    page.goto(url, wait_until="domcontentloaded", timeout=90000)
    for _ in range(40):
        page.wait_for_timeout(500)
        if page.locator(COMPOSER).count():
            break
    page.wait_for_timeout(1500)
    say("open", "{} after {:.0f}s, composer {}".format(page.url, time.time() - t0,
                                                        page.locator(COMPOSER).count()))
    return page


def bubbles(page):
    try:
        return page.locator("message-content, model-response").all_inner_texts()
    except Exception:
        return []


def send(page, prompt):
    page.locator(COMPOSER).first.click(timeout=15000)
    page.keyboard.insert_text(prompt)
    page.wait_for_timeout(300)
    page.keyboard.press("Enter")


def wait_new_bubble(page, had, budget=120):
    """The answer to THIS turn: a bubble that was not there before, then held still."""
    t0, last = time.time(), None
    while time.time() - t0 < budget:
        page.wait_for_timeout(1000)
        now = bubbles(page)
        if len(now) <= had:
            continue
        text = now[-1].strip()
        if text and text == last:
            return text, round(time.time() - t0, 1)
        last = text
    return (last or ""), None


def wait_picture(page, budget=240):
    """A picture, not words: the reply text says it is working long before one exists."""
    t0 = time.time()
    while time.time() - t0 < budget:
        page.wait_for_timeout(3000)
        found = page.evaluate(BIG_IMAGES)
        if found:
            return found, round(time.time() - t0, 1)
    return [], None


def thread_of(page):
    tail = page.url.rsplit("/app/", 1)[-1] if "/app/" in page.url else ""
    return tail.split("?")[0] or None


# --- no turn ---------------------------------------------------------------

def listed(page, seconds=15):
    """The sidebar's conversations once it has painted them (0.3 to 2.4s after the composer)."""
    deadline = time.time() + seconds
    found = page.evaluate(CONVERSATIONS)
    while not found and time.time() < deadline:
        page.wait_for_timeout(250)
        found = page.evaluate(CONVERSATIONS)
    return found


def probe_open(account):
    page = open_page(account)
    body = (page.inner_text("body") or "").lower()
    say("open", "sign-in wording: {}".format([w for w in SIGN_IN if w in body] or "none"))
    say("open", "sidebar threads: {}".format(len(listed(page))))


# Candidate proofs that only a signed-in session can pass, fetched from the page
# itself. redirect 'manual' turns a bounce to the sign-in page into status 0.
PROOF = """
async (path) => {
    try {
        const r = await fetch(path, {credentials: 'include', redirect: 'manual'});
        let text = ''; try { text = await r.text(); } catch (e) {}
        return {status: r.status, type: r.type, bytes: text.length};
    } catch (e) { return {error: String(e).slice(0, 60)}; }
}
"""
PROOF_PATHS = ("/app", "/usage", "/personalization-settings")


def probe_session(account):
    """What a proof of sign-in could be: the same fetches, signed in and anonymous."""
    for stored in (True, False):
        page = open_page(account, stored=stored)
        who = "signed in" if stored else "anonymous"
        body = (page.inner_text("body") or "").lower()
        say("session", "{}: sign-in wording {}".format(who, [w for w in SIGN_IN if w in body] or "none"))
        for path in PROOF_PATHS:
            say("session", "{}: {} -> {}".format(who, path, page.evaluate(PROOF, path)))
        # Every path answers 200 either way (measured 2026-09-27), so the proof has to be
        # something only an account's page renders: its own settings switch.
        page.goto("https://gemini.google.com/personalization-settings",
                  wait_until="domcontentloaded", timeout=90000)
        page.wait_for_timeout(6000)
        say("session", "{}: settings page lands on {}, role=switch count {}".format(
            who, page.url, page.locator('button[role="switch"]').count()))
        if stored:
            page.close()
        else:
            page.context.browser.close()


def probe_settings_read(account):
    """What reading the personal context switch costs, and what the page asks the server."""
    page = account.new_page()
    rpcs = []
    page.on("response", lambda r: rpcs.append(
        (r.url.split("rpcids=", 1)[-1].split("&")[0], r.status))
        if "batchexecute" in r.url else None)
    t0 = time.time()
    page.goto("https://gemini.google.com/personalization-settings",
              wait_until="domcontentloaded", timeout=90000)
    state = None
    for _ in range(60):
        page.wait_for_timeout(500)
        switches = page.evaluate("""() => Array.from(document.querySelectorAll('button[role="switch"]'))
            .map(n => ({label: (n.getAttribute('aria-label') || '').slice(0, 70),
                        checked: n.getAttribute('aria-checked')}))""")
        if switches:
            state = switches
            break
    say("settings-read", "switches after {:.1f}s: {}".format(time.time() - t0, state))
    say("settings-read", "batchexecute rpcids while loading: {}".format(rpcs))


def probe_banner(account):
    """The error the page paints when a turn request fails, provoked from inside the page:
    the turn request is answered 500, so the server never sees a turn."""
    page = open_page(account)
    hits = {"n": 0, "urls": []}

    def fail(route):
        if route.request.method == "POST":
            hits["n"] += 1
            hits["urls"].append(route.request.url.split("?")[0][-60:])
            route.fulfill(status=500, content_type="application/json", body="{}")
        else:
            route.continue_()

    pattern = "**/*StreamGenerate*"
    page.route(pattern, fail)
    try:
        send(page, "probe: this request is made to fail on purpose")
        page.wait_for_timeout(12000)
        say("banner", "requests failed on purpose: {} {}".format(hits["n"], hits["urls"]))
        found = page.evaluate("""() => Array.from(document.querySelectorAll(
            '[role="alert"], snack-bar-container, .mat-mdc-snack-bar-container, [class*="error"]'))
            .map(n => ({tag: n.tagName.toLowerCase(), role: n.getAttribute('role'),
                        cls: (n.className || '').toString().slice(0, 80),
                        text: (n.innerText || '').trim().slice(0, 120)}))""")
        for item in found:
            say("banner", "element {}".format(item))
        say("banner", "last bubble {!r}".format((bubbles(page) or [""])[-1][:160]))
        say("banner", "url after the failure {}".format(page.url))
    finally:
        page.unroute(pattern, fail)


def probe_list(account):
    page = open_page(account)
    for item in listed(page):
        say("list", item)


TURN_ORDER = """
() => {
    const out = [];
    const tags = ['user-query', 'model-response', 'message-content'];
    for (const n of document.querySelectorAll(tags.join(','))) {
        out.push({tag: n.tagName.toLowerCase(), textLen: (n.innerText || '').trim().length,
                  head: (n.innerText || '').trim().slice(0, 24),
                  insideResponse: !!(n.parentElement && n.parentElement.closest('model-response'))});
    }
    return out;
}
"""


def probe_turn_order(account, ids):
    """How a thread's turns sit in the page, in document order. Opens a thread; costs no turn."""
    page = account.new_page()
    for cid in ids:
        page.goto("https://gemini.google.com/app/{}".format(cid), wait_until="domcontentloaded",
                  timeout=90000)
        page.wait_for_timeout(8000)
        for item in page.evaluate(TURN_ORDER):
            say("turn-order", "{} {}".format(cid[:8], item))


SMALLEST_TURNS_BLOCK = """
() => {
    const turns = document.querySelectorAll('user-query, model-response');
    if (!turns.length) return null;
    let node = turns[0].parentElement;
    while (node && Array.from(turns).some((t) => !node.contains(t))) node = node.parentElement;
    return node ? node.outerHTML : null;
}
"""


def probe_capture(account, ids):
    """Save one thread's turns, and nothing around them, as tests/fixtures/gemini_thread.html.
    Opens a thread; costs no turn. Scripts and every url are stripped before saving."""
    import re
    page = account.new_page()
    page.goto("https://gemini.google.com/app/{}".format(ids[0]), wait_until="domcontentloaded",
              timeout=90000)
    page.wait_for_timeout(8000)
    html = page.evaluate(SMALLEST_TURNS_BLOCK)
    if not html:
        say("capture", "no turns on {}".format(ids[0]))
        return
    html = re.sub(r"<script.*?</script>", "", html, flags=re.S)
    html = re.sub(r'\s(src|srcset|href|jslog|data-ved)="[^"]*"', "", html)
    path = ROOT / "tests" / "fixtures" / "gemini_thread.html"
    path.write_text("<main>\n{}\n</main>\n".format(html))
    say("capture", "{} written, {} chars, {} user-query, {} model-response".format(
        path.name, len(html), html.count("<user-query"), html.count("<model-response")))


def probe_peek(account, ids):
    """Does a thread exist, whatever the sidebar shows. A dead id lands back on /app."""
    page = account.new_page()
    t0 = [time.time()]
    seen = image_responses(page, t0)
    for cid in ids:
        del seen[:]
        page.goto("https://gemini.google.com/app/{}".format(cid), wait_until="domcontentloaded",
                  timeout=90000)
        page.wait_for_timeout(7000)
        body = bubbles(page)
        say("peek", "{} -> lands on {} with {} bubble(s)".format(cid, page.url.rsplit("/", 1)[-1],
                                                                len(body)))
        say("peek", "{} images fetched on opening: {}".format(
            cid, [(s["host"], s["prefix"][:12], s["bytes"]) for s in seen]))


# --- turns -----------------------------------------------------------------

def probe_settle(account, picture=False):
    """Which response carries the finished answer, and when, against when the page settles.
    With picture=True, also when the picture arrives against when the stream ends."""
    page = open_page(account)
    token = "teal-{}".format(int(time.time()) % 100000)
    t0 = time.time()
    seen = []

    def on_response(r):
        ctype = (r.headers or {}).get("content-type", "")
        if picture and "lh3.googleusercontent.com/rd-gg-dl/" in r.url and ctype.startswith("image/"):
            seen.append({"at": round(time.time() - t0, 1), "url": "lh3/rd-gg-dl/ (picture)",
                         "status": r.status})
            return
        if r.request.method != "POST" or "google" not in r.url:
            return
        try:
            body = r.body()
        except Exception:
            body = b""
        seen.append({"at": round(time.time() - t0, 1), "url": r.url.split("?")[0][-70:],
                     "rpc": r.url.split("rpcids=", 1)[-1].split("&")[0] if "rpcids=" in r.url else None,
                     "status": r.status, "bytes": len(body), "has_token": token.encode() in body,
                     "names_rd_gg": b"rd-gg" in body, "names_googleusercontent": b"googleusercontent" in body})

    page.on("response", on_response)
    had = len(bubbles(page))
    t0 = time.time()
    if picture:
        send(page, "Generate an image of a plain purple circle on a white background.")
        found, at = wait_picture(page)
        text = "picture {}".format([(f["w"], f["h"]) for f in found])
        page.wait_for_timeout(6000)
    else:
        send(page, "Write two short sentences, and end the second one with the word {}.".format(token))
        text, at = wait_new_bubble(page, had)
    say("settle", "page held still at {}s: {!r}".format(at, text[:120]))
    page.wait_for_timeout(3000)
    for item in seen:
        say("settle", "response {}".format(item))
    carriers = [s for s in seen if s.get("has_token")]
    say("settle", "responses whose body carries the token: {}".format(
        [(c["url"], c["rpc"], c["at"]) for c in carriers] or "none"))
    say("settle", "thread {}".format(thread_of(page)))


def probe_persist(account):
    """Do a picture turn's and an upload turn's threads survive? Measured 2026-09-25: both were
    gone minutes later, while chat threads survived; those probes closed the page seconds after
    the picture appeared. This one keeps the page open and reloads before closing."""
    made = []
    page = open_page(account)
    send(page, "Generate an image of a plain green triangle on a white background.")
    found, at = wait_picture(page)
    say("persist", "picture after {}s: {}".format(at, [(f["w"], f["h"]) for f in found]))
    page.wait_for_timeout(30000)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    say("persist", "picture thread after 30s open and a reload: url {} bubbles {}".format(
        page.url, len(bubbles(page))))
    made.append(thread_of(page))
    page.close()

    path = Path("/tmp/gemini-reference.png")
    path.write_bytes(base64.b64decode(REFERENCE_PNG))
    page = open_page(account)
    for sel in ("button[aria-label*='Nội dung tải lên']", "button[aria-label*='Upload']"):
        if page.locator(sel).count():
            page.locator(sel).first.click(timeout=10000)
            break
    page.wait_for_timeout(2000)
    page.set_input_files('input[type=file][accept="image/*"]', str(path))
    page.wait_for_timeout(6000)
    had = len(bubbles(page))
    send(page, "In one short sentence, what colours are in this picture?")
    text, at = wait_new_bubble(page, had, budget=180)
    say("persist", "upload reply at {}s: {!r}".format(at, text[:120]))
    page.wait_for_timeout(30000)
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(8000)
    say("persist", "upload thread after 30s open and a reload: url {} bubbles {}".format(
        page.url, len(bubbles(page))))
    made.append(thread_of(page))
    say("persist", "threads made: {} (peek them again in a few minutes)".format(made))


def image_responses(page, t0):
    """Every image the page downloads, by host and first path segment only: an lh3 url is a
    capability, so the whole url is never printed or stored."""
    seen = []

    def on_response(r):
        ctype = (r.headers or {}).get("content-type", "")
        if not ctype.startswith("image/") or "gstatic.com" in r.url:
            return
        rest = r.url.split("://", 1)[-1]
        host, _, path = rest.partition("/")
        try:
            size = len(r.body())
        except Exception:
            size = None
        seen.append({"at": round(time.time() - t0[0], 1), "host": host,
                     "prefix": "/" + path.split("/", 1)[0] + "/", "type": ctype[:20], "bytes": size})

    page.on("response", on_response)
    return seen


def probe_pictures(account):
    """Where a user's upload and a generated picture come from during the turn, so the driver
    can keep one and never the other. Two turns."""
    path = Path("/tmp/gemini-reference.png")
    path.write_bytes(base64.b64decode(REFERENCE_PNG))
    for kind in ("upload", "generate"):
        page = open_page(account)
        t0 = [time.time()]
        seen = image_responses(page, t0)
        if kind == "upload":
            for sel in ("button[aria-label*='Nội dung tải lên']", "button[aria-label*='Upload']"):
                if page.locator(sel).count():
                    page.locator(sel).first.click(timeout=10000)
                    break
            page.wait_for_timeout(2000)
            page.set_input_files('input[type=file][accept="image/*"]', str(path))
            page.wait_for_timeout(6000)
            say("pictures", "upload: before sending, image responses {}".format(list(seen)))
            del seen[:]
            t0[0] = time.time()
            had = len(bubbles(page))
            send(page, "In one short sentence, what colours are in this picture?")
            wait_new_bubble(page, had, budget=180)
        else:
            t0[0] = time.time()
            send(page, "Generate an image of a plain orange square on a white background.")
            wait_picture(page)
        page.wait_for_timeout(8000)
        say("pictures", "{}: image responses during the turn {}".format(kind, seen))
        say("pictures", "{}: big images on the page {}".format(
            kind, [(f["w"], f["h"], f["src"].split(":", 1)[0]) for f in page.evaluate(BIG_IMAGES)]))
        say("pictures", "{}: thread {}".format(kind, thread_of(page)))
        page.wait_for_timeout(20000)
        page.close()


def probe_recall(account):
    """Does one conversation leak into another. Personal context must be off for 'Unknown'."""
    page = open_page(account)
    token = "violet-{}".format(int(time.time()) % 100000)
    had = len(bubbles(page))
    send(page, "Remember this word for later, just acknowledge it: {}".format(token))
    first, _ = wait_new_bubble(page, had)
    thread_a = thread_of(page)
    had = len(bubbles(page))
    send(page, "What word did I ask you to remember?")
    same, _ = wait_new_bubble(page, had)
    say("recall", "A {} recalls its own word: {} {!r}".format(thread_a, token in same, same[:80]))
    page.goto(HOME, wait_until="domcontentloaded", timeout=90000)
    page.wait_for_timeout(8000)
    had = len(bubbles(page))
    send(page, "Earlier I asked you to remember a word. What was it? If you do not know, say Unknown.")
    other, _ = wait_new_bubble(page, had)
    say("recall", "B {} leaked the word: {} {!r}".format(thread_of(page), token in other, other[:80]))


# --- cleanup, by name only -------------------------------------------------

def open_row_menu(page, ident):
    link = page.locator('a[href="/app/{}"]'.format(ident)).first
    if not link.count():
        say("purge", "{} is not in the list".format(ident))
        return False
    title = (link.inner_text() or "").strip()
    link.hover(timeout=10000)
    page.wait_for_timeout(500)
    # This conversation's own row: a plain div ancestor holds every row in the list.
    row = link.locator('xpath=ancestor::*[@data-test-id="conversation"][1]')
    buttons = row.locator("button")
    for i in range(buttons.count()):
        b = buttons.nth(i)
        if not b.is_visible():
            continue
        label = b.get_attribute("aria-label") or ""
        if title and title not in label:
            say("purge", "refusing: the button says {!r}, the row is {!r}".format(label, title))
            return False
        b.click(timeout=10000)
        page.wait_for_timeout(1200)
        return True
    return False


def probe_purge(account, ids):
    page = open_page(account)
    here = {c["href"].rsplit("/", 1)[-1]: c["title"] for c in listed(page)}
    for cid in ids:
        say("purge", "target {} titled {!r}".format(cid, here.get(cid, "NOT IN LIST")))
    for cid in ids:
        if not open_row_menu(page, cid):
            continue
        hit = '[role="menuitem"][data-test-id*="delete"]'
        if not page.locator(hit).count():
            page.keyboard.press("Escape")
            continue
        # The confirm button repeats the menu item's own word, whatever the language.
        word = (page.locator(hit).first.inner_text() or "").strip()
        page.locator(hit).first.click(timeout=10000)
        page.wait_for_timeout(1500)
        buttons = page.locator("mat-dialog-container").first.locator("button")
        for i in range(buttons.count()):
            if (buttons.nth(i).inner_text() or "").strip() == word:
                buttons.nth(i).click(timeout=10000)
                say("purge", "deleted {}".format(cid))
                page.wait_for_timeout(2500)
                break
    page.reload(wait_until="domcontentloaded")
    page.wait_for_timeout(6000)
    left = page.evaluate(CONVERSATIONS)
    say("purge", "still present: {}".format(
        [c for c in ids if any(c in x["href"] for x in left)] or "none"))


PROBES = {"open": probe_open, "session": probe_session, "settings-read": probe_settings_read,
          "banner": probe_banner, "list": probe_list, "settle": probe_settle,
          "persist": probe_persist, "recall": probe_recall, "pictures": probe_pictures,
          "settle-picture": lambda b: probe_settle(b, picture=True)}
WITH_IDS = {"peek": probe_peek, "purge": probe_purge, "turn-order": probe_turn_order,
            "capture": probe_capture}
# "all" runs only what costs no turn and changes nothing.
FREE = ("open", "session", "settings-read", "banner", "list")


def main():
    if not profile_of(SESSIONS, "gemini").is_dir():
        sys.exit("no session at {}; run scripts/login_provider.py gemini".format(profile_of(SESSIONS, "gemini")))
    wanted = (sys.argv[1] if len(sys.argv) > 1 else "open").split(",")
    ids = [x for x in (sys.argv[2] if len(sys.argv) > 2 else "").split(",") if x]
    names = list(FREE) if wanted == ["all"] else wanted
    unknown = [n for n in names if n not in PROBES and n not in WITH_IDS]
    if unknown:
        sys.exit("unknown probe(s) {}; one of {} or all".format(
            unknown, ", ".join(list(PROBES) + list(WITH_IDS))))
    try:
        account = open_session(SESSIONS, "gemini")
    except ProviderError as exc:
        sys.exit(str(exc))
    try:
        for name in names:
            say(name, "starting")
            try:
                if name in WITH_IDS:
                    WITH_IDS[name](account, ids)
                else:
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
