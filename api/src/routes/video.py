from fastapi import APIRouter, Depends

from src.jobs import create_job
from src.models import VideoScriptRequest
from src.security import current_user

router = APIRouter(tags=["features"])


@router.post("/video/script", status_code=202)
def video_script(body: VideoScriptRequest, user: dict = Depends(current_user)):
    return create_job(
        user=user,
        provider=body.provider,
        feature="video_script",
        payload={"duration": body.duration},
        conversation_id=body.conversation_id,
        user_message="Write a {}-second video script for this image.".format(body.duration),
        title="Video script",
        media_id=body.media_id,
    )
