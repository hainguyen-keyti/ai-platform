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
runners = [Runner(pool, provider, account) for account, provider in pool.accounts.items()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.start()
    for runner in runners:
        runner.start()
    yield
    for runner in runners:
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
        # The defaults; what each provider actually waits is under providers.
        "pacing": {
            "min_gap_seconds": settings.min_gap,
            "image_budget_3h": settings.image_budget,
            "cooldown_base_seconds": settings.cooldown_base,
            "cooldown_max_seconds": settings.cooldown_max,
            "holding_for_seconds": round(pool.hold_seconds(), 1),
            "per_provider": {name: pool.pacing(name) for name in settings.providers},
        },
        "runners": {r.account: r.snapshot() for r in runners},
        # The totals stay at the top so anything reading them keeps working.
        "current_job": next((r.current_job for r in runners if r.current_job), None),
        "jobs_processed": sum(r.processed for r in runners),
        "jobs_failed": sum(r.failed for r in runners),
        "results_refused": sum(r.refused for r in runners),
        "threads_deleted": sum(r.threads_deleted for r in runners),
        "thread_deletions_failed": sum(r.thread_deletions_failed for r in runners),
        "last_error": next((r.last_error for r in reversed(runners) if r.last_error), None),
    }
