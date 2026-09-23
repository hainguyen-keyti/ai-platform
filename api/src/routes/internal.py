from fastapi import APIRouter, Depends, Response

from src.jobs import claim_next_job, record_result
from src.models import WorkerResult
from src.security import require_worker

router = APIRouter(prefix="/internal", tags=["internal"])


@router.post("/jobs/claim")
def claim(_: bool = Depends(require_worker)):
    job = claim_next_job()
    if job is None:
        return Response(status_code=204)
    return job


@router.post("/jobs/{job_id}/result")
def submit_result(job_id: str, body: WorkerResult, _: bool = Depends(require_worker)):
    return record_result(
        job_id=job_id,
        status=body.status,
        text=body.text,
        media=[m.model_dump() for m in body.media],
        error=body.error,
        thread_url=body.thread_url,
    )
