from fastapi import APIRouter, Depends

from src.jobs import create_job
from src.models import ImageRequest
from src.security import current_user

router = APIRouter(tags=["features"])


@router.post("/image/generate", status_code=202)
def generate_image(body: ImageRequest, user: dict = Depends(current_user)):
    return create_job(
        user=user,
        provider=body.provider,
        feature="image",
        payload={"prompt": body.prompt},
        conversation_id=body.conversation_id,
        user_message="Generate an image: {}".format(body.prompt),
        title=body.prompt,
        reference_media_id=body.reference_media_id,
    )
