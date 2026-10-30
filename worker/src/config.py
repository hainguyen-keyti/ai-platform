import os
from pathlib import Path


class Settings:
    def __init__(self):
        self.api_url = os.environ.get("API_URL", "http://localhost:3000").rstrip("/")
        self.worker_token = os.environ.get("WORKER_TOKEN", "")
        self.provider_mode = os.environ.get("PROVIDER_MODE", "real").lower()
        self.media_path = Path(os.environ.get("MEDIA_PATH", "./storage/media"))
        self.sessions_path = Path(os.environ.get("SESSIONS_PATH", "./storage/sessions"))
        self.pacing_path = os.environ.get("PACING_PATH", "")
        self.poll_interval = float(os.environ.get("POLL_INTERVAL", "1.0"))
        # A mock that answers instantly cannot exercise anything the UI shows
        # while it waits. Tests raise this to make that state observable.
        self.mock_delay = float(os.environ.get("MOCK_DELAY_SECONDS", "0"))
        # Pacing. Heavy use throttled the shared account from 12s to 256s per
        # reply and produced error banners; these keep the worker from driving
        # into that wall. Plus allows roughly 50 images per rolling 3 hours.
        self.min_gap = float(os.environ.get("MIN_GAP_SECONDS", "0"))
        self.image_budget = int(os.environ.get("IMAGE_BUDGET_3H", "40"))
        self.cooldown_base = float(os.environ.get("COOLDOWN_BASE_SECONDS", "30"))
        self.cooldown_max = float(os.environ.get("COOLDOWN_MAX_SECONDS", "900"))
        # When the worker cleans ChatGPT's Library each day, as HH:MM in UTC (issue #27). The default is
        # 23:30 in Vietnam. Empty turns it off.
        self.library_cleanup_at = os.environ.get("LIBRARY_CLEANUP_AT", "16:30").strip()
        self.providers = [
            p.strip() for p in os.environ.get("PROVIDERS", "chatgpt").split(",") if p.strip()
        ]

    def pacing(self, provider: str) -> dict:
        """The pacing for one provider, with per-provider overrides.

        Two accounts on one worker do not share a rhythm: measured 2026-09-24, a
        free grok account answers a short burst and then asks for about nine
        minutes, while the chatgpt account is happy with a few seconds. Any of
        the four values can be set per provider, for example
        MIN_GAP_SECONDS__GROK=120.
        """
        suffix = "__{}".format(provider.upper())

        def value(name, fallback):
            raw = os.environ.get(name + suffix)
            return float(raw) if raw not in (None, "") else fallback

        return {
            "min_gap": value("MIN_GAP_SECONDS", self.min_gap),
            "image_budget": int(value("IMAGE_BUDGET_3H", self.image_budget)),
            "cooldown_base": value("COOLDOWN_BASE_SECONDS", self.cooldown_base),
            "cooldown_max": value("COOLDOWN_MAX_SECONDS", self.cooldown_max),
        }


settings = Settings()
