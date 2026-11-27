"""Owner-edited World briefing; draft changes never leak into the public feed."""
import json
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, Text, select
from sqlalchemy.exc import IntegrityError

from . import backend_app as core
from . import nyan_world as world

router = APIRouter(prefix="/api/world/news", tags=["World news"])
m = MetaData()
posts = Table(
    "nw_news_posts", m,
    Column("id", Integer, primary_key=True),
    Column("seed_key", String(80), unique=True),
    Column("category", String(120), nullable=False),
    Column("title", String(160), nullable=False),
    Column("body", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("published_revision", Integer),
    Column("published_content", Text),
    Column("published_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)
SEED = Path(__file__).with_name("world_news_seed.json")


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: UUID
    kind: str = Field(max_length=20)
    id: int | None = Field(default=None, gt=0, strict=True)
    expected_revision: int | None = Field(default=None, gt=0, strict=True)
    category: str | None = Field(default=None, max_length=120)
    title: str | None = Field(default=None, max_length=160)
    body: str | None = Field(default=None, max_length=12000)


def owner(raw):
    user = core.verify_init_data(raw or "")
    core.require_owner(user)
    return user


def content(category, title, body):
    values = {}
    for key, value in (("category", category), ("title", title), ("body", body)):
        if not isinstance(value, str) or not value.strip():
            raise HTTPException(400, "Заполни рубрику, заголовок и текст")
        values[key] = value.strip()
    values["category"] = values["category"].replace("•", "//").replace("·", "//")
    return values


def seed_existing():
    """Import each legacy article once. Reinstalling never overwrites edits."""
    items = json.loads(SEED.read_text(encoding="utf-8"))
    with core.engine.begin() as conn:
        conn.execute(select(world.settings).where(world.settings.c.id == 1).with_for_update()).one()
        for item in items:
            if conn.execute(select(posts.c.id).where(posts.c.seed_key == item["seed_key"])).first():
                continue
            values = content(item["category"], item["title"], item["body"])
            stamp = world.now()
            conn.execute(posts.insert().values(
                seed_key=item["seed_key"], **values, revision=1,
                published_revision=1, published_content=world.pack(values),
                published_at=stamp, created_at=stamp, updated_at=stamp,
            ))


@router.get("/feed")
def feed(response: Response):
    response.headers["Cache-Control"] = "no-store"
    with core.engine.connect() as conn:
        rows = conn.execute(select(posts).where(
            posts.c.published_content.is_not(None)
        ).order_by(posts.c.id.desc())).mappings()
        items = [
            {"id": r["id"], **json.loads(r["published_content"])}
            for r in rows
        ]
    return {"ok": True, "items": items}


@router.get("/editor")
def editor(response: Response, x_telegram_init_data: str = Header(default="")):
    owner(x_telegram_init_data)
    response.headers["Cache-Control"] = "no-store"
    with core.engine.connect() as conn:
        items = [dict(r) for r in conn.execute(select(posts).order_by(posts.c.id.desc())).mappings()]
    for item in items:
        item["is_published"] = item["published_content"] is not None
        item["has_changes"] = item["revision"] != item["published_revision"]
        item.pop("published_content")
        item.pop("seed_key")
    return {"ok": True, "items": items}


@router.post("/actions")
def action(p: Action, x_telegram_init_data: str = Header(default="")):
    user = owner(x_telegram_init_data)
    payload = p.model_dump(mode="json", exclude={"operation_id"})
    if p.kind not in {"save", "publish", "unpublish"}:
        raise HTTPException(400, "Неизвестное действие")
    key = str(p.operation_id)
    audit_payload = {"input": payload}
    try:
        with core.engine.begin() as conn:
            conn.execute(select(world.settings).where(world.settings.c.id == 1).with_for_update()).one()
            prior = conn.execute(select(world.audit).where(world.audit.c.operation_id == key)).mappings().first()
            if prior:
                previous = json.loads(prior["payload"])
                if (prior["actor_id"] != user["id"] or prior["kind"] != "news:" + p.kind
                        or previous.get("input") != payload):
                    raise HTTPException(409, "Ключ операции уже использован")
                return {"ok": True, "id": previous["id"], "repeated": True}
            row = None
            if p.id is not None:
                row = conn.execute(select(posts).where(posts.c.id == p.id).with_for_update()).mappings().first()
                if row is None:
                    raise HTTPException(404, "Новость не найдена")
                if row["revision"] != p.expected_revision:
                    raise HTTPException(409, "Новость уже изменена. Обнови список перед сохранением")
            elif p.kind != "save":
                raise HTTPException(400, "Сначала сохрани черновик")
            stamp = world.now()
            if p.kind == "save":
                values = content(p.category, p.title, p.body)
                if row is None:
                    rid = conn.execute(posts.insert().values(
                        **values, revision=1, created_at=stamp, updated_at=stamp,
                    )).inserted_primary_key[0]
                else:
                    rid = row["id"]
                    conn.execute(posts.update().where(posts.c.id == rid).values(
                        **values, revision=row["revision"] + 1, updated_at=stamp,
                    ))
            else:
                rid = row["id"]
                if p.kind == "publish":
                    values = content(row["category"], row["title"], row["body"])
                    conn.execute(posts.update().where(posts.c.id == rid).values(
                        published_content=world.pack(values), published_at=stamp,
                        published_revision=row["revision"] + 1, revision=row["revision"] + 1,
                        updated_at=stamp,
                    ))
                else:
                    conn.execute(posts.update().where(posts.c.id == rid).values(
                        published_content=None, published_revision=None,
                        revision=row["revision"] + 1, updated_at=stamp,
                    ))
            audit_payload["id"] = rid
            conn.execute(world.audit.insert().values(
                operation_id=key, actor_id=user["id"], kind="news:" + p.kind,
                payload=world.pack(audit_payload), created_at=stamp,
            ))
        return {"ok": True, "id": rid}
    except IntegrityError:
        raise HTTPException(409, "Конфликт сохранения. Обнови список и проверь новость")


def register_world_news(app):
    m.create_all(core.engine)
    seed_existing()
    app.include_router(router)
