import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from src.config import settings
from src.pool import BrowserPool
from src.runner import Runner


def running_code_sha() -> str:
    """The commit this process was started from. A stale worker was twice
    mistaken for a broken feature; one curl should settle that."""
    if os.environ.get("CODE_SHA"):
        return os.environ["CODE_SHA"]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(Path(__file__).resolve().parent), capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "unknown"


CODE_SHA = running_code_sha()
pool = BrowserPool()
runner = Runner(pool)


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.start()
    runner.start()
    yield
    runner.stop()
    pool.stop()


app = FastAPI(title="AI Platform Worker", lifespan=lifespan)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "code_sha": CODE_SHA,
        "mode": settings.provider_mode,
        "api_url": settings.api_url,
        "providers": pool.status(),
        "pacing": {
            "min_gap_seconds": settings.min_gap,
            "image_budget_3h": settings.image_budget,
            "cooldown_base_seconds": settings.cooldown_base,
            "cooldown_max_seconds": settings.cooldown_max,
            "holding_for_seconds": round(pool.hold_seconds(), 1),
        },
        "current_job": runner.current_job,
        "jobs_processed": runner.processed,
        "jobs_failed": runner.failed,
        "results_refused": runner.refused,
        "last_error": runner.last_error,
    }
