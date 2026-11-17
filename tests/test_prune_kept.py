#!/usr/bin/env python3
"""A failed turn's kept page is removed after 14 days, by the worker, when it keeps the next one (#35).

    ~/cloakbrowser-env/bin/python tests/test_prune_kept.py

Every driver method that keeps a page (storage/diagnostics/, storage/failures/) first removes the files
in that folder older than 14 days. A file younger than that stays, and so does a folder put there by
hand with everything in it. Prints N/8 PASSED.
"""

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.chatgpt import ChatGPTProvider  # noqa: E402
from src.providers.gemini import GeminiProvider  # noqa: E402
from src.providers.grok import GrokProvider  # noqa: E402

DAY = 86400
results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Page:
    """Only what the keepers need to leave a picture; everything else they read raises, which they record."""
    url = "https://example.invalid/c/x"
    frames = []

    def screenshot(self, path, timeout=None):
        Path(path).write_bytes(b"png")

    def title(self):
        return "a page"

    def evaluate(self, script):
        return {}

    def inner_text(self, *args, **kwargs):
        return ""


def aged(path, days):
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text("old")
    when = time.time() - days * DAY
    os.utime(path, (when, when))
    return path


def main():
    root = Path(tempfile.mkdtemp(prefix="prune-kept-"))
    media, sessions = root / "media", root / "sessions"
    diagnostics, failures = root / "diagnostics", root / "failures"
    chatgpt = ChatGPTProvider(media, sessions)
    chatgpt._opened_at, chatgpt._refused = None, []
    grok = GrokProvider(media, sessions)
    grok.last_open = None
    gemini = GeminiProvider(media, sessions)
    page = Page()

    keepers = (
        ("chatgpt's Cloudflare check", diagnostics, lambda: chatgpt._keep_check(page, "a banner")),
        ("chatgpt's failed open", diagnostics, lambda: chatgpt._keep_picture(page)),
        ("grok's unheard turn", diagnostics, lambda: grok._keep_unheard(page, "cid", time.time())),
        ("grok's failed open or send", diagnostics, lambda: grok._keep_failure(page, "open", RuntimeError("x"))),
        ("gemini's unread switch", failures, lambda: gemini._keep_switch(page, "/saved-info", [], None)),
        ("gemini's failed turn", failures, lambda: gemini._keep_failure(page)),
    )
    for name, folder, keep in keepers:
        old = aged(folder / "old-record-{}.png".format(abs(hash(name))), 15)
        before = set(folder.iterdir())
        keep()
        new = set(folder.iterdir()) - before
        record("{} removes a record older than 14 days".format(name), not old.exists() and bool(new),
               "old {}, new files {}".format("still there" if old.exists() else "gone", len(new)))

    young = aged(diagnostics / "young.png", 13)
    by_hand = aged(diagnostics / "look-by-hand" / "old.png", 40)
    os.utime(by_hand.parent, (time.time() - 40 * DAY,) * 2)
    chatgpt._keep_picture(page)
    record("a record 13 days old stays", young.exists(), "young.png {}".format("kept" if young.exists() else "gone"))
    record("a folder put there by hand stays whole", by_hand.exists(),
           "look-by-hand/old.png {}".format("kept" if by_hand.exists() else "gone"))

    print("{}/{} PASSED".format(sum(results), len(results)))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
