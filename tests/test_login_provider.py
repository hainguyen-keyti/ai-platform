#!/usr/bin/env python3
"""What the login script takes for a real sign-in, on a fake browser. No site, no account.

    ~/cloakbrowser-env/bin/python tests/test_login_provider.py

Measured 2026-10-01: chatgpt.com keeps its session cookie in chunks, `...session-token.0` and
`.1` (the names in the session saved on 2026-09-27), and the script waited for the plain name
only: the owner logged in, the script never saw it, and Ctrl+C lost the login.

The same day a state file saved by one browser and loaded by others cost two fresh logins, so the
login opens the provider's own profile, the one the drivers open, and saves nothing beside it.
A profile also keeps the cookie of a session its site has ended, so ChatGPT's login is real only once
the account answers. Prints N/8 PASSED.
"""

import contextlib
import importlib.util
import io
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src.providers.base import ProviderError  # noqa: E402

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


class LoginPage:
    url = "https://grok.com/"

    def goto(self, url, **kwargs):
        self.url = url

    def evaluate(self, script, *args):
        return 200


class LoggedIn(Context):
    """A browser in which the owner has just signed in to Grok."""

    def __init__(self):
        super().__init__(("sso", ".grok.com"), ("sso-rw", ".grok.com"))
        self.pages = [LoginPage()]
        self.closed = 0

    def new_page(self):
        return self.pages[0]

    def storage_state(self, path=None):
        Path(path).write_text("{}")

    def close(self):
        self.closed += 1


class OldWay:
    """What the script opened before: a browser with no profile, launched for the occasion."""

    def __init__(self, context, seen):
        self.context, self.seen = context, seen

    def launch(self, **kwargs):
        self.seen.append(("launch", (), kwargs))
        return self

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        self.context.closed += 1


def run_login(opener):
    """The script's own main for grok, on fakes: no window, no waiting. What it returned, said and left."""
    sessions = Path(tempfile.mkdtemp(prefix="login-provider-test-"))
    context, seen, said = LoggedIn(), [], io.StringIO()

    def open_session(*args, **kwargs):
        seen.append(("open_session", args, kwargs))
        return opener(context)

    kept = sys.argv, login.time.sleep, getattr(login, "cloakbrowser", None), getattr(login, "open_session", None)
    sys.argv, login.time.sleep = ["login_provider.py", "grok", str(sessions)], lambda seconds: None
    login.cloakbrowser, login.open_session = OldWay(context, seen), open_session
    try:
        with contextlib.redirect_stdout(said):
            code = login.main()
    except Exception as exc:
        code = "{}: {}".format(type(exc).__name__, str(exc)[:80])
    finally:
        sys.argv, login.time.sleep, login.cloakbrowser, login.open_session = kept
    return code, seen, context, sessions, said.getvalue()


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

    code, seen, context, sessions, said = run_login(lambda context: context)
    how = [call[0] for call in seen]
    args, kwargs = (seen[0][1], seen[0][2]) if seen else ((), {})
    record("the login opens the provider's own profile, with a window, and writes no state file",
           code == 0 and how == ["open_session"] and [str(a) for a in args[:2]] == [str(sessions), "grok"]
           and kwargs.get("headless") is False and kwargs.get("create") is True and context.closed == 1
           and not list(sessions.glob("*.json")),
           "returned {}, opened by {} with {} {}, closed {} time(s), state files {}".format(
               code, how, [str(a)[-28:] for a in args[:2]], kwargs, context.closed,
               sorted(f.name for f in sessions.glob("*.json"))))

    # A profile keeps its cookies, so a session the site has ended still shows its cookie when the owner
    # comes back to log in again; the account has to answer before the login is called real.
    class Answers:
        def __init__(self, status):
            self.status = status

        def evaluate(self, script, *args):
            return self.status

    live = Context(*anonymous, (SESSION + ".0", ".chatgpt.com"), (SESSION + ".1", ".chatgpt.com"))
    ended = login.signed_in(live, CHATGPT, Answers(401))
    alive = login.signed_in(live, CHATGPT, Answers(200))
    record("a session cookie the site no longer honours is not a sign-in", ended is None and bool(alive),
           "the account answering 401: {!r}; answering 200: {!r}".format(ended, alive))

    def in_use(context):
        raise ProviderError("the grok session is open in another browser: stop that one first")

    code, seen, context, sessions, said = run_login(in_use)
    record("a profile open elsewhere is said in words and the login gives up",
           code == 1 and [call[0] for call in seen] == ["open_session"] and "another browser" in said
           and context.closed == 0 and not list(sessions.iterdir()),
           "returned {}, opened by {}, said {!r}, left {}".format(
               code, [call[0] for call in seen], said.strip()[-70:], sorted(f.name for f in sessions.iterdir())))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
