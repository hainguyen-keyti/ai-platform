#!/usr/bin/env python3
"""The nightly cleanup of ChatGPT's Library (issue #27), measured without a browser or an api.

    ~/cloakbrowser-env/bin/python tests/test_library_cleanup.py

The fake page answers as the real one did on 2026-10-30: POST /backend-api/files/library gives
{items, cursor}, 50 a page, each item with id, file_size_bytes, record_creation_time,
origination_thread_id, access_kind, library_file_category, state and trashed_at;
DELETE .../files/library/files/{id}?soft_delete=true answers {success: true}, moves the file to the
trash and frees its bytes at once. Only pictures from before today, in threads the platform knows, go.
Prints N/N PASSED.
"""

import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

from src import pool as pool_module  # noqa: E402
from src import runner as runner_module  # noqa: E402
from src.providers import chatgpt  # noqa: E402
from src.providers.base import ProviderError  # noqa: E402

OURS, ALIEN = "6ae41b33-e478-83ec-99e1-220272782328", "68d11111-aaaa-83ec-bbbb-000000000000"
TODAY = "2026-10-30"
results = []


def record(name, ok, detail=""):
    results.append(ok)
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


def item(ident, thread=OURS, day="2026-10-29", category="image", size=1000, trashed=None, access="owned"):
    return {"id": ident, "file_id": "file_" + ident, "file_name": ident + ".png", "file_size_bytes": size,
            "record_creation_time": day + "T07:21:19.529208Z", "file_upload_time": day + "T07:21:19Z",
            "origination_thread_id": thread, "access_kind": access, "library_file_category": category,
            "state": "ready", "trashed_at": trashed}


class Page:
    url = chatgpt.HOME

    def __init__(self, pages, refuse=(), list_status=200):
        self.pages, self.refuse, self.list_status = pages, set(refuse), list_status
        self.trashed, self.asked, self.goto_calls = [], [], 0

    def goto(self, url, **kwargs):
        self.goto_calls += 1

    def wait_for_timeout(self, ms):
        pass

    def evaluate(self, script, args=None):
        if script == chatgpt.SESSION_TOKEN:
            return "token"
        if script == chatgpt.FETCH_LIBRARY_PAGE:
            self.asked.append(args[1])
            if self.list_status != 200:
                return {"status": self.list_status}
            return dict(self.pages[args[1]], status=200)
        if script == chatgpt.TRASH_LIBRARY_FILE:
            if args[1] in self.refuse:
                return {"status": 500}
            self.trashed.append(args[1])
            return {"status": 200, "body": {"success": True}}
        raise AssertionError("an unexpected script")


def driver_on(page):
    driver = chatgpt.ChatGPTProvider(Path("/tmp/library-cleanup-test"), ROOT / "storage" / "sessions")
    driver._page = page
    driver._ensure_page = lambda: page
    driver._access_token = "token"
    return driver


def known_threads(urls):
    known.append(list(urls))
    return {url for url in urls if url.endswith(OURS)}


known = []


def driver_cases():
    page = Page({None: {"items": [
        item("old-ours", size=2303752),
        item("today-ours", day=TODAY),
        item("old-alien", thread=ALIEN),
        item("no-thread", thread=None),
        item("a-text", category="text"),
        item("trashed", trashed="2026-10-29T08:00:15Z"),
        item("shared", access="shared"),
        item("no-time", day=""),
    ], "cursor": "page-2"}})
    known.clear()
    got = driver_on(page).clean_library_page(None, TODAY, known_threads)
    record("only a picture from before today, in a thread the platform knows, is moved to the trash",
           page.trashed == ["old-ours"], repr(page.trashed))
    record("the page's report counts what went, its bytes, and the next page",
           got["removed"] == 1 and got["bytes"] == 2303752 and got["failed"] == [] and got["cursor"] == "page-2",
           repr(got))
    record("what is not the platform's is counted as kept",
           got["not_ours"] == 1, repr(got))
    record("the api is asked about whole thread addresses, and only for pictures that could go",
           known == [["{}c/{}".format(chatgpt.HOME, OURS), "{}c/{}".format(chatgpt.HOME, ALIEN)]]
           or sorted(known[0]) == sorted(["{}c/{}".format(chatgpt.HOME, OURS), "{}c/{}".format(chatgpt.HOME, ALIEN)]),
           repr(known))

    page = Page({"page-2": {"items": [item("one"), item("two"), item("three")], "cursor": None}}, refuse=["two"])
    got = driver_on(page).clean_library_page("page-2", TODAY, known_threads)
    record("a file that cannot be moved is reported and does not stop the rest",
           page.trashed == ["one", "three"] and got["removed"] == 2 and got["failed"] == [("two", 500)]
           and got["cursor"] is None and page.asked == ["page-2"], repr(got))

    record("the call only ever moves to the trash, never deletes for good",
           "soft_delete=true" in chatgpt.TRASH_LIBRARY_FILE and "soft_delete=false" not in chatgpt.TRASH_LIBRARY_FILE,
           chatgpt.TRASH_LIBRARY_FILE.split("fetch(", 1)[-1][:90])

    page = Page({None: {"items": [], "cursor": None}}, list_status=403)
    try:
        driver_on(page).clean_library_page(None, TODAY, known_threads)
        outcome = "no error"
    except ProviderError as exc:
        outcome = str(exc)
    record("a list that cannot be read is an error naming its status, and nothing is moved",
           "403" in outcome and page.trashed == [], outcome)


class Response:
    def __init__(self, status, body=None):
        self.status_code, self.body = status, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("status {}".format(self.status_code))

    def json(self):
        return self.body


class Client:
    def __init__(self, answer=None):
        self.answer, self.posts = answer, []

    def post(self, path, json=None):
        self.posts.append((path, json))
        return Response(200, self.answer)


class Pool:
    """Plays pages: each call answers the next page of the run."""

    def __init__(self, steps=(), can=True):
        self.steps, self.can, self.calls = list(steps), can, []

    def can_clean_library(self, provider):
        return self.can

    def clean_library_page(self, provider, cursor, day, known):
        self.calls.append((provider, cursor, day))
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


def step(removed=1, cursor=None):
    return {"removed": removed, "bytes": 10 * removed, "failed": [], "not_ours": 0, "cursor": cursor}


def runner_at(pool, moments, at="16:30"):
    runner_module.settings.library_cleanup_at = at
    runner = runner_module.Runner(pool, "chatgpt")
    clock = iter(moments)
    runner._utcnow = lambda: next(clock)
    return runner


def utc(day, hour, minute=0):
    from datetime import datetime, timezone
    year, month, date = (int(p) for p in day.split("-"))
    return datetime(year, month, date, hour, minute, tzinfo=timezone.utc)


def runner_cases():
    client = Client()
    pool = Pool([step(cursor="p2"), step(removed=2)])
    runner = runner_at(pool, [utc(TODAY, 16, 29), utc(TODAY, 16, 30), utc(TODAY, 16, 31), utc(TODAY, 16, 32)])
    runner._maybe_clean_library(client)
    before = list(pool.calls)
    runner._maybe_clean_library(client)
    first = list(pool.calls)
    runner._maybe_clean_library(client)
    both = list(pool.calls)
    runner._maybe_clean_library(client)
    record("nothing before its time; then one page each idle tick, following the cursor; then done for the day",
           before == [] and first == [("chatgpt", None, TODAY)]
           and both == first + [("chatgpt", "p2", TODAY)] and pool.calls == both,
           repr(pool.calls))
    shown = runner.snapshot()["library_cleanup"]
    record("health shows the run: its day, what went, and that it finished",
           shown["day"] == TODAY and shown["removed"] == 3 and shown["bytes"] == 30 and shown["running"] is False,
           repr(shown))

    pool = Pool([step(), step()])
    runner = runner_at(pool, [utc(TODAY, 17), utc("2026-10-31", 3), utc("2026-10-31", 16, 40)])
    runner._maybe_clean_library(Client())
    runner._maybe_clean_library(Client())
    runner._maybe_clean_library(Client())
    record("the next run is the next day, at its time",
           [c[2] for c in pool.calls] == [TODAY, "2026-10-31"], repr(pool.calls))

    pool = Pool([ProviderError("chatgpt's library could not be read (403)"), step()])
    runner = runner_at(pool, [utc(TODAY, 17), utc(TODAY, 18)])
    runner._maybe_clean_library(Client())
    runner._maybe_clean_library(Client())
    record("a failed page ends the run for the day and says why",
           len(pool.calls) == 1 and "403" in (runner.last_error or "")
           and "403" in (runner.snapshot()["library_cleanup"].get("error") or ""), repr(runner.last_error))

    pool = Pool([step()])
    runner = runner_at(pool, [utc(TODAY, 17)], at="")
    runner._maybe_clean_library(Client())
    record("an empty LIBRARY_CLEANUP_AT turns it off", pool.calls == [], repr(pool.calls))

    pool = Pool([step()], can=False)
    runner = runner_at(pool, [utc(TODAY, 17)])
    runner._maybe_clean_library(Client())
    record("a provider with no Library is never asked", pool.calls == [], repr(pool.calls))

    client = Client({"known": ["https://chatgpt.com/c/" + OURS]})
    runner = runner_at(Pool(), [])
    got = runner._known_threads(client, ["https://chatgpt.com/c/" + OURS, "https://chatgpt.com/c/" + ALIEN])
    record("the runner asks the api which threads are the platform's, for its own provider",
           got == {"https://chatgpt.com/c/" + OURS} and client.posts[0][0] == "/internal/threads/known"
           and client.posts[0][1]["provider"] == "chatgpt" and len(client.posts[0][1]["thread_urls"]) == 2,
           repr(client.posts))


def pool_cases():
    pool = pool_module.BrowserPool()
    held = []

    class Provider:
        def clean_library_page(self, cursor, day, known):
            held.append(lock.locked())
            return {"cursor": None}

    lock = threading.Lock()
    pool._providers["chatgpt"], pool._locks["chatgpt"] = Provider(), lock
    pool._providers["grok"], pool._locks["grok"] = object(), threading.Lock()
    pool.clean_library_page("chatgpt", None, TODAY, known_threads)
    record("a page is cleaned under the provider's lock, so it never meets a turn", held == [True], repr(held))
    record("only a provider whose driver has a Library can be cleaned",
           pool.can_clean_library("chatgpt") and not pool.can_clean_library("grok")
           and not pool.can_clean_library("gemini"), "")


def main():
    driver_cases()
    runner_cases()
    pool_cases()
    passed = sum(1 for ok in results if ok)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if results and passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
