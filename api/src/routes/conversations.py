import io
import json
import zipfile
from pathlib import PurePosixPath
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.db.client import db, many, one
from src.models import ConversationUpdate
from src.routes.media import _safe_path
from src.security import current_user
from src.tombstones import leave_tombstone

router = APIRouter(prefix="/conversations", tags=["conversations"])

LISTED = "id, user_id, provider, title, created_at, updated_at"


def _like(term: str) -> str:
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return "%{}%".format(escaped)


@router.get("")
def list_conversations(user: dict = Depends(current_user),
                       limit: int = Query(default=50, ge=1, le=200),
                       q: Optional[str] = Query(default=None, max_length=200)):
    term = (q or "").strip()
    with db() as conn:
        if term:
            # By title or by any word inside the conversation, always the
            # caller's own; the message clause is scoped through the join.
            rows = many(
                conn,
                "SELECT {} FROM conversations c WHERE c.user_id = ? AND ("
                " c.title LIKE ? ESCAPE '\\' OR EXISTS (SELECT 1 FROM messages m"
                "  WHERE m.conversation_id = c.id AND m.content LIKE ? ESCAPE '\\'))"
                " ORDER BY c.updated_at DESC, c.rowid DESC LIMIT ?".format(
                    ", ".join("c." + col for col in LISTED.split(", "))),
                (user["id"], _like(term), _like(term), limit),
            )
        else:
            rows = many(
                conn,
                "SELECT {} FROM conversations WHERE user_id = ?"
                " ORDER BY updated_at DESC, rowid DESC LIMIT ?".format(LISTED),
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


@router.patch("/{conversation_id}")
def rename_conversation(conversation_id: str, body: ConversationUpdate,
                        user: dict = Depends(current_user)):
    with db() as conn:
        changed = conn.execute(
            "UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?",
            (body.title.strip(), conversation_id, user["id"]),
        ).rowcount
        if changed != 1:
            raise HTTPException(status_code=404, detail="conversation not found")
        return one(conn, "SELECT {} FROM conversations WHERE id = ?".format(LISTED), (conversation_id,))


def _entry_name(offered, fallback):
    # The offered name came from the provider's site through the worker. Inside
    # the archive it must be a bare, printable file name or it is not used.
    name = PurePosixPath(str(offered or "")).name
    if (not name.strip() or name in (".", "..") or "\\" in name
            or any(ord(c) < 32 or ord(c) == 127 for c in name)):
        return fallback
    return name


@router.get("/{conversation_id}/media.zip")
def download_conversation_media(conversation_id: str,
                                message_id: Optional[str] = Query(default=None),
                                user: dict = Depends(current_user)):
    """Everything a conversation (or one message of it) produced, as one archive.

    The bytes are already ours, so packaging is done here rather than asked of
    the model, which delivered a zip in one of four measured attempts.
    """
    with db() as conn:
        owned = one(
            conn,
            "SELECT id FROM conversations WHERE id = ? AND user_id = ?",
            (conversation_id, user["id"]),
        )
        if not owned:
            raise HTTPException(status_code=404, detail="conversation not found")
        sql = ("SELECT filename, metadata FROM media"
               " WHERE conversation_id = ? AND user_id = ?")
        params = [conversation_id, user["id"]]
        if message_id:
            sql += " AND message_id = ?"
            params.append(message_id)
        rows = many(conn, sql + " ORDER BY created_at, rowid", params)

    buffer = io.BytesIO()
    used = set()
    # Pictures and archives do not compress; store them as they are.
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        for row in rows:
            path = _safe_path(row["filename"])
            if not path.exists():
                continue
            metadata = json.loads(row["metadata"]) if row["metadata"] else {}
            offered = _entry_name(metadata.get("name"), row["filename"])
            name, stem, suffix = offered, PurePosixPath(offered).stem, PurePosixPath(offered).suffix
            n = 1
            while name in used:
                n += 1
                name = "{}-{}{}".format(stem, n, suffix)
            used.add(name)
            archive.write(str(path), arcname=name)
    if not used:
        raise HTTPException(status_code=404, detail="no media files in this conversation")

    label = "conversation-{}{}.zip".format(
        conversation_id[:8], "-message-{}".format(message_id[:8]) if message_id else "")
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="{}"'.format(label)},
    )


@router.delete("/{conversation_id}", status_code=204)
def delete_conversation(conversation_id: str, user: dict = Depends(current_user)):
    """Remove the conversation, its messages and media, and note its provider thread.

    Rows go in one transaction; files go after it, so a failed unlink can never
    leave a row pointing at nothing. The credit balance is not touched.
    """
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            conv = one(
                conn,
                "SELECT id, provider, provider_thread_url FROM conversations"
                " WHERE id = ? AND user_id = ?",
                (conversation_id, user["id"]),
            )
            if not conv:
                raise HTTPException(status_code=404, detail="conversation not found")
            filenames = [r["filename"] for r in many(
                conn,
                "SELECT filename FROM media WHERE conversation_id = ? AND user_id = ?",
                (conversation_id, user["id"]),
            )]
            conn.execute("DELETE FROM media WHERE conversation_id = ? AND user_id = ?",
                         (conversation_id, user["id"]))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
            if conv["provider_thread_url"]:
                leave_tombstone(conn, conv["provider"], conv["provider_thread_url"])
            conn.execute("COMMIT")
        except Exception:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            raise
    for name in filenames:
        try:
            _safe_path(name).unlink(missing_ok=True)
        except HTTPException:
            continue
    return Response(status_code=204)
