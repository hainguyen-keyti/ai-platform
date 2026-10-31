from fastapi import APIRouter, Depends, Response

from src.jobs import claim_next_job, heartbeat, note_workers, record_progress, record_result
from src.models import ThreadsKnown, TombstoneResult, WorkerClaim, WorkerHeartbeat, WorkerProgress, WorkerResult
from src.security import require_worker
from src.tombstones import claim_tombstone, known_threads, settle_tombstone

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/workers/ping")
def ping(body: WorkerClaim = WorkerClaim(), _: bool = Depends(require_worker)):
    return note_workers(body.providers, body.pacing.model_dump() if body.pacing else None, body.account)


@router.post("/jobs/claim")
def claim(body: WorkerClaim = WorkerClaim(), _: bool = Depends(require_worker)):
    job = claim_next_job(body.providers, body.pacing.model_dump() if body.pacing else None, body.account)
    if job is None:
        return Response(status_code=204)
    return job


@router.post("/jobs/{job_id}/heartbeat")
def beat(job_id: str, body: WorkerHeartbeat, _: bool = Depends(require_worker)):
    return heartbeat(job_id, body.attempt)


@router.post("/jobs/{job_id}/progress")
def progress(job_id: str, body: WorkerProgress, _: bool = Depends(require_worker)):
    return record_progress(job_id, body.attempt, body.phase)


@router.post("/tombstones/claim")
def claim_thread_to_delete(body: WorkerClaim = WorkerClaim(), _: bool = Depends(require_worker)):
    stone = claim_tombstone(body.providers, body.account)
    if stone is None:
        return Response(status_code=204)
    return stone


@router.post("/tombstones/{stone_id}/result")
def thread_deletion_result(stone_id: str, body: TombstoneResult, _: bool = Depends(require_worker)):
    return settle_tombstone(stone_id, body.ok, body.error)


@router.post("/threads/known")
def threads_known(body: ThreadsKnown, _: bool = Depends(require_worker)):
    return {"known": known_threads(body.provider, body.thread_urls)}


@router.post("/jobs/{job_id}/result")
def submit_result(job_id: str, body: WorkerResult, _: bool = Depends(require_worker)):
    return record_result(
        job_id=job_id,
        attempt=body.attempt,
        status=body.status,
        text=body.text,
        media=[m.model_dump() for m in body.media],
        error=body.error,
        error_kind=body.error_kind,
        thread_url=body.thread_url,
    )
