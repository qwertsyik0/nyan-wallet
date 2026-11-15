"""Public Nyan Confessions page and anonymous feed on the Wallet server."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import CheckConstraint, DateTime, Integer, Text, select
from sqlalchemy.orm import Mapped, mapped_column
from starlette.concurrency import run_in_threadpool

from . import backend_app as core

router = APIRouter(prefix="/api/nyan-confessions")
PAGE_SIZE = 20
MAX_BODY_BYTES = 8192
MAX_TEXT_LENGTH = 1000
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


def serialize(post: Confession) -> dict:
    timestamp = post.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return {
        "id": post.id,
        "body": post.body,
        "created_at": int(timestamp.timestamp() * 1000),
    }


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
        posts = [serialize(post) for post in records[:PAGE_SIZE]]
    return {"posts": posts, "before": posts[-1]["id"] if len(records) > PAGE_SIZE else None}


def store_confession(body: str) -> dict:
    with core.SessionLocal.begin() as session:
        post = Confession(body=body, created_at=core.now_utc())
        session.add(post)
        session.flush()
        return serialize(post)


@router.post("/feed", status_code=201)
async def publish(request: Request):
    origin = request.headers.get("Origin")
    request_origin = f"{request.url.scheme}://{request.url.netloc}"
    if request.headers.get("Sec-Fetch-Site") == "cross-site" or (
        origin and origin not in {PUBLIC_ORIGIN, request_origin}
    ):
        return JSONResponse({"error": "Открой форму на сайте Nyan Confessions."}, status_code=403)

    if request.headers.get("Content-Type", "").split(";", 1)[0].strip() != "application/json":
        return JSONResponse({"error": "Некорректный формат признания."}, status_code=415)

    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BODY_BYTES:
            return JSONResponse({"error": "Признание слишком длинное."}, status_code=413)
        raw.extend(chunk)

    try:
        payload = json.loads(raw)
        body = payload.get("body") if isinstance(payload, dict) else None
        body = body.strip() if isinstance(body, str) else ""
        valid = bool(body) and "\x00" not in body and len(body.encode("utf-16-le")) <= MAX_TEXT_LENGTH * 2
    except (ValueError, UnicodeError):
        valid = False
    if not valid:
        return JSONResponse({"error": "Напиши признание длиной до 1000 символов."}, status_code=400)

    post = await run_in_threadpool(store_confession, body)
    return JSONResponse(post, status_code=201, headers={"Cache-Control": "no-store"})


@router.api_route("/{asset}", methods=["GET", "HEAD"], include_in_schema=False)
def asset_file(asset: str):
    if asset not in FILES:
        raise HTTPException(status_code=404)
    path, media_type = FILES[asset]
    return FileResponse(path, media_type=media_type, headers=PAGE_HEADERS)


def register_nyan_confessions(app):
    core.Base.metadata.create_all(core.engine, tables=[Confession.__table__])
    app.include_router(router)
