#!/usr/bin/env python3
"""The paths a job takes through the pool and the runner when something goes wrong, without a browser or an api.

    ~/cloakbrowser-env/bin/python tests/test_worker_paths.py

A fake provider and a fake client stand in; the pool and the runner are the real ones. What a browser that
dies does is in test_pool_dead_browser.py, what a busy runner says in test_runner_liveness.py, the nightly
cleanup in test_library_cleanup.py. Prints N/N PASSED.
"""

import socket
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))

import httpx  # noqa: E402
from playwright._impl._errors import TargetClosedError  # noqa: E402

from src import pool as pool_module, runner as runner_module  # noqa: E402
from src.config import settings  # noqa: E402
from src.pool import BrowserPool, ProviderHealth  # noqa: E402
from src.providers import session  # noqa: E402
from src.providers.base import FeatureType, GenerationResult, JobCancelled, MediaArtifact, ProviderError  # noqa: E402

results = []
real_httpx_client = httpx.Client


def record(name, ok, detail=""):
    results.append(bool(ok))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Provider:
    """Does what it is told, and keeps what it was asked."""

    name = "chatgpt"
    supported_features = {FeatureType.CHAT, FeatureType.IMAGE, FeatureType.VIDEO_SCRIPT}

    def __init__(self, raises=None, result=None, features=("chat", "image", "video_script"), hold=0.0):
        self.raises, self.features, self.hold = raises, features, hold
        self.result = result or GenerationResult(success=True, text="ok")
        self.asked, self.bound, self.stops = [], [], 0
        self.inside = self.most_inside = 0
        self.last_cancelled_thread = None

    def supports(self, feature):
        return feature in self.features

    def start(self):
        return None

    def bind(self, phase_hook=None, stop_hook=None):
        self.bound.append((phase_hook, stop_hook))

    def _turn(self, *asked):
        self.asked.append(asked)
        self.inside += 1
        self.most_inside = max(self.most_inside, self.inside)
        time.sleep(self.hold)
        self.inside -= 1
        if self.raises is not None:
            raise self.raises
        return self.result

    def chat(self, message, history=None, thread_url=None):
        return self._turn("chat", message, thread_url)

    def generate_image(self, prompt, reference=None, thread_url=None):
        return self._turn("image", prompt, reference, thread_url)

    def generate_video_script(self, filename, duration, thread_url=None):
        return self._turn("video", filename, duration, thread_url)

    def clean_library_page(self, cursor, day, known):
        return self._turn("clean", cursor, day)

    def stop(self):
        self.stops += 1


def pool_with(provider, name="chatgpt"):
    pool = BrowserPool()
    pool._providers[name] = provider
    pool._locks[name] = threading.Lock()
    pool._health.setdefault(name, ProviderHealth(name))
    return pool


class Response:
    def __init__(self, status=200, body=None):
        self.status_code, self.body = status, body or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("status {}".format(self.status_code))

    def json(self):
        return self.body


class Client:
    """Stands in for httpx.Client: answers by the part of the path, an exception being raised."""

    def __init__(self, answers=None):
        self.answers, self.calls = answers or {}, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, path, json=None):
        self.calls.append((path, json))
        for part, answer in self.answers.items():
            if part in path:
                # A list answers in turn, its last for good.
                if isinstance(answer, list):
                    answer = answer.pop(0) if len(answer) > 1 else answer[0]
                if isinstance(answer, Exception):
                    raise answer
                return answer
        return Response(200)

    def to(self, part):
        return [body for path, body in self.calls if part in path]


class Pool:
    """The pool as the runner sees it, for the runner's own paths."""

    def __init__(self, result=None, hold=0.0, cooling=False, deletion=None, raises=None, stones=None):
        self.result = result or GenerationResult(success=True, text="ok")
        self.hold, self.cooling, self.deletion, self.raises = hold, cooling, deletion, raises
        self.executed, self.noted, self.deleted = [], [], []
        self.on_hold = None

    def hold_seconds(self, provider):
        if self.on_hold:
            self.on_hold()
        return self.hold

    def cooling_down(self, provider):
        return self.cooling

    def pacing_report(self, provider):
        return {"images_last_3h": 3, "image_budget": 40, "budget_free_in": 0}

    def can_clean_library(self, provider):
        return False

    def close_idle(self, account):
        pass

    def stands_aside(self, account):
        return False

    def execute(self, provider, feature, payload, thread_url, phase_hook, should_stop):
        self.executed.append((provider, feature, payload, thread_url))
        if self.raises is not None:
            raise self.raises
        return self.result

    def note_result(self, provider, result, seconds):
        self.noted.append(result)

    def delete_thread(self, provider, url):
        self.deleted.append(url)
        return self.deletion or GenerationResult(success=True)


JOB = {"id": "job-1", "attempt": 1, "feature": "image", "provider": "chatgpt", "payload": {"prompt": "p"},
       "thread_url": "https://chatgpt.com/c/1", "lease_seconds": 420}
STONE = {"id": "stone-1", "provider": "chatgpt", "thread_url": "https://chatgpt.com/c/2"}


def turns(runner, client, count):
    """The runner's real loop, for this many times round, on the fake client."""
    seen = {"n": 0}
    earlier = runner.pool.on_hold

    def counted():
        if earlier:
            earlier()
        seen["n"] += 1
        if seen["n"] >= count:
            runner.stop()
    runner.pool.on_hold = counted
    runner_module.httpx.Client = lambda **kwargs: client
    runner.run()


def pool_answers():
    # Nothing to run: every failure below comes back as the kind that decides cooldown and refund.
    empty = BrowserPool()
    result = empty.execute("nobody", "chat", {})
    record("a provider not on this worker is a provider error that says so",
           not result.success and result.error_kind == "provider_error" and "not enabled" in result.error,
           "{} {!r}".format(result.error_kind, result.error))

    empty._errors["nobody"] = "RuntimeError: no profile"
    result = empty.execute("nobody", "chat", {})
    record("a provider that failed to start names why", "no profile" in result.error, repr(result.error))

    result = empty.delete_thread("nobody", "https://x")
    record("a deletion for a provider not here is a provider error, not a crash",
           result.error_kind == "provider_error", str(result.error_kind))

    provider = Provider(features=("chat",))
    result = pool_with(provider).execute("chatgpt", "image", {"prompt": "p"})
    record("a feature the provider lacks is a worker error and no turn", result.error_kind == "worker_error"
           and not provider.asked and not provider.bound, "{} asked {}".format(result.error_kind, provider.asked))

    provider = Provider(features=("telepathy",))
    result = pool_with(provider).execute("chatgpt", "telepathy", {})
    record("a feature nobody drives is a worker error", result.error_kind == "worker_error"
           and "unknown feature" in result.error, repr(result.error))

    provider = Provider(raises=ProviderError("the site said no", kind="provider_misconfigured"))
    result = pool_with(provider).execute("chatgpt", "chat", {"message": "m"})
    record("a provider's error keeps its own kind and words",
           result.error_kind == "provider_misconfigured" and result.error == "the site said no",
           "{} {!r}".format(result.error_kind, result.error))

    provider = Provider(raises=JobCancelled())
    provider.last_cancelled_thread = "https://chatgpt.com/c/kept"
    result = pool_with(provider).execute("chatgpt", "chat", {"message": "m"})
    record("a cancelled turn reports the thread it landed in, for the api to keep or remove",
           result.error_kind == "cancelled" and result.thread_url == "https://chatgpt.com/c/kept"
           and provider.stops == 0, "{} {}".format(result.error_kind, result.thread_url))

    provider = Provider(raises=RuntimeError("a driver bug"))
    pool_with(provider).execute("chatgpt", "chat", {"message": "m"}, None, print, bool)
    record("the job's hooks are let go of even when the turn raises",
           provider.bound[0] == (print, bool) and provider.bound[-1] == (None, None), str(provider.bound))

    provider = Provider()
    pool = pool_with(provider)
    pool.execute("chatgpt", "image", {"prompt": "p", "reference_filename": "one.png"}, "t")
    pool.execute("chatgpt", "image", {"prompt": "p", "reference_filename": "one.png",
                                      "reference_filenames": ["a.png", "b.png"]}, "t")
    pool.execute("chatgpt", "video_script", {"filename": "v.mp4", "duration": "7"})
    record("a picture gets its references, several before one, and a video its duration as a number",
           provider.asked == [("image", "p", "one.png", "t"), ("image", "p", ["a.png", "b.png"], "t"),
                              ("video", "v.mp4", 7, None)], str(provider.asked))

    provider = Provider(hold=0.15)
    pool = pool_with(provider)
    workers = [threading.Thread(target=pool.execute, args=("chatgpt", "chat", {"message": str(n)})) for n in range(4)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    record("two jobs never share a provider's page", provider.most_inside == 1 and len(provider.asked) == 4,
           "at most {} inside, {} turns".format(provider.most_inside, len(provider.asked)))

    provider = Provider(raises=TargetClosedError())
    pool = pool_with(provider)
    try:
        pool.clean_library_page("chatgpt", None, "2026-10-31", set)
        said = "returned"
    except TargetClosedError:
        said = "raised"
    record("a browser that dies under the cleanup is dropped, and the run told", said == "raised" and provider.stops == 1,
           "{} stops {}".format(said, provider.stops))

    provider = Provider(raises=RuntimeError("the list could not be read"))
    pool = pool_with(provider)
    try:
        pool.clean_library_page("chatgpt", None, "2026-10-31", set)
        said = "returned"
    except RuntimeError:
        said = "raised"
    record("any other failure of the cleanup keeps the browser", said == "raised" and provider.stops == 0,
           "{} stops {}".format(said, provider.stops))
    record("only a driver with a Library is cleaned", pool.can_clean_library("chatgpt")
           and not pool.can_clean_library("grok"))

    class Refuses(Provider):
        def stop(self):
            raise RuntimeError("the browser was already gone")
    pool = pool_with(Refuses())
    pool.stop()
    record("a browser that will not stop does not stop the shutdown", pool._providers == {})

    built = pool_module.build_provider
    settings.providers = ["chatgpt", "grok"]

    def build(name, account=None):
        if name == "grok":
            raise RuntimeError("no profile for grok")
        return Provider()
    pool_module.build_provider = build
    pool = BrowserPool()
    pool.start()
    status = pool.status()
    record("one provider that cannot start leaves the others served",
           status["chatgpt"]["ready"] and not status["grok"]["ready"] and "no profile" in status["grok"]["error"],
           str({n: (s["ready"], s["error"]) for n, s in status.items()}))
    pool_module.build_provider = built

    # Issue #29: an account that cannot start leaves the work to the others of its provider.
    pool = BrowserPool()
    pool._provider_of = {"chatgpt": "chatgpt", "chatgpt-b": "chatgpt", "grok": "grok"}
    pool._providers = {"chatgpt": Provider()}
    pool._errors = {"chatgpt-b": "RuntimeError: no profile", "grok": "RuntimeError: no profile"}
    record("an account that could not start stands aside while another of its provider can serve",
           pool.stands_aside("chatgpt-b") and not pool.stands_aside("chatgpt"))
    record("the only account of a provider does not, so its job says why it failed", not pool.stands_aside("grok"))
    del pool._providers["chatgpt"]
    record("nor does one whose fellows could not start either", not pool.stands_aside("chatgpt-b"))
    settings.providers = ["chatgpt"]

    # Issue #29: every account's browser held open is memory the machine is short of.
    provider = Provider()
    pool = pool_with(provider)
    settings.browser_idle_seconds = 0.2
    pool.execute("chatgpt", "chat", {"message": "m"})
    pool.close_idle("chatgpt")
    record("a browser just used stays open", provider.stops == 0)
    time.sleep(0.3)
    pool.close_idle("chatgpt")
    pool.close_idle("chatgpt")
    record("a browser idle long enough is closed, once", provider.stops == 1, "stops {}".format(provider.stops))
    pool.execute("chatgpt", "chat", {"message": "m"})
    time.sleep(0.3)
    with pool._locks["chatgpt"]:
        pool.close_idle("chatgpt")
    record("a browser in use is not closed", provider.stops == 1, "stops {}".format(provider.stops))
    settings.browser_idle_seconds = 0
    time.sleep(0.1)
    pool.close_idle("chatgpt")
    record("no limit, no closing", provider.stops == 1, "stops {}".format(provider.stops))
    settings.browser_idle_seconds = 1800

    profiles = Path(tempfile.mkdtemp(prefix="worker-accounts-", dir=str(Path.home() / ".cache")))
    for name, seeded in (("chatgpt", True), ("chatgpt-a2", True), ("chatgpt-empty", False), ("chatgptish", True), ("grok-x", True)):
        (profiles / name).mkdir()
        if seeded:
            (profiles / name / session.SEED_FILE).write_text("12345")
    record("a provider's accounts are its logged-in profiles on disk, the default first",
           session.accounts_on_disk(profiles, "chatgpt") == ["chatgpt", "chatgpt-a2"],
           str(session.accounts_on_disk(profiles, "chatgpt")))
    record("an account's profile has a checked name", session.account_profile("chatgpt") == "chatgpt"
           and session.account_profile("chatgpt", "a2") == "chatgpt-a2")
    try:
        session.account_profile("chatgpt", "../up")
        said = "taken"
    except ValueError:
        said = "refused"
    record("a name that is not a plain one makes no profile", said == "refused", said)


def health_answers():
    failure = GenerationResult.failure("a wall", kind="provider_error")
    health = ProviderHealth("chatgpt")
    health.pacing.update(cooldown_base=30.0, cooldown_max=100.0, min_gap=0.0, image_budget=2)
    pauses = []
    for _ in range(4):
        health.note(failure, 1.0)
        pauses.append(round(health.cooldown_until - time.time()))
    record("each failure in a row doubles the pause, up to the ceiling", pauses == [30, 60, 100, 100], str(pauses))
    record("the last error stays for health to show", health.last_provider_error == "a wall")

    health.note(GenerationResult(success=True, text="ok"), 1.0)
    record("a success ends the row", health.consecutive_errors == 0)

    health = ProviderHealth("chatgpt")
    health.note(GenerationResult.failure("timed out", kind="provider_timeout"), 1.0)
    record("a provider's timeout cools down too", health.consecutive_errors == 1 and health.cooldown_until > time.time())

    health = ProviderHealth("chatgpt")
    for kind in ("worker_error", "cancelled", "empty_reply"):
        health.note(GenerationResult.failure("x", kind=kind), 1.0)
    record("a failure not the site's does not cool the provider down", health.cooldown_until == 0.0
           and health.consecutive_errors == 0)

    health = ProviderHealth("chatgpt")
    health.pacing.update(image_budget=2, min_gap=0.0)
    made = GenerationResult(success=True, media=[MediaArtifact(filename="a.png", type="image"),
                                                 MediaArtifact(filename="b.txt", type="file")])
    health.note(made, 1.0)
    record("a file that is not a picture spends no budget", health.images_in_window() == 1, str(health.images_in_window()))
    record("under the budget nothing holds", health.hold_seconds() == 0.0, str(health.hold_seconds()))
    health.note(made, 1.0)
    held = health.hold_seconds()
    record("a budget spent holds the provider until the oldest picture leaves the window",
           pool_module.IMAGE_WINDOW_SECONDS - 5 < held <= pool_module.IMAGE_WINDOW_SECONDS, "{:.0f}s".format(held))

    health = ProviderHealth("chatgpt")
    health.pacing.update(min_gap=120.0)
    health.note(GenerationResult(success=True, text="ok"), 1.0)
    record("the gap between turns holds", 115 < health.hold_seconds() <= 120, "{:.0f}s".format(health.hold_seconds()))
    record("a gap is pacing, not a provider unwell", health.cooldown_until == 0.0)

    pool = BrowserPool()
    pool._health = {"chatgpt": ProviderHealth("chatgpt"), "grok": ProviderHealth("grok")}
    pool._health["grok"].note(failure, 1.0)
    record("one provider's cooldown does not hold another", pool.hold_seconds("chatgpt") == 0.0
           and pool.hold_seconds("grok") > 0 and pool.cooling_down("grok") and not pool.cooling_down("chatgpt"))
    pool = BrowserPool()
    pool._health = {"chatgpt": ProviderHealth("chatgpt"), "chatgpt-b": ProviderHealth("chatgpt", "chatgpt-b"),
                    "grok": ProviderHealth("grok")}
    for health in pool._health.values():
        health.pacing.update(image_budget=0, min_gap=0.0, image_total=3)
    picture = GenerationResult(success=True, media=[MediaArtifact(filename="a.png", type="image")])
    pool._health["chatgpt"].note(picture, 1.0)
    pool._health["chatgpt-b"].note(picture, 1.0)
    pool._health["grok"].note(picture, 1.0)
    record("under the cap across accounts nothing holds", pool.hold_seconds("chatgpt") == 0.0)
    pool._health["chatgpt-b"].note(picture, 1.0)
    record("the cap across a provider's accounts holds them all, and no other provider",
           pool.hold_seconds("chatgpt") > 3600 and pool.hold_seconds("chatgpt-b") > 3600 and pool.hold_seconds("grok") == 0.0,
           "{:.0f}s {:.0f}s {:.0f}s".format(pool.hold_seconds("chatgpt"), pool.hold_seconds("chatgpt-b"), pool.hold_seconds("grok")))
    record("the budget's report says when the cap frees", pool.pacing_report("chatgpt")["budget_free_in"] > 3600)
    settings.pacing_path = str(Path(tempfile.mkdtemp(prefix="worker-pacing-", dir=str(Path.home() / ".cache"))))
    kept = ProviderHealth("chatgpt", "chatgpt-b")
    kept.note(picture, 1.0)
    record("an account's budget is kept in a file of its own",
           (Path(settings.pacing_path) / "pacing-chatgpt-b.json").exists() and not (Path(settings.pacing_path) / "pacing-chatgpt.json").exists())
    settings.pacing_path = ""

    pool = BrowserPool()
    pool._health = {"chatgpt": ProviderHealth("chatgpt"), "grok": ProviderHealth("grok")}
    record("a provider not here reports nothing", pool.pacing_report("nobody") == {} and pool.pacing("nobody") == {}
           and pool.hold_seconds("nobody") == 0.0)

    pool._health["chatgpt"].pacing.update(image_budget=1)
    pool._health["chatgpt"].note(made, 1.0)
    report = pool.pacing_report("chatgpt")
    record("the budget's report says when it frees", report["images_last_3h"] == 1 and report["image_budget"] == 1
           and report["budget_free_in"] > pool_module.IMAGE_WINDOW_SECONDS - 5, str(report))


def runner_answers():
    media = Path(tempfile.mkdtemp(prefix="worker-paths-", dir=str(Path.home() / ".cache")))
    settings.media_path = media
    settings.poll_interval = 0.01

    pool = Pool()
    client = Client()
    runner = runner_module.Runner(pool, "grok")
    runner._handle(client, JOB)
    refused = client.to("/result")
    record("a job of another provider is refused and not run on this browser", not pool.executed
           and refused[0]["status"] == "failed" and refused[0]["error_kind"] == "worker_error" and runner.failed == 1,
           str(refused[0]))

    pool = Pool(result=GenerationResult(success=True, text="words", thread_url="https://chatgpt.com/c/1", media=[
        MediaArtifact(filename="a.png", type="image", metadata={"size": 1})]))
    client = Client()
    runner = runner_module.Runner(pool, "chatgpt")
    runner._handle(client, JOB)
    body = client.to("/result")[0]
    record("a turn that worked posts its words, its files and its thread, and is counted",
           body["status"] == "done" and body["attempt"] == 1 and body["text"] == "words"
           and body["media"] == [{"filename": "a.png", "type": "image", "metadata": {"size": 1}}]
           and body["thread_url"] == "https://chatgpt.com/c/1" and runner.processed == 1 and len(pool.noted) == 1,
           str(body))

    pool = Pool(result=GenerationResult.failure("a wall", kind="provider_error"))
    client = Client()
    runner = runner_module.Runner(pool, "chatgpt")
    runner._handle(client, JOB)
    body = client.to("/result")[0]
    record("a turn that failed posts why, and is counted as failed",
           body["status"] == "failed" and body["error"] == "a wall" and body["error_kind"] == "provider_error"
           and runner.failed == 1 and runner.processed == 0 and runner.last_error == "a wall", str(body))

    kept = media / "kept.png"
    kept.write_bytes(b"x")
    pool = Pool(result=GenerationResult(success=True, media=[MediaArtifact(filename="kept.png", type="image"),
                                                             MediaArtifact(filename="gone.png", type="image")]))
    client = Client({"/result": Response(409, {"detail": "cancelled"})})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._handle(client, JOB)
    record("a result the api refuses removes what the attempt saved, and is not counted as done",
           not kept.exists() and runner.refused == 1 and runner.processed == 0 and "cancelled" in runner.last_error,
           "file left {} refused {} error {!r}".format(kept.exists(), runner.refused, runner.last_error))
    record("a refused picture was still made, so it still spends the budget", len(pool.noted) == 1)

    pool = Pool(hold=5.0)
    client = Client({"/ping": RuntimeError("the api is restarting"), "/tombstones/claim": Response(204)})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._halt.wait = lambda seconds=None: None
    turns(runner, client, 1)
    record("a provider on hold says so, claims nothing, and survives an api that does not answer",
           client.to("/ping")[0]["providers"] == ["chatgpt"] and client.to("/ping")[0]["pacing"]["image_budget"] == 40
           and not client.to("/jobs/claim"), str(client.calls[:2]))
    record("a pacing gap does not starve a thread deletion", len(client.to("/tombstones/claim")) == 1,
           str(len(client.to("/tombstones/claim"))))

    pool = Pool(hold=5.0, cooling=True)
    client = Client()
    runner = runner_module.Runner(pool, "chatgpt")
    runner._halt.wait = lambda seconds=None: None
    turns(runner, client, 1)
    record("an error cooldown holds the deletion back too", not client.to("/tombstones/claim") and client.to("/ping"))

    pool = Pool()
    client = Client({"/jobs/claim": RuntimeError("the api is restarting"), "/tombstones/claim": Response(204)})
    runner = runner_module.Runner(pool, "chatgpt")
    turns(runner, client, 3)
    record("a claim that fails is said and the runner goes on asking", len(client.to("/jobs/claim")) == 3
           and "claim failed" in runner.last_error, "{} claims, {!r}".format(len(client.to("/jobs/claim")), runner.last_error))

    pool = Pool(raises=RuntimeError("the pool blew up"))
    client = Client({"/jobs/claim": Response(200, JOB), "/tombstones/claim": Response(204)})
    runner = runner_module.Runner(pool, "chatgpt")
    turns(runner, client, 2)
    record("a job that blows up is said, leaves no current job, and the runner goes on",
           runner.failed == 2 and runner.current_job is None and "the pool blew up" in runner.last_error
           and len(pool.executed) == 2, "failed {} current {} {!r}".format(runner.failed, runner.current_job, runner.last_error))

    # The api restarts on every change to its code. A result it never got means the turn is made again.
    runner_module.RESULT_RETRY_SECONDS = (0.01, 0.01, 0.01, 0.01, 0.01)
    down = httpx.ConnectError("the api is restarting")

    pool = Pool(result=GenerationResult(success=True, text="ok"))
    client = Client({"/jobs/claim": Response(200, JOB), "/result": down})
    runner = runner_module.Runner(pool, "chatgpt")
    # Twice round: the second job is the one the runner, told to stop, gives up on after two tries.
    turns(runner, client, 2)
    record("a result the api never takes is tried again, then said, not counted as done, and the runner goes on",
           len(client.to("/result")) == 6 + 2 and runner.processed == 0 and runner.failed == 2
           and runner.current_job is None and "handle failed" in runner.last_error,
           "{} tries, {!r}".format(len(client.to("/result")), runner.last_error))

    pool = Pool(result=GenerationResult(success=True, text="ok"))
    client = Client({"/result": [down, down, Response(200)]})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._handle(client, JOB)
    bodies = client.to("/result")
    record("a result the api takes once it is back counts as done, the same result each try",
           len(bodies) == 3 and bodies[0] == bodies[2] and runner.processed == 1 and runner.failed == 0,
           "{} tries, processed {}".format(len(bodies), runner.processed))

    pool = Pool(result=GenerationResult(success=True, text="ok"))
    client = Client({"/result": [Response(503), Response(200)]})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._handle(client, JOB)
    record("a 5xx from the api is tried again", len(client.to("/result")) == 2 and runner.processed == 1)

    pool = Pool(result=GenerationResult(success=True, text="ok"))
    client = Client({"/result": Response(422)})
    runner = runner_module.Runner(pool, "chatgpt")
    try:
        runner._handle(client, JOB)
        said = "returned"
    except RuntimeError:
        said = "raised"
    record("an answer the api means is not tried again", said == "raised" and len(client.to("/result")) == 1,
           "{} after {} tries".format(said, len(client.to("/result"))))

    # The api can take a result and lose its answer: the next try then gets 409, about the job's own result.
    kept = media / "taken.png"
    kept.write_bytes(b"x")
    pool = Pool(result=GenerationResult(success=True, media=[MediaArtifact(filename="taken.png", type="image")]))
    client = Client({"/result": [httpx.ReadTimeout("the answer was lost"), Response(409, {"detail": "job is done"})]})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._handle(client, JOB)
    record("a 409 after a try that went unanswered keeps the files: they may be the job's own",
           kept.exists() and runner.refused == 1 and runner.processed == 0, "file left {}".format(kept.exists()))

    pool = Pool(result=GenerationResult(success=True, text="ok"))
    client = Client({"/result": down})
    runner = runner_module.Runner(pool, "chatgpt")
    runner.stop()
    try:
        runner._handle(client, JOB)
    except httpx.ConnectError:
        pass
    record("a worker shutting down stops waiting on the api", len(client.to("/result")) == 2,
           "{} tries".format(len(client.to("/result"))))

    # With the real http client, what really reaches the except: a port nobody listens on, then an api on it.
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    class Api(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    servers = []

    def comes_back():
        servers.append(HTTPServer(("127.0.0.1", port), Api))
        servers[0].serve_forever()
    runner_module.RESULT_RETRY_SECONDS = (0.5, 0.5, 0.5, 0.5, 0.5)
    threading.Timer(0.3, comes_back).start()
    pool = Pool(result=GenerationResult(success=True, text="ok"))
    runner = runner_module.Runner(pool, "chatgpt")
    with real_httpx_client(base_url="http://127.0.0.1:{}".format(port), timeout=5.0) as real:
        runner._handle(real, JOB)
    servers[0].shutdown()
    record("a real connection refused is waited out", runner.processed == 1 and runner.failed == 0,
           "processed {} last error {!r}".format(runner.processed, runner.last_error))
    runner_module.RESULT_RETRY_SECONDS = (0.01, 0.01, 0.01, 0.01, 0.01)

    # A budget file that cannot be written cost a finished picture its result (measured 2026-10-31).
    settings.pacing_path = str(media / "no" / "such" / "folder")
    made = GenerationResult(success=True, media=[MediaArtifact(filename="made.png", type="image")])
    real_pool = pool_with(Provider(result=made))
    client = Client()
    runner = runner_module.Runner(real_pool, "chatgpt")
    runner._handle(client, JOB)
    snapshot = real_pool.status()
    record("a budget file that cannot be written does not lose the job's result",
           len(client.to("/result")) == 1 and runner.processed == 1, "{} posted".format(len(client.to("/result"))))
    health = real_pool._health["chatgpt"]
    record("and health says so, and memory still counts", health.images_in_window() == 1
           and "FileNotFoundError" in (snapshot["chatgpt"]["budget_file_error"] or ""),
           repr(snapshot["chatgpt"]["budget_file_error"]))
    settings.pacing_path = str(media)
    health = ProviderHealth("chatgpt")
    health.budget_file_error = "an old failure"
    health.note(made, 1.0)
    record("a write that works again clears it", health.budget_file_error is None)
    settings.pacing_path = ""

    pool = Pool()
    client = Client({"/tombstones/claim": Response(200, STONE)})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._delete_one_thread(client)
    record("a thread deleted is reported and counted", pool.deleted == [STONE["thread_url"]]
           and client.to("/tombstones/stone-1/result") == [{"ok": True, "error": None}] and runner.threads_deleted == 1)

    pool = Pool(deletion=GenerationResult.failure("status 500", kind="provider_error"))
    client = Client({"/tombstones/claim": Response(200, STONE)})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._delete_one_thread(client)
    record("a deletion that failed is reported as failed and counted",
           client.to("/tombstones/stone-1/result") == [{"ok": False, "error": "status 500"}]
           and runner.thread_deletions_failed == 1 and "status 500" in runner.last_error, repr(runner.last_error))

    pool = Pool()
    client = Client({"/tombstones/claim": Response(204)})
    runner = runner_module.Runner(pool, "chatgpt")
    runner._delete_one_thread(client)
    record("no thread to delete opens nothing", pool.deleted == [])

    client = Client({"/tombstones/claim": RuntimeError("the api is restarting")})
    runner = runner_module.Runner(Pool(), "chatgpt")
    runner._maybe_delete_one_thread(client)
    runner._maybe_delete_one_thread(client)
    record("a tombstone check that fails is said, and is not asked again within its interval",
           len(client.to("/tombstones/claim")) == 1 and "tombstone failed" in runner.last_error, repr(runner.last_error))

    lost, finished = threading.Event(), threading.Event()
    client = Client({"/heartbeat": RuntimeError("a missed beat")})
    beat = threading.Thread(target=runner_module.Runner(Pool(), "chatgpt")._heartbeat,
                            args=(client, "job-1", 1, 0.3, lost, finished))
    beat.start()
    time.sleep(1.3)
    finished.set()
    beat.join(timeout=5)
    record("a missed heartbeat is not a lost job", not lost.is_set() and len(client.to("/heartbeat")) >= 2,
           "{} beats".format(len(client.to("/heartbeat"))))

    lost, finished = threading.Event(), threading.Event()
    client = Client({"/heartbeat": Response(404)})
    beat = threading.Thread(target=runner_module.Runner(Pool(), "chatgpt")._heartbeat,
                            args=(client, "job-1", 1, 0.3, lost, finished))
    beat.start()
    time.sleep(0.8)
    finished.set()
    beat.join(timeout=5)
    record("only the api's word that the job is gone stops the driver", not lost.is_set())


def main():
    settings.pacing_path = ""
    pool_answers()
    health_answers()
    runner_answers()
    passed = sum(results)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
