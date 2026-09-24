#!/usr/bin/env python3
"""Check the ChatGPT DOM signatures the worker relies on, against captured fixtures.

    ~/cloakbrowser-env/bin/python tests/test_dom_signatures.py

The fixtures under tests/fixtures/ are snippets saved from the real site by
tests/provider_probe.py. The error banner must be recognised in its own fixture
and not in an ordinary reply, so a detector that matches everything, or nothing,
fails here without a real failure to provoke. Prints N/3 PASSED.
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
    finally:
        browser.close()
    return finish()


if __name__ == "__main__":
    sys.exit(main())
