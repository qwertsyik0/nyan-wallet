"""Public Nyan Confessions page and anonymous feed on the Wallet server."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import (
    Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text,
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
MAX_QUESTION_LENGTH = 180
MAX_ID = 2147483647
DEFAULT_QUESTION = "Что ты давно хочешь сказать кому-то из Нян?"
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


class ConfessionSettings(core.Base):
    __tablename__ = "nyan_confession_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pinned_id: Mapped[int | None] = mapped_column(ForeignKey("nyan_confessions.id", ondelete="SET NULL"))
    question: Mapped[str | None] = mapped_column(String(MAX_QUESTION_LENGTH), default=DEFAULT_QUESTION)


class ConfessionModeration(core.Base):
    __tablename__ = "nyan_confession_moderation"
    __table_args__ = (
        Index("ix_nyan_confession_moderation_post", "post_id", "comment_id", "hidden"),
        Index("ix_nyan_confession_moderation_comment", "comment_id", "hidden"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    target_key: Mapped[str] = mapped_column(String(20), unique=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("nyan_confessions.id", ondelete="CASCADE"), nullable=False)
    comment_id: Mapped[int | None] = mapped_column(ForeignKey("nyan_confession_comments.id", ondelete="CASCADE"))
    reported: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class ConfessionReply(core.Base):
    __tablename__ = "nyan_confession_replies"

    comment_id: Mapped[int] = mapped_column(ForeignKey("nyan_confession_comments.id", ondelete="CASCADE"), primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("nyan_confession_comments.id", ondelete="CASCADE"), nullable=False)


def post_visible():
    entry = ConfessionModeration
    return ~select(entry.id).where(entry.post_id == Confession.id, entry.comment_id.is_(None), entry.hidden).exists()


def comment_visible():
    entry = ConfessionModeration
    return ~select(entry.id).where(entry.comment_id == ConfessionComment.id, entry.hidden).exists()


def positive_id(value) -> bool:
    return type(value) is int and 1 <= value <= MAX_ID


def save_settings(session: Session, **values) -> None:
    query = insert(ConfessionSettings).values(id=1, **values)
    session.execute(query.on_conflict_do_update(index_elements=["id"], set_=values))


def owner_only(init_data: str = Header(default="", alias="X-Telegram-Init-Data")) -> None:
    core.require_owner(core.verify_init_data(init_data))


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


def serialize_feed(session: Session, records: Sequence[Confession], pinned_id: int | None = None) -> list[dict]:
    if not records:
        return []
    post_ids = [post.id for post in records]
    reactions = reaction_counts(session, post_ids)
    hearts = set(session.scalars(select(ConfessionOwnerHeart.post_id).where(
        ConfessionOwnerHeart.post_id.in_(post_ids)
    )))
    comment = ConfessionComment
    comments = dict(session.execute(
        select(comment.post_id, func.count()).where(comment.post_id.in_(post_ids), comment_visible()).group_by(comment.post_id)
    ).all())
    return [
        {
            **serialize(post),
            **reactions.get(post.id, {"likes": 0, "dislikes": 0}),
            "comment_count": comments.get(post.id, 0),
            "liked_by_owner": post.id in hearts,
            "pinned": post.id == pinned_id,
        }
        for post in records
    ]


def require_post(session: Session, post_id: int, *, include_hidden: bool = False, lock: bool = False) -> Confession:
    if not positive_id(post_id):
        raise HTTPException(status_code=404, detail="Признание не найдено.")
    query = select(Confession).where(Confession.id == post_id)
    if not include_hidden:
        query = query.where(post_visible())
    post = session.scalar(query.with_for_update() if lock else query)
    if post is None:
        raise HTTPException(status_code=404, detail="Признание не найдено.")
    return post


def require_comment(session: Session, post_id: int, comment_id: int, *, include_hidden: bool = False) -> ConfessionComment:
    query = select(ConfessionComment).where(ConfessionComment.post_id == post_id, ConfessionComment.id == comment_id)
    if not include_hidden:
        query = query.where(comment_visible())
    comment = session.scalar(query)
    if comment is None:
        raise HTTPException(status_code=404, detail="Комментарий не найден.")
    return comment


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
    query = select(Confession).where(post_visible()).order_by(Confession.id.desc()).limit(PAGE_SIZE + 1)
    if before is not None:
        query = query.where(Confession.id < before)

    with core.SessionLocal() as session:
        settings = session.get(ConfessionSettings, 1)
        pinned_id = settings.pinned_id if settings else None
        pinned = None
        if pinned_id is not None:
            query = query.where(Confession.id != pinned_id)
            if before is None:
                pinned = session.scalar(select(Confession).where(Confession.id == pinned_id, post_visible()))
        records = session.scalars(query).all()
        page = records[:PAGE_SIZE]
        next_before = page[-1].id if len(records) > PAGE_SIZE else None
        if pinned is not None:
            page.insert(0, pinned)
        posts = serialize_feed(session, page, pinned_id)
    return {"posts": posts, "before": next_before}


@router.get("/feed/{post_id}")
def get_post(post_id: int, response: Response):
    response.headers["Cache-Control"] = "no-store"
    with core.SessionLocal() as session:
        post = require_post(session, post_id)
        settings = session.get(ConfessionSettings, 1)
        return serialize_feed(session, [post], settings.pinned_id if settings else None)[0]


@router.get("/question")
def get_question(response: Response):
    response.headers["Cache-Control"] = "no-store"
    with core.SessionLocal() as session:
        settings = session.get(ConfessionSettings, 1)
        return {"question": settings.question if settings else DEFAULT_QUESTION}


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
        payload = None
    if not isinstance(payload, dict):
        return error_response(f"Некорректный формат {subject}.", 400)
    return payload


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


@router.get("/owner-heart/access", dependencies=[Depends(owner_only)])
def owner_heart_access():
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


@router.post("/feed/{post_id}/owner-heart", dependencies=[Depends(owner_only)])
async def owner_heart(post_id: int, request: Request):
    payload = await read_payload(request, "реакции")
    if isinstance(payload, Response):
        return payload
    liked = payload.get("liked")
    if not isinstance(liked, bool):
        return error_response("Некорректная реакция.", 400)
    result = await run_in_threadpool(set_owner_heart, post_id, liked)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


def serialize_comments(session: Session, records: Sequence[ConfessionComment]) -> list[dict]:
    if not records:
        return []
    reply = ConfessionReply
    parent = ConfessionComment
    rows = session.execute(
        select(reply.comment_id, reply.parent_id, parent.body)
        .outerjoin(parent, (parent.id == reply.parent_id) & comment_visible())
        .where(reply.comment_id.in_([entry.id for entry in records]))
    )
    parents = {
        comment_id: {"id": parent_id, "body": body[:120] + ("…" if len(body) > 120 else "") if body else None}
        for comment_id, parent_id, body in rows
    }
    return [{**serialize(entry), "reply_to": parents.get(entry.id)} for entry in records]


def count_comments(session: Session, post_id: int) -> int:
    return session.scalar(select(func.count()).select_from(ConfessionComment).where(
        ConfessionComment.post_id == post_id, comment_visible()
    ))


@router.get("/feed/{post_id}/comments")
def comments(post_id: int, response: Response, before: int | None = Query(default=None, ge=1, le=MAX_ID)):
    response.headers["Cache-Control"] = "no-store"
    comment = ConfessionComment
    query = select(comment).where(comment.post_id == post_id, comment_visible()).order_by(comment.id.desc()).limit(PAGE_SIZE + 1)
    if before is not None:
        query = query.where(comment.id < before)
    with core.SessionLocal() as session:
        require_post(session, post_id)
        records = session.scalars(query).all()
        entries = serialize_comments(session, records[:PAGE_SIZE])
        total = count_comments(session, post_id)
    return {"comments": entries, "before": entries[-1]["id"] if len(records) > PAGE_SIZE else None, "total": total}


def store_comment(post_id: int, body: str, parent_id: int | None) -> dict:
    with core.SessionLocal.begin() as session:
        require_post(session, post_id)
        if parent_id is not None:
            require_comment(session, post_id, parent_id)
        comment = ConfessionComment(post_id=post_id, body=body, created_at=core.now_utc())
        session.add(comment)
        session.flush()
        if parent_id is not None:
            session.add(ConfessionReply(comment_id=comment.id, parent_id=parent_id))
            session.flush()
        return {"comment": serialize_comments(session, [comment])[0], "total": count_comments(session, post_id)}


@router.post("/feed/{post_id}/comments", status_code=201)
async def add_comment(post_id: int, request: Request):
    payload = await read_payload(request, "комментария")
    if isinstance(payload, Response):
        return payload
    body = submission_text(payload, MAX_COMMENT_LENGTH)
    parent_id = payload.get("reply_to")
    if not body:
        return error_response("Напиши комментарий длиной до 500 символов.", 400)
    if parent_id is not None and not positive_id(parent_id):
        return error_response("Некорректный комментарий для ответа.", 400)
    result = await run_in_threadpool(store_comment, post_id, body, parent_id)
    return JSONResponse(result, status_code=201, headers={"Cache-Control": "no-store"})


def set_moderation(post_id: int, comment_id: int | None, action: str) -> dict:
    entry = ConfessionModeration
    target = f"post:{post_id}" if comment_id is None else f"comment:{comment_id}"
    with core.SessionLocal.begin() as session:
        public = action == "report"
        require_post(session, post_id, include_hidden=not public, lock=not public)
        if comment_id is not None:
            require_comment(session, post_id, comment_id, include_hidden=not public)

        changes = {
            "report": {"reported": True},
            "dismiss": {"reported": False},
            "hide": {"hidden": True, "reported": False},
            "restore": {"hidden": False},
        }[action]
        query = insert(entry).values(target_key=target, post_id=post_id, comment_id=comment_id, **changes)
        session.execute(query.on_conflict_do_update(
            index_elements=[entry.target_key],
            set_=changes,
            where=~entry.hidden if public else None,
        ))
        if action == "hide" and comment_id is None:
            settings = session.get(ConfessionSettings, 1, with_for_update=True)
            if settings and settings.pinned_id == post_id:
                settings.pinned_id = None
        total = count_comments(session, post_id) if comment_id is not None else None
    return {"ok": True, "total": total}


@router.post("/feed/{post_id}/report")
async def report_post(post_id: int, request: Request):
    payload = await read_payload(request, "жалобы")
    if isinstance(payload, Response):
        return payload
    comment_id = payload.get("comment_id")
    if comment_id is not None and not positive_id(comment_id):
        return error_response("Некорректный комментарий.", 400)
    await run_in_threadpool(set_moderation, post_id, comment_id, "report")
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


@router.get("/owner/moderation", dependencies=[Depends(owner_only)])
def moderation_list(response: Response, before: int | None = Query(default=None, ge=1, le=MAX_ID)):
    response.headers["Cache-Control"] = "no-store"
    entry = ConfessionModeration
    query = (
        select(entry, Confession.body, ConfessionComment.body).join(Confession, Confession.id == entry.post_id)
        .outerjoin(ConfessionComment, ConfessionComment.id == entry.comment_id)
        .where(entry.reported | entry.hidden).order_by(entry.id.desc()).limit(PAGE_SIZE + 1)
    )
    if before is not None:
        query = query.where(entry.id < before)
    with core.SessionLocal() as session:
        rows = session.execute(query).all()
        items = [
            {"id": row.id, "post_id": row.post_id, "comment_id": row.comment_id,
             "body": comment if row.comment_id is not None else post,
             "reported": row.reported, "hidden": row.hidden}
            for row, post, comment in rows[:PAGE_SIZE]
        ]
    return {"items": items, "before": items[-1]["id"] if len(rows) > PAGE_SIZE else None}


@router.post("/owner/moderation", dependencies=[Depends(owner_only)])
async def moderate(request: Request):
    payload = await read_payload(request, "модерации")
    if isinstance(payload, Response):
        return payload
    action = payload.get("action")
    post_id = payload.get("post_id")
    comment_id = payload.get("comment_id")
    if action not in ("hide", "restore", "dismiss") or not positive_id(post_id) or (
        comment_id is not None and not positive_id(comment_id)
    ):
        return error_response("Некорректное действие.", 400)
    result = await run_in_threadpool(set_moderation, post_id, comment_id, action)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


def update_pin(post_id: int, pinned: bool) -> dict:
    with core.SessionLocal.begin() as session:
        require_post(session, post_id, lock=True)
        if pinned:
            save_settings(session, pinned_id=post_id)
        else:
            settings = session.get(ConfessionSettings, 1, with_for_update=True)
            if settings and settings.pinned_id == post_id:
                settings.pinned_id = None
        settings = session.get(ConfessionSettings, 1)
        return {"pinned_id": settings.pinned_id if settings else None}


@router.post("/owner/pin", dependencies=[Depends(owner_only)])
async def pin(request: Request):
    payload = await read_payload(request, "закрепа")
    if isinstance(payload, Response):
        return payload
    if not positive_id(payload.get("post_id")) or not isinstance(payload.get("pinned"), bool):
        return error_response("Некорректный закреп.", 400)
    result = await run_in_threadpool(update_pin, payload["post_id"], payload["pinned"])
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


def update_question(question: str | None) -> dict:
    with core.SessionLocal.begin() as session:
        save_settings(session, question=question)
    return {"question": question}


@router.post("/owner/question", dependencies=[Depends(owner_only)])
async def set_question(request: Request):
    payload = await read_payload(request, "вопроса недели")
    if isinstance(payload, Response):
        return payload
    value = payload.get("body")
    body = submission_text(payload, MAX_QUESTION_LENGTH)
    if not isinstance(value, str) or (value.strip() and not body):
        return error_response("Вопрос должен быть длиной до 180 символов.", 400)
    result = await run_in_threadpool(update_question, body or None)
    return JSONResponse(result, headers={"Cache-Control": "no-store"})


@router.api_route("/{asset}", methods=["GET", "HEAD"], include_in_schema=False)
def asset_file(asset: str):
    if asset not in FILES:
        raise HTTPException(status_code=404)
    path, media_type = FILES[asset]
    return FileResponse(path, media_type=media_type, headers=PAGE_HEADERS)


def register_nyan_confessions(app):
    core.Base.metadata.create_all(core.engine, tables=[
        Confession.__table__, ConfessionReaction.__table__, ConfessionComment.__table__,
        ConfessionOwnerHeart.__table__, ConfessionSettings.__table__,
        ConfessionModeration.__table__, ConfessionReply.__table__,
    ])
    app.include_router(router)
