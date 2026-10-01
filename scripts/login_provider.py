#!/usr/bin/env python3
"""Open the provider's own browser so it can be logged in by hand; the session stays in its profile.

    ~/cloakbrowser-env/bin/python scripts/login_provider.py grok

A window opens on the provider's own site, in the profile the worker opens afterwards
(storage/sessions/<provider>/) and as the same device. Log in there. The script watches the
browser and closes it by itself the moment the login is real, so there is no terminal step to
get wrong, and it does not call a session real that is not logged in. Take the provider off the
host worker first: a profile opens in one browser at a time. It prints cookie names and
domains, never values.
"""

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.base import ProviderError  # noqa: E402
from src.providers.session import open_session, profile_of  # noqa: E402

# Where to land, and the cookie that only exists once the login is real. A
# provider that redirects (x.com/i/grok sends you to grok.com) must be opened at
# its own site, or the saved session carries the wrong domain's cookies: that is
# exactly how one login was lost on 2026-09-24.
PROVIDERS = {
    "chatgpt": {
        "home": "https://chatgpt.com/",
        "domain": "chatgpt.com",
        "cookies": ("__Secure-next-auth.session-token",),
        # A profile keeps the cookie of a session the site has ended (2026-10-01: "the provider
        # rejected a fresh session token"), so the account itself has to answer.
        "proves_token": "/backend-api/settings/user",
    },
    "grok": {
        "home": "https://grok.com/",
        "domain": "grok.com",
        "cookies": ("sso", "sso-rw"),
        # The cookie only says a session exists; this says the account answers.
        "proves_it": "/rest/app-chat/conversations?pageSize=1",
    },
    "gemini": {
        "home": "https://gemini.google.com/",
        "domain": "google.com",
        "cookies": ("__Secure-1PSID",),
        # Measured 2026-09-27: every gemini path answers 200 signed out too, so no
        # status can prove anything. The account's own settings page stays put for an
        # account and sends anyone else to /saved-info.
        "proves_page": "https://gemini.google.com/personalization-settings",
    },
}

WAIT_MINUTES = 15
POLL_SECONDS = 3
PROOF_AGAIN_SECONDS = 60


ASK = """
async (path) => {
    try {
        const r = await fetch(path, {credentials: 'include'});
        return r.status;
    } catch (e) { return 0; }
}
"""

# The same question for a site whose account is read with the session's own token. The token is
# asked for and used inside the page and never leaves it.
ASK_WITH_TOKEN = """
async (path) => {
    try {
        const token = (await (await fetch('/api/auth/session')).json()).accessToken;
        if (!token) return 0;
        const r = await fetch(path, {headers: {Authorization: 'Bearer ' + token}, credentials: 'include'});
        return r.status;
    } catch (e) { return 0; }
}
"""


def is_cookie(name, wanted):
    """The cookie itself, or one chunk of it: a long session cookie is kept as name.0, name.1.

    Measured 2026-10-01: chatgpt.com's session cookie exists only in chunks, and waiting for the
    plain name never ended although the login was real.
    """
    return name == wanted or (name.startswith(wanted + ".") and name[len(wanted) + 1:].isdigit())


def signed_in(context, spec, page=None, asked=None):
    """The provider's own session cookie, and where possible its own answer.

    A cookie can be present on a page that is not really signed in, which is how
    one login was lost on 2026-09-24. When the provider offers an endpoint that
    only an account can read, that is what decides.

    asked remembers, per cookie as it is now, when its settings page last failed to stay: a profile
    keeps the cookie of a session the site has ended, and the page proof opens a tab, so the same
    cookie is not proved again within PROOF_AGAIN_SECONDS. A new login changes the cookie.
    """
    found = mark = None
    for cookie in context.cookies():
        name = cookie.get("name", "")
        if spec["domain"] in cookie.get("domain", "") and any(is_cookie(name, w) for w in spec["cookies"]):
            found, mark = name, hash((name, cookie.get("value")))
            break
    if not found:
        return None
    landing = spec.get("proves_page")
    if landing:
        if asked is not None and time.time() - asked.get(mark, float("-inf")) < PROOF_AGAIN_SECONDS:
            return None
        if page_stays(context, landing):
            return "{} and {} stayed put".format(found, landing)
        if asked is not None:
            asked[mark] = time.time()
        return None
    for kind, ask in (("proves_it", ASK), ("proves_token", ASK_WITH_TOKEN)):
        proof = spec.get(kind)
        if proof and page is not None:
            try:
                if page.evaluate(ask, proof) != 200:
                    return None
            except Exception:
                return None
            return "{} and {} answered".format(found, proof.split("?")[0])
    return found


def page_stays(context, url):
    """Open url in a tab of its own and say whether it stayed on its own path.

    A tab of its own, so the window the person is signing in with is never moved.
    """
    wanted = url.split("://", 1)[-1].split("/", 1)[-1]
    probe = context.new_page()
    try:
        probe.goto(url, wait_until="domcontentloaded", timeout=60000)
        probe.wait_for_timeout(6000)
        landed = probe.url.split("://", 1)[-1].split("/", 1)[-1].split("?")[0]
        return landed.rstrip("/") == wanted.rstrip("/")
    except Exception:
        return False
    finally:
        probe.close()


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

    try:
        context = open_session(sessions, provider, headless=False, create=True)
    except ProviderError as exc:
        print(exc)
        return 1
    page = context.pages[0] if context.pages else context.new_page()
    page.goto(spec["home"], wait_until="domcontentloaded", timeout=90000)

    print("\nA browser window is open at {}.".format(spec["home"]))
    print("Log in there. Stay on that site; do not navigate to another one.")
    print("This script closes the window by itself once the login is real; the session stays in its profile.")
    print("Waiting up to {} minutes...\n".format(WAIT_MINUTES))

    deadline = time.time() + WAIT_MINUTES * 60
    found, asked = None, {}
    try:
        while time.time() < deadline:
            try:
                found = signed_in(context, spec, page, asked)
            except Exception:
                print("the browser window was closed before the login finished")
                context.close()
                return 1
            if found:
                break
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("cancelled")
        context.close()
        return 1
    except Exception as exc:
        print("stopped: {}: {}".format(type(exc).__name__, str(exc)[:120]))
        context.close()
        return 1

    if not found:
        counts, names = summarise(context, spec)
        print("no {} session after {} minutes".format(provider, WAIT_MINUTES))
        print("cookies seen by domain: {}".format(counts))
        print("cookie names on {}: {}".format(spec["domain"], names or "none"))
        context.close()
        return 1

    # A moment for the site to finish writing whatever it writes after sign-in.
    time.sleep(5)
    counts, names = summarise(context, spec)
    context.close()

    print("signed in ({} cookie present)".format(found))
    print("session saved to {}".format(profile_of(sessions, provider)))
    print("cookies by domain: {}".format(counts))
    print("cookie names on {}: {}".format(spec["domain"], names))
    return 0


if __name__ == "__main__":
    sys.exit(main())
