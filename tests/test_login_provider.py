#!/usr/bin/env python3
"""What the login script takes for a real sign-in, on a fake browser. No site, no account.

    ~/cloakbrowser-env/bin/python tests/test_login_provider.py

Measured 2026-10-01: chatgpt.com keeps its session cookie in chunks, `...session-token.0` and
`.1` (the names in the session saved on 2026-09-27), and the script waited for the plain name
only: the owner logged in, the script never saw it, and Ctrl+C lost the login.

The same day a state file saved by one browser and loaded by others cost two fresh logins, so the
login opens the provider's own profile, the one the drivers open, and saves nothing beside it.
A profile also keeps the cookie of a session its site has ended: ChatGPT's login is real only once
the account answers, and Google's settings page, the proof that opens a tab, is not asked again
for the same cookie more than once a minute. Prints N/10 PASSED.
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
SETTINGS = login.PROVIDERS["gemini"]["proves_page"]

results = []


def record(name, ok, detail):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Clock:
    """The script's own clock: sleeping moves it, nothing waits."""

    def __init__(self):
        self.now = 1000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class Context:
    def __init__(self, *cookies):
        self.jar = [{"name": name, "domain": domain, "value": "SECRET-" + name} for name, domain in cookies]

    def cookies(self):
        return self.jar


class LoginPage:
    """The page the owner logs in on. Asked whether the account answers, it says what it was told to,
    and refuses an account read that does not carry the session's token, as the site does."""
    url = "https://grok.com/"

    def __init__(self, statuses=()):
        self.statuses, self.asked = list(statuses), []

    def goto(self, url, **kwargs):
        self.url = url

    def evaluate(self, script, *args):
        path = args[0] if args else ""
        with_token = "Authorization" in script
        self.asked.append(("token" if with_token else "plain", path))
        if path.startswith("/backend-api/") and not with_token:
            return 403
        return self.statuses.pop(0) if self.statuses else 200


class LoggedIn(Context):
    """A browser in which the owner has just signed in to Grok."""

    def __init__(self, statuses=()):
        super().__init__(("sso", ".grok.com"), ("sso-rw", ".grok.com"))
        self.pages = [LoginPage(statuses)]
        self.closed = 0

    def new_page(self):
        return self.pages[0]

    def storage_state(self, path=None):
        Path(path).write_text("{}")

    def close(self):
        self.closed += 1


class ProbeTab:
    """The tab the script opens on Google's settings page: it stays put only for an account."""

    def __init__(self, context):
        self.context, self.url = context, ""

    def goto(self, url, **kwargs):
        self.url = url if self.context.proves() else "https://gemini.google.com/saved-info"

    def wait_for_timeout(self, ms):
        self.context.clock.sleep(ms / 1000.0)

    def close(self):
        pass


class EndedThenLoggedIn(Context):
    """A Gemini profile that still holds the cookie of a session Google ended; the owner logs in again
    five minutes after the window opens. misses: how many times the settings page is still not the
    account's right after that login."""

    def __init__(self, clock, misses=0):
        super().__init__()
        self.clock, self.at, self.misses = clock, clock.now + 300, misses
        self.pages, self.closed, self.probes = [LoginPage()], 0, []

    def signed(self):
        return self.clock.now >= self.at

    def proves(self):
        if not self.signed():
            return False
        self.misses -= 1
        return self.misses < 0

    def cookies(self):
        return [{"name": "__Secure-1PSID", "domain": ".google.com", "value": "fresh" if self.signed() else "ended"}]

    def new_page(self):
        self.probes.append(self.clock.now)
        return ProbeTab(self)

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


def run_login(opener, provider="grok", context=None, clock=None):
    """The script's own main on fakes: no window, no waiting. What it returned, said and left."""
    sessions = Path(tempfile.mkdtemp(prefix="login-provider-test-"))
    context, clock = context or LoggedIn(), clock or Clock()
    seen, said = [], io.StringIO()

    def open_session(*args, **kwargs):
        seen.append(("open_session", args, kwargs))
        return opener(context)

    kept = (sys.argv, login.time.sleep, login.time.time, getattr(login, "cloakbrowser", None),
            getattr(login, "open_session", None))
    sys.argv = ["login_provider.py", provider, str(sessions)]
    login.time.sleep, login.time.time = clock.sleep, clock.time
    login.cloakbrowser, login.open_session = OldWay(context, seen), open_session
    try:
        with contextlib.redirect_stdout(said):
            code = login.main()
    except Exception as exc:
        code = "{}: {}".format(type(exc).__name__, str(exc)[:80])
    finally:
        sys.argv, login.time.sleep, login.time.time, login.cloakbrowser, login.open_session = kept
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
    record("the login opens the provider's own profile, with a window, writes no state file and prints no cookie value",
           code == 0 and how == ["open_session"] and [str(a) for a in args[:2]] == [str(sessions), "grok"]
           and kwargs.get("headless") is False and kwargs.get("create") is True and context.closed == 1
           and not list(sessions.glob("*.json")) and "SECRET" not in said and "sso" in said,
           "returned {}, opened by {} with {} {}, closed {} time(s), state files {}, a cookie value printed {}".format(
               code, how, [str(a)[-28:] for a in args[:2]], kwargs, context.closed,
               sorted(f.name for f in sessions.glob("*.json")), "SECRET" in said))

    waiting = LoggedIn(statuses=[401, 401, 200])
    code, seen, context, sessions, said = run_login(lambda context: context, context=waiting)
    asked = waiting.pages[0].asked
    record("the login waits until the account answers", code == 0 and len(asked) == 3 and waiting.closed == 1,
           "returned {}, asked the account {} time(s), closed {} time(s)".format(code, len(asked), waiting.closed))

    # A profile keeps its cookies, so a session the site has ended still shows its cookie when the owner
    # comes back to log in again; the account has to answer, asked with the session's own token.
    live = Context(*anonymous, (SESSION + ".0", ".chatgpt.com"), (SESSION + ".1", ".chatgpt.com"))
    ended = login.signed_in(live, CHATGPT, LoginPage([401]))
    page = LoginPage([200])
    alive = login.signed_in(live, CHATGPT, page)
    record("a session cookie the site no longer honours is not a sign-in",
           ended is None and bool(alive) and page.asked == [("token", "/backend-api/settings/user")],
           "the account answering 401: {!r}; answering 200: {!r}, asked {}".format(ended, alive, page.asked))

    def in_use(context):
        raise ProviderError("the grok session is open in another browser: stop that one first")

    code, seen, context, sessions, said = run_login(in_use)
    record("a profile open elsewhere is said in words and the login gives up",
           code == 1 and [call[0] for call in seen] == ["open_session"] and "another browser" in said
           and context.closed == 0 and not list(sessions.iterdir()),
           "returned {}, opened by {}, said {!r}, left {}".format(
               code, [call[0] for call in seen], said.strip()[-70:], sorted(f.name for f in sessions.iterdir())))

    # Google's proof opens a tab on its settings page. With an ended session's cookie still in the
    # profile that tab would open at every poll, in front of the owner, about a hundred times.
    clock = Clock()
    google = EndedThenLoggedIn(clock)
    code, seen, context, sessions, said = run_login(lambda context: context, "gemini", google, clock)
    before = [at for at in google.probes if at < google.at]
    after = [at for at in google.probes if at >= google.at]
    clock = Clock()
    slow = EndedThenLoggedIn(clock, misses=1)
    late, _, _, _, _ = run_login(lambda context: context, "gemini", slow, clock)
    again = [at for at in slow.probes if at >= slow.at]
    record("a cookie already there is not proved more than once a minute, and the new login ends at its next poll",
           code == 0 and 1 <= len(before) <= 6 and len(after) == 1 and after[0] - google.at <= 9
           and google.closed == 1 and SETTINGS.split("://", 1)[-1] in said
           and late == 0 and len(again) == 2 and 60 <= again[1] - again[0] <= 75,
           "returned {}; in the 300s before the login the settings tab opened {} time(s); after it {} time(s), {}s "
           "after the cookie changed; a first proof that missed was asked again {}s later (returned {})".format(
               code, len(before), len(after), round(after[0] - google.at, 1) if after else "never",
               round(again[1] - again[0], 1) if len(again) > 1 else "never", late))

    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
