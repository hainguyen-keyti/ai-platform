#!/usr/bin/env python3
"""Check the ChatGPT DOM signatures the worker relies on, against captured fixtures.

    ~/cloakbrowser-env/bin/python tests/test_dom_signatures.py

The fixtures under tests/fixtures/ are snippets saved from the real site by
tests/provider_probe.py. The error banner must be recognised in its own fixture
and not in an ordinary reply, so a detector that matches everything, or nothing,
fails here without a real failure to provoke. Prints N/10 PASSED.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "worker"))

# One positive case and two negatives: the assistant turn alone, and the whole
# main area of a healthy page with composer and all, so a detector that fires
# on something ordinary is caught here.
CASES = (
    ("chatgpt_error_banner.html", True),
    ("chatgpt_reply.html", False),
    ("chatgpt_main_reply.html", False),
)

# Two banners, an old one first: the detector must report both, or a fresh
# failure appended after a persisted one would hide behind it.
TWO_BANNERS = """<main>
<div class="text-token-text-error border"><span>old: persisted from an earlier turn</span><button>Retry</button></div>
<article>ordinary turn</article>
<div class="text-token-text-error border"><span>new: this turn failed</span><button>Retry</button></div>
</main>"""

# The same, in the shape chatgpt.com paints since 2026-09-27: an aside with role
# alert and a text-danger token, the server's message and a Retry button.
TWO_BANNERS_NEW = """<main>
<aside role="alert" class="border text-sm border-text-danger/20 text-danger"><div>old: persisted from an earlier turn</div><button>Retry</button></aside>
<div data-turn-key="t1">ordinary turn</div>
<aside role="alert" class="border text-sm border-text-danger/20 text-danger"><div>new: this turn failed</div><button>Retry</button></aside>
</main>"""

# Pictures, measured 2026-09-27: both a generated picture and a user's upload are
# blob: images inside the turn, neither inside the user bubble nor the assistant
# message; only the generated one sits in the generated-image gallery. The
# fixtures' src attributes are stripped, so each image gets a real blob: url of a
# 300x300 canvas, which is the scheme and the size the page really uses.
IMAGE_CASES = (
    ("chatgpt_generated_image.html", 1),
    ("chatgpt_user_attachment.html", 0),
)

# A notice that is not a failure: role alert with a button, but not the measured
# banner. Counting it would throw a good answer away as a provider error.
NEUTRAL_ALERT = """<main>
<div data-turn-key="t1">an ordinary reply</div>
<div role="alert">Memory is full<button>Manage</button></div>
</main>"""

GIVE_BLOBS = """
async () => {
    const canvas = document.createElement('canvas');
    canvas.width = 300; canvas.height = 300;
    canvas.getContext('2d').fillRect(0, 0, 300, 300);
    const blob = await new Promise((resolve) => canvas.toBlob(resolve, 'image/png'));
    const imgs = Array.from(document.querySelectorAll('img'));
    await Promise.all(imgs.map((img) => new Promise((resolve) => {
        img.onload = resolve; img.onerror = resolve;
        img.src = URL.createObjectURL(blob);
    })));
    return imgs.length;
}
"""

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def finish():
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


def main():
    try:
        from src.providers.chatgpt import ERROR_BANNER_PRESENT
    except ImportError as exc:
        for name, _ in CASES:
            record(name, False, "no detector to run: {}".format(exc))
        return finish()

    import cloakbrowser

    browser = cloakbrowser.launch(headless=True)
    try:
        page = browser.new_context().new_page()
        for name, expected in CASES:
            path = FIXTURES / name
            if not path.exists():
                record(name, False, "fixture missing at {}".format(path))
                continue
            # Injected straight into the body: set_content waits for a load
            # event the snippet's missing stylesheets never fire, and only the
            # DOM matters here.
            page.evaluate("(html) => { document.body.innerHTML = html; }", path.read_text())
            found = bool(page.evaluate(ERROR_BANNER_PRESENT))
            record(name, found == expected, "detector says {}, expected {}".format(found, expected))
        page.evaluate("(html) => { document.body.innerHTML = html; }", TWO_BANNERS)
        texts = page.evaluate(ERROR_BANNER_PRESENT)
        record("two banners, old one first", len(texts) == 2 and texts[-1].startswith("new:"),
               "detector returned {}".format(texts))
        page.evaluate("(html) => { document.body.innerHTML = html; }", TWO_BANNERS_NEW)
        texts = page.evaluate(ERROR_BANNER_PRESENT)
        record("two banners in the new shape, old one first",
               len(texts) == 2 and texts[-1].startswith("new:"), "detector returned {}".format(texts))

        from src.providers.chatgpt import COLLECT_CANDIDATE_IMAGES
        for name, expected in IMAGE_CASES:
            path = FIXTURES / name
            if not path.exists():
                record(name, False, "fixture missing at {}".format(path))
                continue
            page.evaluate("(html) => { document.body.innerHTML = html; }", path.read_text())
            given = page.evaluate(GIVE_BLOBS)
            kept = page.evaluate(COLLECT_CANDIDATE_IMAGES)
            record(name + " pictures kept", len(kept) == expected,
                   "{} img given a blob, {} kept, expected {}".format(given, len(kept), expected))

        # Two turns in one thread, each with its own picture: only the last turn's
        # picture is this turn's result, whatever its blob url happens to be.
        picture_turn = (FIXTURES / "chatgpt_generated_image.html").read_text()
        page.evaluate("(html) => { document.body.innerHTML = html; }", picture_turn + picture_turn)
        given = page.evaluate(GIVE_BLOBS)
        kept = page.evaluate(COLLECT_CANDIDATE_IMAGES)
        record("an earlier turn's picture is not this turn's", len(kept) == 1,
               "{} img given a blob, {} kept, expected 1".format(given, len(kept)))

        page.evaluate("(html) => { document.body.innerHTML = html; }", NEUTRAL_ALERT)
        found = page.evaluate(ERROR_BANNER_PRESENT)
        record("a neutral alert is not a failure", not found, "detector returned {}".format(found))

        from src.providers.chatgpt import ASSISTANT_TURN
        page.evaluate("(html) => { document.body.innerHTML = html; }",
                      (FIXTURES / "chatgpt_reply.html").read_text())
        replies = page.locator(ASSISTANT_TURN)
        text = replies.last.inner_text().strip() if replies.count() else ""
        record("the reply is found in the new markup", replies.count() == 1 and bool(text),
               "{} reply element(s), {} characters".format(replies.count(), len(text)))
    finally:
        browser.close()
    return finish()


if __name__ == "__main__":
    sys.exit(main())
