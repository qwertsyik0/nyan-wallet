"""NYAN WORLD: owner-controlled season budgets and moderated written decisions."""
from __future__ import annotations
import json
from html import escape
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import UUID
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (MetaData, Table, Column, Integer, BigInteger, String, Text,
                        DateTime, UniqueConstraint, select)
from sqlalchemy.exc import IntegrityError, NoSuchTableError
from server import backend_app as core

router = APIRouter(prefix="/api/world", tags=["NYAN WORLD"])
m = MetaData()
settings = Table("nw_settings", m, Column("id", Integer, primary_key=True),
                 Column("active_season_id", Integer, nullable=True))
seasons = Table("nw_seasons", m, Column("id", Integer, primary_key=True),
    Column("name", String(120), nullable=False), Column("currency", String(32), nullable=False),
    Column("status", String(20), nullable=False), Column("rules", Text, nullable=False),
    Column("chat_url", String(300), nullable=False), Column("created_at", DateTime(timezone=True), nullable=False))
countries = Table("nw_countries", m, Column("id", Integer, primary_key=True),
    Column("season_id", Integer, nullable=False), Column("name", String(120), nullable=False),
    Column("leader", String(160), nullable=False), Column("player_id", BigInteger, nullable=True),
    Column("budget", BigInteger, nullable=False), Column("income", BigInteger, nullable=False),
    Column("expense", BigInteger, nullable=False), Column("debt", BigInteger, nullable=False),
    Column("frozen", Integer, nullable=False), Column("indicators", Text, nullable=False),
    Column("notes", Text, nullable=False),
    UniqueConstraint("season_id", "name", name="uq_nw_country_name"),
    UniqueConstraint("season_id", "player_id", name="uq_nw_player_country"))
requests = Table("nw_requests", m, Column("id", Integer, primary_key=True),
    Column("season_id", Integer, nullable=False), Column("country_id", Integer, nullable=False),
    Column("author_id", BigInteger, nullable=False), Column("kind", String(24), nullable=False),
    Column("title", String(160), nullable=False), Column("body", Text, nullable=False),
    Column("status", String(24), nullable=False), Column("revision", Integer, nullable=False),
    Column("comment", Text, nullable=False), Column("effects", Text, nullable=False),
    Column("due_at", String(40), nullable=False), Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False))
history = Table("nw_request_history", m, Column("id", Integer, primary_key=True),
    Column("request_id", Integer, nullable=False), Column("actor_id", BigInteger, nullable=False),
    Column("body", Text, nullable=False), Column("created_at", DateTime(timezone=True), nullable=False))
ledger = Table("nw_ledger", m, Column("id", Integer, primary_key=True),
    Column("season_id", Integer, nullable=False), Column("country_id", Integer, nullable=False),
    Column("delta", BigInteger, nullable=False), Column("balance_after", BigInteger, nullable=False),
    Column("reason", Text, nullable=False), Column("group_key", String(100), nullable=False),
    Column("reversal_of", Integer, nullable=True, unique=True),
    Column("actor_id", BigInteger, nullable=False), Column("created_at", DateTime(timezone=True), nullable=False))
audit = Table("nw_audit", m, Column("id", Integer, primary_key=True),
    Column("operation_id", String(36), nullable=False, unique=True),
    Column("actor_id", BigInteger, nullable=False), Column("kind", String(40), nullable=False),
    Column("payload", Text, nullable=False), Column("created_at", DateTime(timezone=True), nullable=False))
notices = Table("nw_notices", m, Column("id", Integer, primary_key=True),
    Column("user_id", BigInteger, nullable=False), Column("body", Text, nullable=False),
    Column("is_read", Integer, nullable=False), Column("created_at", DateTime(timezone=True), nullable=False))
WORLD_CHAT_URL = "https://t.me/+Zi1PggBzzJ9hZDEy"
def registration_approved(c, r, co):
    season = row(c, seasons, r["season_id"])
    url = season["chat_url"] or WORLD_CHAT_URL
    user = c.execute(select(core.User.__table__).where(
        core.User.telegram_id == r["author_id"])).mappings().one_or_none()
    user = dict(user) if user else {}
    name = ("@" + user["username"].lstrip("@")) if user.get("username") else (
        " ".join(str(user.get(k) or "") for k in ("first_name", "last_name")).strip()
        or str(r["author_id"]))
    message = (f"Уважаемый {name}, ваша заявка на должность руководителя государства "
               f"{co['name']} одобрена!\n\nДобро пожаловать в NYAN WORLD. "
               "Вступите в чат по кнопке ниже.")
    # Use the approval transaction so a failed assignment never sends an invite.
    try:
        outbox = Table("telegram_relay_outbox", MetaData(), autoload_with=c)
    except NoSuchTableError:
        fail("Очередь Telegram не настроена. Одобрение не сохранено", 503)
    body = "NYAN_TG_RICH_V1:" + pack({
        "text": escape(message),
        "buttons": [{"text": "Вступить в чат", "url": url}],
    })
    c.execute(outbox.insert().values(
        source_key=f"nyan-world:registration-approved:{r['id']}",
        chat_id=r["author_id"], body=body, state="pending", attempts=0, created_at=now()))
    notify(c, r["author_id"], message + "\n" + url)

LIMIT = 10**15
STATES = {"draft", "registration", "active", "paused", "finished"}
KINDS = {"decision", "announcement", "transfer", "registration"}
def now(): return datetime.now(timezone.utc)
def pack(v): return json.dumps(v, ensure_ascii=False, default=str, allow_nan=False)
def fail(message, code=400): raise HTTPException(code, message)
def integer(v, name, lo=-LIMIT, hi=LIMIT):
    if type(v) is not int or not lo <= v <= hi: fail(f"{name}: требуется целое число от {lo} до {hi}")
    return v
def string(v, name, maximum=5000, required=True):
    if not isinstance(v, str) or len(v.strip()) > maximum or (required and not v.strip()):
        fail(f"Проверь поле: {name}")
    return v.strip()
def indicators(v):
    if not isinstance(v, dict) or len(v) > 30: fail("Допустимо до 30 показателей")
    return {string(k, "название показателя", 80): integer(n, "значение показателя") for k,n in v.items()}
def auth(raw): return core.verify_init_data(raw or "")
def owner(user): core.require_owner(user)
def row(c,t,id):
    v=c.execute(select(t).where(t.c.id==id)).mappings().one_or_none()
    if v is None: fail("Запись не найдена",404)
    return dict(v)
def notify(c,uid,body):
    if uid: c.execute(notices.insert().values(user_id=uid,body=body,is_read=0,created_at=now()))
def request_event(c,r,uid):
    c.execute(history.insert().values(request_id=r["id"],actor_id=uid,body=pack(r),created_at=now()))
def money(c,co,delta,reason,key,uid,reversal=None):
    delta=integer(delta,"сумма")
    balance=integer(co["budget"]+delta,"остаток бюджета",0)
    c.execute(countries.update().where(countries.c.id==co["id"]).values(budget=balance))
    co["budget"]=balance
    c.execute(ledger.insert().values(season_id=co["season_id"],country_id=co["id"],
        delta=delta,balance_after=balance,reason=reason,group_key=key,
        reversal_of=reversal,actor_id=uid,created_at=now()))
def effects(v):
    if not isinstance(v,dict) or set(v)-{"budget_delta","indicators","income","expense","debt","recipient_id","transfer_amount"}:
        fail("Некорректные последствия")
    out={"budget_delta":integer(v.get("budget_delta",0),"изменение бюджета"),
         "indicators":indicators(v.get("indicators",{}))}
    for k in ("income","expense","debt"):
        if k in v: out[k]=integer(v[k],k,0)
    if v.get("recipient_id") is not None:
        out["recipient_id"]=integer(v["recipient_id"],"страна получателя",1)
        out["transfer_amount"]=integer(v.get("transfer_amount"),"сумма перевода",1)
    return out
def apply_effects(c,r,uid,key):
    co=row(c,countries,r["country_id"])
    e=effects(json.loads(r["effects"]))
    if e["budget_delta"]: money(c,co,e["budget_delta"],f"Заявка #{r['id']}: {r['title']}",key,uid)
    if "recipient_id" in e:
        target=row(c,countries,e["recipient_id"])
        if target["id"]==co["id"] or target["season_id"]!=co["season_id"]: fail("Некорректная страна получателя")
        money(c,co,-e["transfer_amount"],f"Перевод по заявке #{r['id']}",key,uid)
        money(c,target,e["transfer_amount"],f"Перевод по заявке #{r['id']}",key,uid)
        notify(c,target["player_id"],f"Получен перевод по заявке #{r['id']}")
    values={k:e[k] for k in ("income","expense","debt") if k in e}
    values["indicators"]=pack({**json.loads(co["indicators"]),**e["indicators"]})
    c.execute(countries.update().where(countries.c.id==co["id"]).values(**values))
    c.execute(requests.update().where(requests.c.id==r["id"]).values(status="completed",updated_at=now()))
    r.update(status="completed",updated_at=now())
    request_event(c,r,uid)
    notify(c,co["player_id"],f"Последствия заявки #{r['id']} применены. {r['comment']}")

class Action(BaseModel):
    model_config=ConfigDict(extra="forbid")
    operation_id: UUID
    kind: str=Field(min_length=1,max_length=40)
    data: dict=Field(default_factory=dict)

def perform(c,user,p):
    uid=int(user["id"]); d=p.data; key=str(p.operation_id)
    player_ops={"submit","resubmit","withdraw","read_notices"}
    if p.kind not in player_ops: owner(user)
    if p.kind=="read_notices":
        c.execute(notices.update().where(notices.c.user_id==uid).values(is_read=1))
        return
    if p.kind in {"submit","resubmit","withdraw"}:
        if p.kind=="submit":
            co=row(c,countries,integer(d.get("country_id"),"страна",1))
            season=row(c,seasons,co["season_id"])
            if co["season_id"]!=c.execute(select(settings.c.active_season_id)).scalar_one(): fail("Этот сезон не выбран")
            kind=d.get("kind","decision")
            if kind not in KINDS: fail("Неизвестный вид заявки")
            if kind=="registration":
                if season["status"] not in {"registration","active"} or co["player_id"] is not None: fail("Регистрация закрыта или страна занята")
                existing=c.execute(select(countries.c.id).where(countries.c.season_id==season["id"],countries.c.player_id==uid)).first()
                if existing: fail("За тобой уже закреплена страна")
                pending=c.execute(select(requests.c.id).where(requests.c.season_id==season["id"],requests.c.author_id==uid,requests.c.kind=="registration",requests.c.status.in_(["submitted","needs_revision","approved"]))).first()
                if pending: fail("Заявка на страну уже отправлена")
            else:
                if season["status"]!="active" or co["frozen"]: fail("Подача действий сейчас приостановлена")
                if co["player_id"]!=uid: fail("Это не твоя страна",403)
            pending=c.execute(select(requests.c.id).where(requests.c.author_id==uid,requests.c.status=="submitted")).all()
            if len(pending)>=20: fail("Дождись рассмотрения предыдущих заявок")
            result=c.execute(requests.insert().values(season_id=season["id"],country_id=co["id"],author_id=uid,
                kind=kind,title=string(d.get("title"),"заголовок",160),body=string(d.get("body"),"описание",12000),
                status="submitted",revision=1,comment="",effects="{}",due_at="",created_at=now(),updated_at=now()))
            r=row(c,requests,result.inserted_primary_key[0]); request_event(c,r,uid)
            notify(c,core.OWNER_TELEGRAM_ID,f"Новая заявка NYAN WORLD #{r['id']}: {co['name']}")
        else:
            r=row(c,requests,integer(d.get("id"),"заявка",1))
            if r["author_id"]!=uid: fail("Нет доступа",403)
            co=row(c,countries,r["country_id"]); season=row(c,seasons,r["season_id"])
            if p.kind=="withdraw":
                if r["status"] not in {"submitted","needs_revision"}: fail("Эту заявку уже нельзя отозвать")
                r.update(status="cancelled",updated_at=now())
            else:
                if r["status"]!="needs_revision": fail("Заявка не возвращена на доработку")
                if season["status"] not in {"registration","active"} or co["frozen"]: fail("Сезон приостановлен")
                if r["kind"]!="registration" and co["player_id"]!=uid: fail("Ты больше не управляешь этой страной",403)
                r.update(title=string(d.get("title"),"заголовок",160),body=string(d.get("body"),"описание",12000),
                         revision=r["revision"]+1,status="submitted",updated_at=now())
            c.execute(requests.update().where(requests.c.id==r["id"]).values(**{k:r[k] for k in ("title","body","revision","status","updated_at")}))
            request_event(c,r,uid)
        return
    if p.kind=="season":
        values=dict(name=string(d.get("name"),"название",120),
            currency=string(d.get("currency"),"валюта",32),status=d.get("status","draft"),
            rules=string(d.get("rules",""),"правила",20000,False),
            chat_url=string(d.get("chat_url",""),"ссылка на чат",300,False))
        if values["status"] not in STATES: fail("Неизвестный статус сезона")
        if values["chat_url"] and not values["chat_url"].startswith("https://t.me/"): fail("Нужна ссылка https://t.me/")
        if d.get("id"):
            old=row(c,seasons,integer(d["id"],"сезон",1))
            c.execute(seasons.update().where(seasons.c.id==old["id"]).values(**values))
            sid=old["id"]
        else:
            sid=c.execute(seasons.insert().values(**values,created_at=now())).inserted_primary_key[0]
        if d.get("select",False): c.execute(settings.update().where(settings.c.id==1).values(active_season_id=sid))
        return
    if p.kind=="select_season":
        sid=integer(d.get("id"),"сезон",1); row(c,seasons,sid)
        c.execute(settings.update().where(settings.c.id==1).values(active_season_id=sid)); return
    if p.kind=="country":
        sid=integer(d.get("season_id"),"сезон",1); row(c,seasons,sid)
        player=d.get("player_id")
        if player is not None:
            integer(player,"Telegram ID",1)
            if c.execute(select(core.User.telegram_id).where(core.User.telegram_id==player)).first() is None:
                fail("Игрок должен сначала открыть Nyan Wallet")
        values=dict(name=string(d.get("name"),"страна",120),leader=string(d.get("leader",""),"руководитель",160,False),
            player_id=player,income=integer(d.get("income",0),"доход",0),expense=integer(d.get("expense",0),"расход",0),
            debt=integer(d.get("debt",0),"долг",0),frozen=int(bool(d.get("frozen",False))),
            indicators=pack(indicators(d.get("indicators",{}))),notes=string(d.get("notes",""),"заметки",10000,False))
        if d.get("id"):
            old=row(c,countries,integer(d["id"],"страна",1))
            if old["season_id"]!=sid: fail("Страну нельзя переносить между сезонами")
            c.execute(countries.update().where(countries.c.id==old["id"]).values(**values))
            if old["player_id"]!=player:
                notify(c,old["player_id"],f"Управление страной {old['name']} завершено")
                notify(c,player,f"Ты назначен руководителем страны {values['name']}")
        else:
            cid=c.execute(countries.insert().values(season_id=sid,budget=0,**values)).inserted_primary_key[0]
            co=row(c,countries,cid)
            opening=integer(d.get("opening_budget",0),"стартовый бюджет",0)
            if opening: money(c,co,opening,"Стартовый бюджет",key,uid)
            notify(c,player,f"Тебе назначена страна {values['name']}")
        return
    if p.kind in {"budget","transfer","cycle"}:
        co=row(c,countries,integer(d.get("country_id"),"страна",1))
        reason=string(d.get("reason"),"основание операции",1000)
        if p.kind=="budget":
            money(c,co,integer(d.get("delta"),"сумма"),reason,key,uid)
        elif p.kind=="cycle":
            money(c,co,co["income"]-co["expense"],reason,key,uid)
        else:
            target=row(c,countries,integer(d.get("recipient_id"),"получатель",1))
            amount=integer(d.get("amount"),"сумма",1)
            if target["id"]==co["id"] or target["season_id"]!=co["season_id"]: fail("Некорректный получатель")
            money(c,co,-amount,reason,key,uid); money(c,target,amount,reason,key,uid)
            notify(c,target["player_id"],f"В бюджет поступило {amount}. {reason}")
        notify(c,co["player_id"],f"Бюджет обновлён: {co['budget']}. {reason}"); return
    if p.kind=="reverse":
        entry=row(c,ledger,integer(d.get("id"),"операция",1))
        reason=string(d.get("reason"),"причина исправления",1000)
        group=c.execute(select(ledger).where(ledger.c.group_key==entry["group_key"]).order_by(ledger.c.id)).mappings().all()
        if any(e["reversal_of"] is not None for e in group): fail("Операцию исправления нельзя отменять повторно")
        if c.execute(select(ledger.c.id).where(ledger.c.reversal_of.in_([e["id"] for e in group]))).first():
            fail("Операция уже исправлена")
        totals={}
        for e in group: totals[e["country_id"]]=totals.get(e["country_id"],0)-e["delta"]
        for cid,delta in totals.items():
            co=row(c,countries,cid); integer(co["budget"]+delta,"остаток после исправления",0)
        for e in reversed(group): money(c,row(c,countries,e["country_id"]),-e["delta"],reason,key,uid,e["id"])
        return
    if p.kind=="review":
        r=row(c,requests,integer(d.get("id"),"заявка",1))
        if r["status"] not in {"submitted","approved","in_progress","needs_revision"}: fail("Заявка уже завершена")
        status=d.get("status")
        if status not in {"needs_revision","rejected","approved","in_progress","cancelled"}: fail("Неизвестное решение")
        comment=string(d.get("comment",""),"комментарий",5000,status in {"needs_revision","rejected"})
        e=effects(d.get("effects",{}))
        due=string(d.get("due_at",""),"срок",40,False)
        if due:
            try:
                date=datetime.fromisoformat(due.replace("Z","+00:00"))
                if date.tzinfo is None: fail("Укажи часовой пояс срока")
            except ValueError: fail("Некорректная дата")
        r.update(status=status,comment=comment,effects=pack(e),due_at=due,updated_at=now())
        c.execute(requests.update().where(requests.c.id==r["id"]).values(**{k:r[k] for k in ("status","comment","effects","due_at","updated_at")}))
        if r["kind"]=="registration" and status=="approved":
            co=row(c,countries,r["country_id"])
            if co["player_id"] not in (None,r["author_id"]): fail("Страна уже занята")
            c.execute(countries.update().where(countries.c.id==co["id"]).values(player_id=r["author_id"]))
            r.update(status="completed");c.execute(requests.update().where(requests.c.id==r["id"]).values(status="completed"))
            registration_approved(c,r,co)
        request_event(c,r,uid)
        if not (r["kind"]=="registration" and status=="approved"):
            notify(c,r["author_id"],f"Заявка #{r['id']}: {r['status']}. {comment}")
        return
    if p.kind=="apply":
        r=row(c,requests,integer(d.get("id"),"заявка",1))
        if r["kind"]=="registration" or r["status"] not in {"approved","in_progress"}: fail("Нет одобренного действия для применения")
        apply_effects(c,r,uid,key); return
    fail("Неизвестное действие")

@router.post("/actions")
def action(p:Action,x_telegram_init_data:str=Header(default="",alias="X-Telegram-Init-Data")):
    user=auth(x_telegram_init_data)
    if len(pack(p.data))>40000: fail("Слишком большой запрос")
    try:
        with core.engine.begin() as c:
            c.execute(select(settings).where(settings.c.id==1).with_for_update()).one()
            previous=c.execute(select(audit).where(audit.c.operation_id==str(p.operation_id))).mappings().one_or_none()
            if previous:
                if previous["actor_id"]!=int(user["id"]) or previous["kind"]!=p.kind or previous["payload"]!=pack(p.data):
                    fail("Ключ операции уже использован",409)
                return {"ok":True,"repeated":True}
            perform(c,user,p)
            c.execute(audit.insert().values(operation_id=str(p.operation_id),actor_id=user["id"],kind=p.kind,payload=pack(p.data),created_at=now()))
    except IntegrityError: fail("Конфликт: страна, игрок или операция уже зарегистрированы",409)
    return {"ok":True}

@router.get("/state")
def state(season_id:int|None=None,x_telegram_init_data:str=Header(default="",alias="X-Telegram-Init-Data")):
    user=auth(x_telegram_init_data); uid=int(user["id"]); admin=core.is_owner(uid)
    with core.engine.connect() as c:
        sid=season_id if admin and season_id else c.execute(select(settings.c.active_season_id)).scalar_one()
        season=row(c,seasons,sid) if sid else None
        cs=[dict(r) for r in c.execute(select(countries).where(countries.c.season_id==sid).order_by(countries.c.name)).mappings()]
        own=next((r for r in cs if r["player_id"]==uid),None)
        if season:
            season["chat_url"]=(season["chat_url"] or WORLD_CHAT_URL) if admin or own else ""
        for co in cs:
            co["indicators"]=json.loads(co["indicators"])
            co["occupied"]=co["player_id"] is not None
            if not admin and (not own or co["id"]!=own["id"]):
                for key in ("budget","income","expense","debt","notes","indicators","player_id"): co.pop(key,None)
        rs=select(requests).where(requests.c.season_id==sid)
        if not admin: rs=rs.where(requests.c.author_id==uid)
        result_requests=[dict(r) for r in c.execute(rs.order_by(requests.c.id.desc()).limit(300)).mappings()]
        for r in result_requests: r["effects"]=json.loads(r["effects"])
        ls=select(ledger).where(ledger.c.season_id==sid)
        if not admin: ls=ls.where(ledger.c.country_id==own["id"] if own else ledger.c.id==-1)
        return {"ok":True,"is_owner":admin,"season":season,"active_season_id":c.execute(select(settings.c.active_season_id)).scalar_one(),
            "seasons":[dict(r) for r in c.execute(select(seasons).order_by(seasons.c.id.desc())).mappings()] if admin else [],
            "countries":cs,"my_country_id":own["id"] if own else None,"requests":result_requests,
            "ledger":[dict(r) for r in c.execute(ls.order_by(ledger.c.id.desc()).limit(300)).mappings()],
            "audit":[dict(r) for r in c.execute(select(audit).order_by(audit.c.id.desc()).limit(200)).mappings()] if admin else [],
            "notices":[dict(r) for r in c.execute(select(notices).where(notices.c.user_id==uid).order_by(notices.c.id.desc()).limit(50)).mappings()]}

@router.get("/requests/{request_id}/history")
def request_history(request_id:int,x_telegram_init_data:str=Header(default="",alias="X-Telegram-Init-Data")):
    user=auth(x_telegram_init_data)
    with core.engine.connect() as c:
        r=row(c,requests,request_id)
        if not core.is_owner(user["id"]) and r["author_id"]!=user["id"]: fail("Нет доступа",403)
        return {"ok":True,"items":[dict(x) for x in c.execute(select(history).where(history.c.request_id==request_id).order_by(history.c.id)).mappings()]}

def register_world(app):
    m.create_all(core.engine)
    with core.engine.begin() as c:
        if c.execute(select(settings.c.id).where(settings.c.id==1)).first() is None:
            c.execute(settings.insert().values(id=1,active_season_id=None))
    app.include_router(router)
