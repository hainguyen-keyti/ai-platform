from fastapi import APIRouter, Depends

from src.jobs import cancel_job, create_job, get_job
from src.models import ChatRequest
from src.security import current_user

router = APIRouter(tags=["features"])


@router.post("/jobs/{job_id}/cancel")
def cancel(job_id: str, user: dict = Depends(current_user)):
    return cancel_job(user["id"], job_id)


@router.post("/chat", status_code=202)
def chat(body: ChatRequest, user: dict = Depends(current_user)):
    return create_job(
        user=user,
        provider=body.provider,
        feature="chat",
        payload={"message": body.message},
        conversation_id=body.conversation_id,
        user_message=body.message,
        title=body.message,
    )


@router.get("/jobs/{job_id}")
def job_status(job_id: str, user: dict = Depends(current_user)):
    return get_job(user["id"], job_id)
