#!/usr/bin/env python3
"""Open a real browser so a provider can be logged in by hand, then save the session.

    python scripts/login_provider.py chatgpt

Run it with the cloakbrowser venv. Log in in the window that opens, then come back
to the terminal and press Enter.
"""

import sys
from pathlib import Path

import cloakbrowser

HOMES = {
    "chatgpt": "https://chatgpt.com/",
    "grok": "https://x.com/i/grok",
    "gemini": "https://gemini.google.com/",
}

ROOT = Path(__file__).resolve().parent.parent


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in HOMES:
        sys.exit("usage: login_provider.py [{}]".format("|".join(HOMES)))

    provider = sys.argv[1]
    sessions = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "storage" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    target = sessions / "{}.json".format(provider)

    browser = cloakbrowser.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(HOMES[provider], wait_until="domcontentloaded")

    print("\nA browser window is open. Log in to {}, then press Enter here.".format(provider))
    try:
        input()
    except (EOFError, KeyboardInterrupt):
        print("cancelled")
        browser.close()
        return 1

    context.storage_state(path=str(target))
    browser.close()
    print("session saved to {}".format(target))
    return 0


if __name__ == "__main__":
    sys.exit(main())
