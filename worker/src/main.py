from contextlib import asynccontextmanager

from fastapi import FastAPI

from src.config import settings
from src.pool import BrowserPool
from src.runner import Runner

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
        "mode": settings.provider_mode,
        "api_url": settings.api_url,
        "providers": pool.status(),
        "jobs_processed": runner.processed,
        "jobs_failed": runner.failed,
        "last_error": runner.last_error,
    }
