import os
from pathlib import Path


class Settings:
    def __init__(self):
        self.api_url = os.environ.get("API_URL", "http://localhost:3000").rstrip("/")
        self.worker_token = os.environ.get("WORKER_TOKEN", "")
        self.provider_mode = os.environ.get("PROVIDER_MODE", "real").lower()
        self.media_path = Path(os.environ.get("MEDIA_PATH", "./storage/media"))
        self.sessions_path = Path(os.environ.get("SESSIONS_PATH", "./storage/sessions"))
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
        self.providers = [
            p.strip() for p in os.environ.get("PROVIDERS", "chatgpt").split(",") if p.strip()
        ]


settings = Settings()
