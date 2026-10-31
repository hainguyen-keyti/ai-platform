import json
import statistics
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from src.config import settings
from src.providers.base import GenerationResult, JobCancelled, ProviderError
from src.providers.mock import MockProvider

IMAGE_WINDOW_SECONDS = 3 * 3600


def browser_gone(exc) -> bool:
    """Playwright's word that the page, context or browser under a call is gone."""
    try:
        from playwright._impl._errors import is_target_closed_error
    except Exception:
        is_target_closed_error = None
    if is_target_closed_error is not None and is_target_closed_error(exc):
        return True
    said = str(exc).lower()
    return "has been closed" in said or "target closed" in said


def build_provider(name: str, account: str = None):
    """The driver of a provider, on one of its accounts. A new provider is a BaseProvider and a line here."""
    if settings.provider_mode == "mock":
        return MockProvider(settings.media_path, settings.sessions_path, name=name, account=account)
    if name == "chatgpt":
        from src.providers.chatgpt import ChatGPTProvider

        return ChatGPTProvider(settings.media_path, settings.sessions_path, account)
    if name == "grok":
        from src.providers.grok import GrokProvider

        return GrokProvider(settings.media_path, settings.sessions_path, account)
    if name == "gemini":
        from src.providers.gemini import GeminiProvider

        return GeminiProvider(settings.media_path, settings.sessions_path, account)
    raise ValueError("provider {} has no real implementation yet".format(name))


class ProviderHealth:
    """What one account of a provider has been doing lately, and whether to leave it alone."""

    def __init__(self, provider="chatgpt", account=None):
        self.provider = provider
        self.account = account or provider
        self.pacing = settings.pacing(provider)
        self.consecutive_errors = 0
        self.cooldown_until = 0.0
        self.last_turn_at = 0.0
        # A real account's budget outlives the worker: counted in memory, a restart gave it all back.
        # Only a worker told where keeps it (run-worker.sh, in real mode): a mock's or a test's pictures
        # spend no account and must not count against the real one's file.
        self.budget_file = (Path(settings.pacing_path) / "pacing-{}.json".format(self.account)
                            if settings.pacing_path else None)
        self.budget_file_error = None
        self.image_times = deque(self._stored_image_times())
        self.latencies = deque(maxlen=50)
        self.last_provider_error = None

    def _stored_image_times(self) -> list:
        if self.budget_file is None or not self.budget_file.exists():
            return []
        cutoff = time.time() - IMAGE_WINDOW_SECONDS
        return sorted(at for at in json.loads(self.budget_file.read_text()) if at >= cutoff)

    def _store_image_times(self):
        if self.budget_file is None:
            return
        self.images_in_window()
        written = self.budget_file.with_name(self.budget_file.name + ".new")
        # The picture is made and its job waits to be told: a file that cannot be written must not lose it.
        # Memory still counts, and health says the count will not outlive a restart.
        try:
            written.write_text(json.dumps(list(self.image_times)))
            written.replace(self.budget_file)
            self.budget_file_error = None
        except OSError as exc:
            self.budget_file_error = "{}: {}".format(type(exc).__name__, exc)

    def note(self, result: GenerationResult, elapsed: float):
        self.last_turn_at = time.time()
        self.latencies.append(elapsed)
        if result.error_kind in ("provider_error", "provider_timeout"):
            # Every consecutive failure doubles the pause. Retrying into a wall
            # is how a throttled account turns into a banned one.
            self.consecutive_errors += 1
            pause = min(self.pacing["cooldown_base"] * 2 ** (self.consecutive_errors - 1),
                        self.pacing["cooldown_max"])
            self.cooldown_until = time.time() + pause
            self.last_provider_error = result.error
        elif result.success:
            self.consecutive_errors = 0
            for item in result.media:
                if item.type == "image":
                    self.image_times.append(time.time())
            self._store_image_times()

    def images_in_window(self) -> int:
        cutoff = time.time() - IMAGE_WINDOW_SECONDS
        while self.image_times and self.image_times[0] < cutoff:
            self.image_times.popleft()
        return len(self.image_times)

    def hold_seconds(self) -> float:
        now = time.time()
        wait = max(0.0, self.cooldown_until - now,
                   self.last_turn_at + self.pacing["min_gap"] - now)
        if self.pacing["image_budget"] and self.images_in_window() >= self.pacing["image_budget"]:
            wait = max(wait, self.image_times[0] + IMAGE_WINDOW_SECONDS - now)
        return wait

    def snapshot(self) -> dict:
        p50 = statistics.median(self.latencies) if self.latencies else None
        return {
            "cooldown_until": (datetime.fromtimestamp(self.cooldown_until, timezone.utc).isoformat()
                               if self.cooldown_until > time.time() else None),
            "consecutive_errors": self.consecutive_errors,
            "images_last_3h": self.images_in_window(),
            "budget_file_error": self.budget_file_error,
            "p50_latency_s": round(p50, 1) if p50 is not None else None,
            "last_provider_error": self.last_provider_error,
        }


class BrowserPool:
    """Owns one browser session per account, serialised by a lock.

    Two requests must never share a page, so every account gets its own lock and
    a job waits rather than interleaving. Everything here is keyed by account; a
    provider's default account has the provider's own name.
    """

    def __init__(self):
        self._providers = {}
        self._locks = {}
        self._errors = {}
        self._provider_of = {account: name for name in settings.providers for account in settings.accounts(name)}
        self._health = {account: ProviderHealth(name, account) for account, name in self._provider_of.items()}
        self._used_at = {}

    @property
    def accounts(self) -> dict:
        """Every account this pool serves, and its provider."""
        return dict(self._provider_of)

    def start(self):
        for account, name in self._provider_of.items():
            try:
                provider = build_provider(name, account)
                provider.start()
                self._providers[account] = provider
                self._locks[account] = threading.Lock()
            except Exception as exc:
                self._errors[account] = "{}: {}".format(type(exc).__name__, exc)

    def stop(self):
        for provider in self._providers.values():
            try:
                provider.stop()
            except Exception:
                pass
        self._providers.clear()

    def _total_wait(self, health) -> float:
        """How long the cap across a provider's accounts holds: they share one machine and one IP."""
        total = health.pacing.get("image_total")
        if not total:
            return 0.0
        same = [other for other in self._health.values() if other.provider == health.provider]
        for other in same:
            other.images_in_window()
        times = sorted(at for other in same for at in other.image_times)
        return max(0.0, times[len(times) - total] + IMAGE_WINDOW_SECONDS - time.time()) if len(times) >= total else 0.0

    def hold_seconds(self, provider: str = None) -> float:
        """How long this account's runner should wait before claiming anything.

        Per account on purpose: the longest wait of any used to be returned to
        everyone, so one provider's cooldown parked the rest.
        """
        if provider is not None:
            health = self._health.get(provider)
            return max(health.hold_seconds(), self._total_wait(health)) if health else 0.0
        return max([h.hold_seconds() for h in self._health.values()] or [0.0])

    def pacing_report(self, provider: str) -> dict:
        """What this account has spent of its picture budget, for the api to tell whoever asks."""
        health = self._health.get(provider)
        if health is None:
            return {}
        used, budget = health.images_in_window(), health.pacing["image_budget"]
        free_in = health.image_times[0] + IMAGE_WINDOW_SECONDS - time.time() if budget and used >= budget else 0
        return {"images_last_3h": used, "image_budget": int(budget),
                "budget_free_in": max(0.0, free_in, self._total_wait(health))}

    def close_idle(self, account: str):
        """Close a browser no job has used for BROWSER_IDLE_SECONDS; its next job opens it again. Never
        waits on a turn: a browser in use is not idle."""
        used = self._used_at.get(account)
        limit = settings.browser_idle_seconds
        lock = self._locks.get(account)
        if not limit or used is None or lock is None or time.time() - used < limit or not lock.acquire(blocking=False):
            return
        try:
            self._providers[account].stop()
            self._used_at.pop(account, None)
        finally:
            lock.release()

    def cooling_down(self, provider: str) -> bool:
        """An error cooldown, as opposed to a pacing gap: the site is unwell now."""
        health = self._health.get(provider)
        return bool(health) and health.cooldown_until > time.time()

    def pacing(self, provider: str) -> dict:
        health = self._health.get(provider)
        return dict(health.pacing) if health else {}

    def note_result(self, provider_name: str, result: GenerationResult, elapsed: float):
        health = self._health.get(provider_name)
        if health:
            health.note(result, elapsed)

    def execute(self, provider_name: str, feature: str, payload: dict,
                thread_url: str = None, phase_hook=None, stop_hook=None) -> GenerationResult:
        provider = self._providers.get(provider_name)
        if provider is None:
            return GenerationResult.failure(
                "provider {} unavailable: {}".format(
                    provider_name, self._errors.get(provider_name, "not enabled on this worker")
                ),
                kind="provider_error",
            )
        if not provider.supports(feature):
            return GenerationResult.failure(
                "provider {} does not support {}".format(provider_name, feature),
                kind="worker_error",
            )

        with self._locks[provider_name]:
            self._used_at[provider_name] = time.time()
            provider.bind(phase_hook, stop_hook)
            try:
                if feature == "chat":
                    return provider.chat(
                        payload.get("message", ""), payload.get("history"), thread_url
                    )
                if feature == "image":
                    # Several references only ever come for chatgpt (issue #22); one stays a name.
                    return provider.generate_image(
                        payload.get("prompt", ""),
                        payload.get("reference_filenames") or payload.get("reference_filename"), thread_url
                    )
                if feature == "video_script":
                    return provider.generate_video_script(
                        payload.get("filename", ""), int(payload.get("duration", 5)), thread_url
                    )
            except JobCancelled:
                # Refused by the api anyway, but the thread the turn landed in is
                # worth reporting: kept for a live conversation, removed for a
                # deleted one.
                return GenerationResult(
                    success=False, error="cancelled while running", error_kind="cancelled",
                    thread_url=getattr(provider, "last_cancelled_thread", None))
            except ProviderError as exc:
                return GenerationResult.failure(str(exc), kind=exc.kind)
            except Exception as exc:
                if browser_gone(exc):
                    # The page or browser died under the turn: drop it, so the next turn opens the
                    # profile again, and count it as the provider's failure, so a cooldown follows
                    # instead of the next job failing the same way a second later (2026-10-21).
                    try:
                        provider.stop()
                    except Exception:
                        pass
                    return GenerationResult.failure(
                        "the {} browser closed under the turn ({}: {})".format(
                            provider_name, type(exc).__name__, exc), kind="provider_error")
                return GenerationResult.failure(
                    "{}: {}".format(type(exc).__name__, exc), kind="worker_error")
            finally:
                provider.bind(None, None)
                self._used_at[provider_name] = time.time()
        return GenerationResult.failure("unknown feature {}".format(feature), kind="worker_error")

    def delete_thread(self, provider_name: str, thread_url: str) -> GenerationResult:
        """Remove one thread from the provider's account, under the same lock as turns."""
        provider = self._providers.get(provider_name)
        if provider is None:
            return GenerationResult.failure(
                "provider {} unavailable: {}".format(
                    provider_name, self._errors.get(provider_name, "not enabled on this worker")),
                kind="provider_error")
        with self._locks[provider_name]:
            self._used_at[provider_name] = time.time()
            try:
                return GenerationResult(success=bool(provider.delete_thread(thread_url)))
            except ProviderError as exc:
                return GenerationResult.failure(str(exc), kind=exc.kind)
            except Exception as exc:
                if browser_gone(exc):
                    # A browser that died while the runner was idle is first met here: drop it
                    # now, not with the next person's job.
                    try:
                        provider.stop()
                    except Exception:
                        pass
                    return GenerationResult.failure(
                        "the {} browser closed under the deletion ({}: {})".format(
                            provider_name, type(exc).__name__, exc), kind="provider_error")
                return GenerationResult.failure(
                    "{}: {}".format(type(exc).__name__, exc), kind="worker_error")

    def can_clean_library(self, provider_name: str) -> bool:
        """Whether this provider's driver has a Library to clean (issue #27): ChatGPT's alone."""
        return hasattr(self._providers.get(provider_name), "clean_library_page")

    def clean_library_page(self, provider_name: str, cursor, day: str, known) -> dict:
        """One page of the nightly cleanup, under the same lock as turns, so it never meets one."""
        provider = self._providers[provider_name]
        with self._locks[provider_name]:
            self._used_at[provider_name] = time.time()
            try:
                return provider.clean_library_page(cursor, day, known)
            except Exception as exc:
                if browser_gone(exc):
                    try:
                        provider.stop()
                    except Exception:
                        pass
                raise

    def status(self) -> dict:
        out = {}
        for name, of in self._provider_of.items():
            provider = self._providers.get(name)
            entry = {
                "provider": of,
                "ready": provider is not None,
                "features": sorted(f.value for f in provider.supported_features) if provider else [],
                "error": self._errors.get(name),
            }
            entry.update(self._health[name].snapshot())
            entry["pacing"] = self._health[name].pacing
            # Diagnostics the provider chooses to expose: how the last turn was
            # settled, whether the last thread open landed where it aimed, what
            # the account's memory switch read before the last turn, how the
            # last stop ended its turn, and how full the account's file store is (#23).
            for attr in ("last_settle", "last_open", "memory", "last_stop", "storage"):
                if provider is not None and hasattr(provider, attr):
                    entry[attr] = getattr(provider, attr)
            out[name] = entry
        return out
