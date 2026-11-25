#!/usr/bin/env python3
"""Fill the six agreed NYAN WORLD countries without changing Russia, USA or existing countries."""
import json
import os
from pathlib import Path
import subprocess
import sys
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL

# Fictional first-season presets agreed with the owner, not real economic statistics.
PRESETS = [
    ("Китай", "Си Цзиньпин", 2400, 1900, 18000, (80,90,65,85),
     "Игровые направления: промышленность, экспорт, инфраструктурные проекты и международная торговля.\n\nРазвитие производства требует ресурсов и устойчивых торговых связей. Последствия государственных решений определяет организатор."),
    ("Франция", "Эмманюэль Макрон", 1700, 1350, 14000, (65,75,80,80),
     "Игровые направления: дипломатия, энергетика, промышленность и международные инициативы.\n\nВозможности развития связаны с внутренними реформами и сотрудничеством с другими государствами. Последствия решений определяет организатор."),
    ("Германия", "Фридрих Мерц", 2000, 1600, 16000, (75,85,55,85),
     "Игровые направления: промышленность, экспорт, технологии и экономические соглашения.\n\nДля развития важны обеспечение производства энергией и доступ к внешним рынкам. Последствия государственных решений определяет организатор."),
    ("Великобритания", "Энди Бёрнем", 1800, 1450, 14500, (70,80,60,80),
     "Игровые направления: финансы, международная торговля, дипломатия и инвестиционные проекты.\n\nРазвитие зависит от выбранной внутренней политики и международного сотрудничества. Последствия государственных решений определяет организатор."),
    ("Турция", "Реджеп Тайип Эрдоган", 1500, 1150, 12500, (65,65,55,70),
     "Игровые направления: торговля, транспортные проекты, региональная дипломатия и посредничество.\n\nГосударство может развивать сотрудничество с разными политическими объединениями. Последствия государственных решений определяет организатор."),
    ("Индия", "Нарендра Моди", 1900, 1500, 15000, (70,75,55,60),
     "Игровые направления: развитие внутреннего рынка, технологии, промышленность и самостоятельная дипломатия.\n\nВозможности роста связаны с улучшением инфраструктуры и обеспечением экономики энергией. Последствия государственных решений определяет организатор."),
]
INDICATORS = ("стабильность", "экономика", "энергетика", "инфраструктура")

def normalized(name):
    return " ".join(name.casefold().replace("ё", "е").split())

def seed(engine, owner_id, backup=None):
    from sqlalchemy import MetaData, Table, select
    meta = MetaData()
    t = {n: Table(n, meta, autoload_with=engine, resolve_fks=False)
         for n in ("nw_settings", "nw_seasons", "nw_countries", "nw_ledger", "nw_audit")}
    settings, seasons, countries, ledger, audit = (t[n] for n in
        ("nw_settings", "nw_seasons", "nw_countries", "nw_ledger", "nw_audit"))
    result = []
    with engine.begin() as c:
        setting = c.execute(select(settings).where(settings.c.id == 1).with_for_update()).mappings().one_or_none()
        if not setting or not setting["active_season_id"]:
            raise RuntimeError("текущий сезон не выбран; включи галочку в настройках сезона")
        sid = setting["active_season_id"]
        season = c.execute(select(seasons).where(seasons.c.id == sid)).mappings().one_or_none()
        if not season or season["status"] == "finished":
            raise RuntimeError("текущий сезон не найден или завершён")
        existing = [dict(r) for r in c.execute(select(countries).where(countries.c.season_id == sid)).mappings()]
        names = {normalized(r["name"]) for r in existing}
        if not names.intersection({"россия", "российская федерация"}) or not names.intersection({
                "сша", "соединенные штаты", "соединенные штаты америки"}):
            raise RuntimeError("в текущем сезоне нет России и США; проверь, какой сезон выбран. Ничего не изменено")
        if backup:
            backup({"season": dict(season), "countries_before": existing})
        for name, leader, income, expense, opening, scores, notes in PRESETS:
            if normalized(name) in names:
                result.append((name, "уже существует, без изменений"))
                continue
            stamp = datetime.now(timezone.utc)
            key = str(uuid5(NAMESPACE_URL, f"nyan-world/countries-20261125/{sid}/{name}"))
            if c.execute(select(audit.c.id).where(audit.c.operation_id == key)).first():
                raise RuntimeError(f"история страны {name} уже есть, но страна отсутствует; автоматическое повторное начисление остановлено")
            values = dict(season_id=sid, name=name, leader=leader, player_id=None,
                          budget=opening, income=income, expense=expense, debt=0, frozen=0,
                          indicators=json.dumps(dict(zip(INDICATORS,scores)),ensure_ascii=False), notes=notes)
            cid = c.execute(countries.insert().values(**values)).inserted_primary_key[0]
            c.execute(ledger.insert().values(season_id=sid, country_id=cid, delta=opening,
                balance_after=opening, reason="Стартовый бюджет", group_key=key, reversal_of=None,
                actor_id=owner_id, created_at=stamp))
            payload = {**values, "id":cid, "opening_budget":opening,
                       "indicators":dict(zip(INDICATORS,scores)), "source":"owner_authorized_presets_20261125"}
            c.execute(audit.insert().values(operation_id=key, actor_id=owner_id, kind="country",
                payload=json.dumps(payload,ensure_ascii=False), created_at=stamp))
            result.append((name, f"добавлена, бюджет {opening}, доход {income}, расход {expense}"))
    return season["name"], result

def service_value(name):
    return subprocess.check_output(["systemctl","show","nyan-wallet","-p",name,"--value"],text=True).strip()

def main():
    if os.geteuid() != 0:
        raise RuntimeError("запусти под root на VPS кошелька")
    if service_value("ActiveState") != "active":
        raise RuntimeError("сервис кошелька не запущен")
    root = Path(service_value("WorkingDirectory"))
    if not root.is_absolute() or not (root/"server/backend_app.py").is_file():
        raise RuntimeError("папка API не найдена")
    for folder in (root/".venv", root/"venv"):
        python = folder/"bin/python"
        if python.is_file():
            if Path(sys.prefix).resolve() != folder.resolve():
                os.execv(str(python),[str(python),str(Path(__file__).resolve())])
            break
    pid = service_value("MainPID")
    if not pid.isdigit() or int(pid) < 1:
        raise RuntimeError("процесс API не найден")
    env = {k.decode():v.decode() for item in Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
           if b"=" in item for k,v in [item.split(b"=",1)]}
    from dotenv import dotenv_values
    cfg = {**dotenv_values(root/".env"), **env}
    url = cfg.get("DATABASE_URL") or ""
    if not url.startswith(("postgres://","postgresql://","postgresql+psycopg://")):
        raise RuntimeError("PostgreSQL активного API не найден")
    owner_id = int(cfg.get("OWNER_TELEGRAM_ID") or 0)
    if owner_id <= 0:
        raise RuntimeError("OWNER_TELEGRAM_ID не найден")
    for prefix in ("postgres://","postgresql://"):
        if url.startswith(prefix):
            url = url.replace(prefix,"postgresql+psycopg://",1)
            break
    saved = []
    def backup(snapshot):
        folder = root/".world-backups"/("countries-"+datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f"))
        folder.mkdir(parents=True,mode=0o700)
        path = folder/"before.json"
        fd = os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,"w") as f:
            json.dump(snapshot,f,ensure_ascii=False,indent=2,default=str)
        saved.append(path)
    from sqlalchemy import create_engine
    engine = create_engine(url)
    try:
        season, results = seed(engine,owner_id,backup)
        print("Сезон:",season)
        for name, state in results:
            print(name+": "+state)
        print("Россия и США сохранены без изменений.")
        print("Игроки не назначены, действия стран не приостановлены.")
        if saved: print("Снимок до добавления:",saved[-1])
    finally:
        engine.dispose()

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        if type(error).__module__.startswith("sqlalchemy"):
            raise SystemExit("ошибка базы данных; добавление отменено, изменения не сохранены")
        raise SystemExit("ошибка: "+str(error))
