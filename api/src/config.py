import os
import sys
from pathlib import Path


def _required(name):
    value = os.environ.get(name)
    if not value:
        sys.exit("missing required environment variable {}".format(name))
    return value


class Settings:
    def __init__(self):
        self.db_path = Path(os.environ.get("DB_PATH", "./storage/db/app.db"))
        self.media_path = Path(os.environ.get("MEDIA_PATH", "./storage/media"))
        self.jwt_secret = _required("JWT_SECRET")
        self.invite_code = _required("INVITE_CODE")
        self.worker_token = _required("WORKER_TOKEN")
        self.token_ttl_hours = int(os.environ.get("TOKEN_TTL_HOURS", "24"))
        self.default_quota = int(os.environ.get("DEFAULT_QUOTA", "100"))
        # A claim holds the job for this long unless renewed. The provider's own
        # ceiling is 300s, so a live worker renews well inside it; a dead one
        # cannot, and the row is reclaimed on the next claim.
        self.job_lease_seconds = int(os.environ.get("JOB_LEASE_SECONDS", "420"))
        self.job_max_attempts = int(os.environ.get("JOB_MAX_ATTEMPTS", "3"))
        # A test seam: shifts the api's idea of today so a day change can be
        # exercised without waiting for one. Zero in real use.
        self.clock_offset_seconds = int(os.environ.get("CLOCK_OFFSET_SECONDS", "0"))
        # How long a job may sit pending with no worker asking for its provider
        # before it is failed and refunded, floored below so a healthy worker in
        # the middle of a long turn is never mistaken for a missing one.
        self.no_worker_seconds = int(os.environ.get("NO_WORKER_SECONDS", "180"))
        # A busy worker proves it is alive by its heartbeat, at most a third of
        # the lease apart. Two intervals covers a missed beat, and thirty seconds
        # covers a restart; shorter than that and a job queued behind a healthy
        # long turn is failed as unserved.
        floor = int(self.job_lease_seconds / 3.0) * 2 + 30
        self.no_worker_seconds = max(self.no_worker_seconds, floor)
        # A turn refused because the provider's account needs its admin holds that provider out this
        # long; then the next turn finds out whether it has been fixed.
        self.provider_hold_seconds = int(os.environ.get("PROVIDER_HOLD_SECONDS", "600"))


settings = Settings()
