#!/usr/bin/env python3
"""What the login script takes for a real sign-in, on a fake browser. No site, no account.

    ~/cloakbrowser-env/bin/python tests/test_login_provider.py

Measured 2026-10-01: chatgpt.com keeps its session cookie in chunks, `...session-token.0` and
`.1` (the names in the session saved on 2026-09-27), and the script waited for the plain name
only: the owner logged in, the script never saw it, and Ctrl+C lost the login. Prints N/5 PASSED.
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("login_provider", ROOT / "scripts" / "login_provider.py")
login = importlib.util.module_from_spec(spec)
spec.loader.exec_module(login)

SESSION = "__Secure-next-auth.session-token"
CHATGPT = login.PROVIDERS["chatgpt"]
# Gemini's cookie without its settings page proof, which needs a real tab.
GOOGLE = {"domain": "google.com", "cookies": login.PROVIDERS["gemini"]["cookies"]}

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Context:
    def __init__(self, *cookies):
        self.jar = [{"name": name, "domain": domain} for name, domain in cookies]

    def cookies(self):
        return self.jar


def main():
    anonymous = (("__Host-next-auth.csrf-token", "chatgpt.com"), ("__Secure-next-auth.callback-url", "chatgpt.com"))

    found = login.signed_in(Context(*anonymous, (SESSION + ".0", ".chatgpt.com"), (SESSION + ".1", ".chatgpt.com")),
                            CHATGPT)
    record("a session cookie kept in chunks is a sign-in", bool(found) and found.startswith(SESSION),
           "found {!r}".format(found))

    found = login.signed_in(Context(*anonymous, (SESSION, ".chatgpt.com")), CHATGPT)
    record("the plain session cookie still is", found == SESSION, "found {!r}".format(found))

    found = login.signed_in(Context(*anonymous), CHATGPT)
    record("a page with no session cookie is not saved", found is None, "found {!r}".format(found))

    found = login.signed_in(Context(*anonymous, (SESSION + ".0", ".example.com")), CHATGPT)
    record("a session cookie of another site does not count", found is None, "found {!r}".format(found))

    # A chunk is the name, a dot and a number; a longer name that only starts the same is another cookie.
    lookalikes = (("__Secure-1PSIDTS", ".google.com"), ("__Secure-1PSIDCC", ".google.com"),
                  (SESSION + ".old", ".chatgpt.com"), (SESSION + "-backup", ".chatgpt.com"))
    google = login.signed_in(Context(*lookalikes), GOOGLE)
    chatgpt = login.signed_in(Context(*anonymous, *lookalikes), CHATGPT)
    record("a cookie whose name only starts the same does not count", google is None and chatgpt is None,
           "google {!r}, chatgpt {!r}".format(google, chatgpt))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
