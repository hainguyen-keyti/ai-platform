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
        self.job_stale_seconds = int(os.environ.get("JOB_STALE_SECONDS", "600"))


settings = Settings()
