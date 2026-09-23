import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.db.client import db, many, one
from src.security import current_user

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("")
def list_conversations(user: dict = Depends(current_user),
                       limit: int = Query(default=50, ge=1, le=200)):
    with db() as conn:
        rows = many(
            conn,
            "SELECT id, user_id, provider, title, created_at, updated_at FROM conversations"
            " WHERE user_id = ? ORDER BY updated_at DESC, rowid DESC LIMIT ?",
            (user["id"], limit),
        )
    return {"items": rows}


@router.get("/{conversation_id}")
def get_conversation(conversation_id: str, user: dict = Depends(current_user)):
    with db() as conn:
        conv = one(
            conn,
            "SELECT * FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user["id"]),
        )
        if not conv:
            raise HTTPException(status_code=404, detail="conversation not found")
        messages = many(
            conn,
            "SELECT id, role, content, created_at FROM messages WHERE conversation_id = ?"
            " ORDER BY created_at, rowid",
            (conversation_id,),
        )
        media = many(
            conn,
            "SELECT id, type, filename, metadata, message_id, created_at FROM media"
            " WHERE conversation_id = ? ORDER BY created_at, rowid",
            (conversation_id,),
        )
    by_message = {}
    for item in media:
        item["metadata"] = json.loads(item["metadata"]) if item["metadata"] else {}
        by_message.setdefault(item["message_id"], []).append(item)
    for message in messages:
        message["media"] = by_message.get(message["id"], [])

    # Which thread this sits in on the provider's site is ours, not the
    # client's: it names a resource inside a shared account.
    conv.pop("provider_thread_url", None)
    conv["messages"] = messages
    # Anything generated before media carried a message id belongs to no bubble;
    # it is returned separately and the client places it by timestamp.
    conv["orphan_media"] = by_message.get(None, [])
    return conv


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: dict = Depends(current_user)):
    with db() as conn:
        owned = one(
            conn,
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user["id"]),
        )
        if not owned:
            raise HTTPException(status_code=404, detail="conversation not found")
        conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
    return Response(status_code=204)
