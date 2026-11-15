"""Public Nyan Confessions page and anonymous feed on the Wallet server."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text,
    case, delete, func, select,
)
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Mapped, Session, mapped_column
from starlette.concurrency import run_in_threadpool

from . import backend_app as core

router = APIRouter(prefix="/api/nyan-confessions")
PAGE_SIZE = 20
MAX_BODY_BYTES = 8192
MAX_TEXT_LENGTH = 1000
MAX_COMMENT_LENGTH = 500
REACTION_KEY = re.compile(r"[a-f0-9]{32}")
PUBLIC_ORIGIN = "https://nyan-wallet-bridge.qwertsyik.workers.dev"
ASSETS = Path(__file__).resolve().parent.parent / "assets"
FILES = {
    "style.css": (ASSETS / "nyan-confessions/style.css", "text/css"),
    "confessions.js": (ASSETS / "nyan-confessions/confessions.js", "text/javascript"),
    "nyanik.webp": (ASSETS / "nyan-confessions/nyanik.webp", "image/webp"),
}
PAGE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
        "connect-src 'self'; base-uri 'none'; form-action 'self'"
    ),
}


class Confession(core.Base):
    __tablename__ = "nyan_confessions"
    __table_args__ = (
        CheckConstraint("length(body) BETWEEN 1 AND 1000", name="nyan_confessions_body_length"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ConfessionReaction(core.Base):
    __tablename__ = "nyan_confession_reactions"
    __table_args__ = (
        CheckConstraint("value IN (-1, 1)", name="nyan_confession_reaction_value"),
    )

    post_id: Mapped[int] = mapped_column(ForeignKey("nyan_confessions.id", ondelete="CASCADE"), primary_key=True)
    voter_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[int] = mapped_column(SmallInteger, nullable=False)


class ConfessionOwnerHeart(core.Base):
    __tablename__ = "nyan_confession_owner_hearts"

    post_id: Mapped[int] = mapped_column(ForeignKey("nyan_confessions.id", ondelete="CASCADE"), primary_key=True)


class ConfessionComment(core.Base):
    __tablename__ = "nyan_confession_comments"
    __table_args__ = (
        CheckConstraint("length(body) BETWEEN 1 AND 500", name="nyan_confession_comment_body_length"),
        Index("ix_nyan_confession_comment_post_id_id", "post_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("nyan_confessions.id", ondelete="CASCADE"), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


def serialize(post: Confession | ConfessionComment) -> dict:
    timestamp = post.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return {
        "id": post.id,
        "body": post.body,
        "created_at": int(timestamp.timestamp() * 1000),
    }


def reaction_counts(session: Session, post_ids: Sequence[int]) -> dict[int, dict]:
    reaction = ConfessionReaction
    rows = session.execute(
        select(
            reaction.post_id,
            func.sum(case((reaction.value == 1, 1), else_=0)),
            func.sum(case((reaction.value == -1, 1), else_=0)),
        ).where(reaction.post_id.in_(post_ids)).group_by(reaction.post_id)
    )
    return {post_id: {"likes": likes, "dislikes": dislikes} for post_id, likes, dislikes in rows}


def serialize_feed(session: Session, records: Sequence[Confession]) -> list[dict]:
    if not records:
        return []
    post_ids = [post.id for post in records]
    reactions = reaction_counts(session, post_ids)
    hearts = set(session.scalars(select(ConfessionOwnerHeart.post_id).where(
        ConfessionOwnerHeart.post_id.in_(post_ids)
    )))
    comment = ConfessionComment
    comments = dict(session.execute(
        select(comment.post_id, func.count()).where(comment.post_id.in_(post_ids)).group_by(comment.post_id)
    ).all())
    return [
        {
            **serialize(post),
            **reactions.get(post.id, {"likes": 0, "dislikes": 0}),
            "comment_count": comments.get(post.id, 0),
            "liked_by_owner": post.id in hearts,
        }
        for post in records
    ]


def require_post(session: Session, post_id: int) -> None:
    if session.get(Confession, post_id) is None:
        raise HTTPException(status_code=404, detail="Признание не найдено.")


@router.api_route("", methods=["GET", "HEAD"], include_in_schema=False)
def page():
    return FileResponse(
        ASSETS / "nyan-confessions/index.html",
        media_type="text/html",
        headers=PAGE_HEADERS,
    )


@router.get("/feed")
def feed(response: Response, before: int | None = Query(default=None, ge=1, le=2147483647)):
    response.headers["Cache-Control"] = "no-store"
    query = select(Confession).order_by(Confession.id.desc()).limit(PAGE_SIZE + 1)
    if before is not None:
        query = query.where(Confession.id < before)

    with core.SessionLocal() as session:
        records = session.scalars(query).all()
        posts = serialize_feed(session, records[:PAGE_SIZE])
    return {"posts": posts, "before": posts[-1]["id"] if len(records) > PAGE_SIZE else None}


def store_confession(body: str) -> dict:
    with core.SessionLocal.begin() as session:
        post = Confession(body=body, created_at=core.now_utc())
        session.add(post)
        session.flush()
        return {**serialize(post), "likes": 0, "dislikes": 0, "comment_count": 0, "liked_by_owner": False}


def error_response(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status_code)


async def read_payload(request: Request, subject: str) -> dict | JSONResponse:
    origin = request.headers.get("Origin")
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
        origin and origin not in {PUBLIC_ORIGIN, request_origin}
    ):
        return error_response("Открой форму на сайте Nyan Confessions.", 403)

    if request.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
        return error_response(f"Некорректный формат {subject}.", 415)

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            return error_response("Запрос слишком длинный.", 413)
        raw.extend(chunk)

    try:
        payload = json.loads(raw)
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}


def submission_text(payload: dict, limit: int) -> str:
    value = payload.get("body")
    body = value.strip() if isinstance(value, str) else ""
    try:
        if "\x00" not in body and len(body.encode("utf-16-le")) <= limit * 2:
            return body
    except UnicodeError:
        pass
    return ""


@router.post("/feed", status_code=201)
async def publish(request: Request):
    payload = await read_payload(request, "признания")
    if isinstance(payload, Response):
        return payload
    body = submission_text(payload, MAX_TEXT_LENGTH)
    if not body:
        return error_response("Напиши признание длиной до 1000 символов.", 400)

    post = await run_in_threadpool(store_confession, body)
    return JSONResponse(post, status_code=201, headers={"Cache-Control": "no-store"})


def set_reaction(post_id: int, key: str, value: int) -> dict:
    voter_key = hashlib.sha256(key.encode("ascii")).hexdigest()
    reaction = ConfessionReaction
    with core.SessionLocal.begin() as session:
        require_post(session, post_id)
        if value:
            query = insert(reaction).values(post_id=post_id, voter_key=voter_key, value=value)
            session.execute(query.on_conflict_do_update(
                index_elements=[reaction.post_id, reaction.voter_key],
                set_={"value": query.excluded.value},
            ))
        else:
            session.execute(delete(reaction).where(reaction.post_id == post_id, reaction.voter_key == voter_key))
        counts = reaction_counts(session, [post_id]).get(post_id, {"likes": 0, "dislikes": 0})
    return {**counts, "reaction": value}


@router.post("/feed/{post_id}/reaction")
async def react(post_id: int, request: Request):
    payload = await read_payload(request, "реакции")
    if isinstance(payload, Response):
        return payload
    key = payload.get("key")
    value = payload.get("reaction")
    if not isinstance(key, str) or not REACTION_KEY.fullmatch(key) or type(value) is not int or value not in (-1, 0, 1):
        return error_response("Некорректная реакция.", 400)
    result = await run_in_threadpool(set_reaction, post_id, key, value)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/owner-heart/access")
def owner_heart_access(init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    core.require_owner(core.verify_init_data(init_data))
    return JSONResponse({"owner": True}, headers={"Cache-Control": "no-store"})


def set_owner_heart(post_id: int, liked: bool) -> dict:
    heart = ConfessionOwnerHeart
    with core.SessionLocal.begin() as session:
        require_post(session, post_id)
        if liked:
            session.execute(insert(heart).values(post_id=post_id).on_conflict_do_nothing())
        else:
            session.execute(delete(heart).where(heart.post_id == post_id))
    return {"liked_by_owner": liked}


@router.post("/feed/{post_id}/owner-heart")
async def owner_heart(post_id: int, request: Request, init_data: str = Header(default="", alias="X-Telegram-Init-Data")):
    core.require_owner(core.verify_init_data(init_data))
    payload = await read_payload(request, "реакции")
    if isinstance(payload, Response):
        return payload
    liked = payload.get("liked")
    if not isinstance(liked, bool):
        return error_response("Некорректная реакция.", 400)
    result = await run_in_threadpool(set_owner_heart, post_id, liked)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.get("/feed/{post_id}/comments")
def comments(post_id: int, response: Response, before: int | None = Query(default=None, ge=1, le=2147483647)):
    response.headers["Cache-Control"] = "no-store"
    comment = ConfessionComment
    query = select(comment).where(comment.post_id == post_id).order_by(comment.id.desc()).limit(PAGE_SIZE + 1)
    if before is not None:
        query = query.where(comment.id < before)
    with core.SessionLocal() as session:
        require_post(session, post_id)
        records = session.scalars(query).all()
        entries = [serialize(item) for item in records[:PAGE_SIZE]]
        total = session.scalar(select(func.count()).select_from(comment).where(comment.post_id == post_id))
    return {"comments": entries, "before": entries[-1]["id"] if len(records) > PAGE_SIZE else None, "total": total}


def store_comment(post_id: int, body: str) -> dict:
    with core.SessionLocal.begin() as session:
        require_post(session, post_id)
        comment = ConfessionComment(post_id=post_id, body=body, created_at=core.now_utc())
        session.add(comment)
        session.flush()
        total = session.scalar(select(func.count()).select_from(ConfessionComment).where(ConfessionComment.post_id == post_id))
        return {"comment": serialize(comment), "total": total}


@router.post("/feed/{post_id}/comments", status_code=201)
async def add_comment(post_id: int, request: Request):
    payload = await read_payload(request, "комментария")
    if isinstance(payload, Response):
        return payload
    body = submission_text(payload, MAX_COMMENT_LENGTH)
    if not body:
        return error_response("Напиши комментарий длиной до 500 символов.", 400)
    result = await run_in_threadpool(store_comment, post_id, body)
    return JSONResponse(result, status_code=201, headers={"Cache-Control": "no-store"})


@router.api_route("/{asset}", methods=["GET", "HEAD"], include_in_schema=False)
def asset_file(asset: str):
    if asset not in FILES:
        raise HTTPException(status_code=404)
    path, media_type = FILES[asset]
    return FileResponse(path, media_type=media_type, headers=PAGE_HEADERS)


def register_nyan_confessions(app):
    core.Base.metadata.create_all(core.engine, tables=[
        Confession.__table__, ConfessionReaction.__table__, ConfessionComment.__table__,
        ConfessionOwnerHeart.__table__,
    ])
    app.include_router(router)
