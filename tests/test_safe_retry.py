#!/usr/bin/env python3
"""A failed turn says whether it is safe to try again: only a turn that never reached the provider is (issue #31).

    ~/cloakbrowser-env/bin/python tests/test_safe_retry.py

The real pool, runner and providers' _send; a fake provider, page and client stand in, no browser or api.
The api's side is in test_safe_retry_api.py. Prints N/N PASSED.
"""

import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "worker"))
sys.path.insert(0, str(ROOT / "tests"))

from playwright._impl._errors import Error as PlaywrightError, TargetClosedError, TimeoutError as PlaywrightTimeout  # noqa: E402

from src import runner as runner_module  # noqa: E402
from src.pool import BrowserPool, ProviderHealth  # noqa: E402
from src.providers.base import FeatureType, GenerationResult, ProviderError  # noqa: E402
from src.providers.chatgpt import ChatGPTProvider  # noqa: E402
from src.providers.gemini import GeminiProvider  # noqa: E402
from src.providers.grok import GrokProvider  # noqa: E402
from test_worker_paths import JOB, Client, Pool  # noqa: E402

results = []


def record(name, ok, detail=""):
    results.append(bool(ok))
    print("[{}] {}  {}".format("PASS" if ok else "FAIL", name, detail), flush=True)


class Turning:
    """A provider whose turn fails at a chosen moment: before its send, or after it."""

    name = "chatgpt"
    supported_features = {FeatureType.CHAT, FeatureType.IMAGE}

    def __init__(self, raises=None, after_send=False, result=None):
        self.raises, self.after_send = raises, after_send
        self.result = result or GenerationResult(success=True, text="ok")
        self.sent = False

    def supports(self, feature):
        return feature in ("chat", "image")

    def bind(self, phase_hook=None, stop_hook=None):
        pass

    def stop(self):
        pass

    def _turn(self):
        if self.after_send:
            self.sent = True
        if self.raises is not None:
            raise self.raises
        return self.result

    def chat(self, message, history=None, thread_url=None):
        return self._turn()

    def generate_image(self, prompt, reference=None, thread_url=None):
        return self._turn()


class Unmarked(Turning):
    """A driver that predates the mark: nothing says whether it sent."""

    def __init__(self, raises):
        super().__init__(raises)
        del self.sent


def run(provider):
    pool = BrowserPool()
    pool._providers["chatgpt"] = provider
    pool._locks["chatgpt"] = threading.Lock()
    pool._health.setdefault("chatgpt", ProviderHealth("chatgpt"))
    return pool.execute("chatgpt", "image", {"prompt": "p"})


def pool_answers():
    cases = [
        ("a provider error before the send is safe to try again", Turning(ProviderError("page did not load")), True, "provider_error"),
        ("a provider error after the send is not", Turning(ProviderError("no answer"), after_send=True), False, "provider_error"),
        ("a provider's word that the sent turn never arrived makes it safe",
         Turning(ProviderError("never received", retry_safe=True), after_send=True), True, "provider_error"),
        ("an account that needs its admin is not tried again",
         Turning(ProviderError("memory on", kind="provider_misconfigured")), False, "provider_misconfigured"),
        ("an account behind a check is not tried again", Turning(ProviderError("check", kind="provider_blocked")), False, "provider_blocked"),
        ("a browser gone before the send is safe", Turning(TargetClosedError("Target page, context or browser has been closed")), True, "provider_error"),
        ("a browser gone after the send is not", Turning(TargetClosedError("Target page, context or browser has been closed"), after_send=True), False, "provider_error"),
        ("a page that timed out before the send is the site's timeout, and safe",
         Turning(PlaywrightTimeout("Page.goto: Timeout 90000ms exceeded.")), True, "provider_timeout"),
        ("a site that could not be reached before the send likewise",
         Turning(PlaywrightError("Page.goto: net::ERR_NAME_NOT_RESOLVED at https://chatgpt.com/")), True, "provider_timeout"),
        ("a timeout after the send is the site's, and not safe",
         Turning(PlaywrightTimeout("Locator.inner_text: Timeout 30000ms exceeded."), after_send=True), False, "provider_timeout"),
        ("a fault of our own code is a worker error and not tried again", Turning(TypeError("a bug")), False, "worker_error"),
        ("a driver that cannot say whether it sent is taken to have sent", Unmarked(ProviderError("x")), False, "provider_error"),
    ]
    for name, provider, safe, kind in cases:
        result = run(provider)
        record(name, result.retry_safe is safe and result.error_kind == kind, (result.retry_safe, result.error_kind, result.error))

    leftover = Turning(ProviderError("page did not load"))
    leftover.sent = True
    result = run(leftover)
    record("the mark of an earlier turn does not count against this one", result.retry_safe is True, result.retry_safe)
    result = run(Turning())
    record("a success is never marked for another try", result.success and result.retry_safe is False, result.retry_safe)


def runner_answers():
    pool = Pool(result=GenerationResult.failure("page did not load", kind="provider_error", retry_safe=True))
    client = Client()
    runner_module.Runner(pool, "chatgpt")._handle(client, JOB)
    sent = client.to("/result")
    record("the runner tells the api the turn is safe to try again", sent and sent[0].get("retry_safe") is True, sent)


class Box:
    def __init__(self, page):
        self.page = page

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def inner_text(self):
        return self.page.text

    def click(self, timeout=None, force=None):
        pass

    def focus(self):
        pass

    def scroll_into_view_if_needed(self, timeout=None):
        pass

    def evaluate(self, script):
        pass


class Keys:
    def __init__(self, page):
        self.page = page

    def insert_text(self, text):
        if self.page.takes_text:
            self.page.text += text

    def press(self, key):
        if key == "Enter":
            self.page.sent_seen.append(self.page.provider.sent)
            self.page.text = ""
        elif key == "Backspace":
            self.page.text = ""


class Page:
    def __init__(self, provider, takes_text=True):
        self.provider, self.takes_text = provider, takes_text
        self.text, self.sent_seen = "", []
        self.keyboard = Keys(self)

    def locator(self, selector):
        return Box(self)

    def wait_for_timeout(self, ms):
        pass


def provider_sends():
    work = Path(tempfile.mkdtemp(prefix="safe-retry-"))
    for cls in (ChatGPTProvider, GrokProvider, GeminiProvider):
        for takes in (True, False):
            provider = cls(work / "media", work / "sessions")
            provider.sent = False
            page = Page(provider, takes_text=takes)
            if cls is GrokProvider:
                provider._dismiss_overlays = lambda page: None
                provider._composer = lambda page, seconds: "composer"
                provider._composer_text = lambda page, composer: page.text
            try:
                if cls is GrokProvider:
                    provider._send(page, "composer", "a red square")
                else:
                    provider._send(page, "a red square")
                said = "sent"
            except ProviderError as exc:
                said = str(exc)
            if takes:
                record("{} marks the turn sent just before Enter".format(cls.name),
                       said == "sent" and page.sent_seen == [True] and provider.sent is True, (said, page.sent_seen))
            else:
                record("{} leaves a turn that never reached its composer unsent".format(cls.name),
                       said != "sent" and page.sent_seen == [] and provider.sent is False, (said, page.sent_seen))


def main():
    pool_answers()
    runner_answers()
    provider_sends()
    passed = sum(results)
    print("{}/{} PASSED".format(passed, len(results)))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
