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
        self.default_quota = int(os.environ.get("DEFAULT_QUOTA", "500"))
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
        # An account behind a check or logged out waits for a person: half an hour, then the next turn finds out (issue #31).
        self.provider_blocked_hold_seconds = int(os.environ.get("PROVIDER_BLOCKED_HOLD_SECONDS", "1800"))
        # A turn that never reached the provider waits this long before it is taken again (issue #31).
        self.job_retry_seconds = int(os.environ.get("JOB_RETRY_SECONDS", "60"))
        # Accounts a new picture conversation goes to first, such as a Plus one (2026-11-08: sessions begun on a
        # Free account met its limit after five pictures and waited 23 hours beside an idle Plus account).
        # Another account takes one only while none of these can. Empty: whichever account asks first.
        self.preferred_image_accounts = [
            name.strip() for name in os.environ.get("PREFERRED_IMAGE_ACCOUNTS", "").split(",") if name.strip()]


settings = Settings()
