#!/usr/bin/env python3
"""Open a real browser so a provider can be logged in by hand, then save the session.

    ~/cloakbrowser-env/bin/python scripts/login_provider.py grok

A window opens on the provider's own site. Log in there. The script watches the
browser and saves the session by itself the moment the login is real, so there
is no terminal step to get wrong, and it refuses to save a session that is not
logged in. It prints cookie names and domains, never values.
"""

import sys
import time
from pathlib import Path

import cloakbrowser

ROOT = Path(__file__).resolve().parent.parent

# Where to land, and the cookie that only exists once the login is real. A
# provider that redirects (x.com/i/grok sends you to grok.com) must be opened at
# its own site, or the saved session carries the wrong domain's cookies: that is
# exactly how one login was lost on 2026-09-24.
PROVIDERS = {
    "chatgpt": {
        "home": "https://chatgpt.com/",
        "domain": "chatgpt.com",
        "cookies": ("__Secure-next-auth.session-token",),
    },
    "grok": {
        "home": "https://grok.com/",
        "domain": "grok.com",
        "cookies": ("sso", "sso-rw"),
    },
    "gemini": {
        "home": "https://gemini.google.com/",
        "domain": "google.com",
        "cookies": ("__Secure-1PSID",),
    },
}

WAIT_MINUTES = 15
POLL_SECONDS = 3


def signed_in(context, spec):
    """The provider's own session cookie, on the provider's own domain."""
    for cookie in context.cookies():
        if spec["domain"] in cookie.get("domain", "") and cookie.get("name") in spec["cookies"]:
            return cookie["name"]
    return None


def summarise(context, spec):
    counts = {}
    names = set()
    for cookie in context.cookies():
        domain = cookie.get("domain", "?")
        counts[domain] = counts.get(domain, 0) + 1
        if spec["domain"] in domain:
            names.add(cookie.get("name", "?"))
    return counts, sorted(names)


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in PROVIDERS:
        sys.exit("usage: login_provider.py [{}]".format("|".join(PROVIDERS)))

    provider = sys.argv[1]
    spec = PROVIDERS[provider]
    sessions = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / "storage" / "sessions"
    sessions.mkdir(parents=True, exist_ok=True)
    target = sessions / "{}.json".format(provider)

    browser = cloakbrowser.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    page.goto(spec["home"], wait_until="domcontentloaded", timeout=90000)

    print("\nA browser window is open at {}.".format(spec["home"]))
    print("Log in there. Stay on that site; do not navigate to another one.")
    print("This script saves the session by itself once the login is real, then closes.")
    print("Waiting up to {} minutes...\n".format(WAIT_MINUTES))

    deadline = time.time() + WAIT_MINUTES * 60
    found = None
    try:
        while time.time() < deadline:
            try:
                found = signed_in(context, spec)
            except Exception:
                print("the browser window was closed before the login finished")
                return 1
            if found:
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("cancelled")
        browser.close()
        return 1

    if not found:
        counts, names = summarise(context, spec)
        print("no {} session after {} minutes; nothing was saved".format(provider, WAIT_MINUTES))
        print("cookies seen by domain: {}".format(counts))
        print("cookie names on {}: {}".format(spec["domain"], names or "none"))
        browser.close()
        return 1

    # A moment for the site to finish writing whatever it writes after sign-in.
    time.sleep(5)
    context.storage_state(path=str(target))
    counts, names = summarise(context, spec)
    browser.close()

    print("signed in ({} cookie present)".format(found))
    print("session saved to {}".format(target))
    print("cookies by domain: {}".format(counts))
    print("cookie names on {}: {}".format(spec["domain"], names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
