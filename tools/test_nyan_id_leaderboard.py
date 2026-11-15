"""Integration tests for Nyan ID leaderboard ranking with a local SQLite DB.

Stubs server side-effect modules so no real wallet database or bot is needed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

from sqlalchemy import BigInteger, ForeignKey, Integer, String, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


ROOT = Path(__file__).resolve().parents[1]


def load_leaderboard():
    package = types.ModuleType("server")
    package.__path__ = [str(ROOT / "server")]
    sys.modules["server"] = package

    class Base(DeclarativeBase):
        pass

    class User(Base):
        __tablename__ = "users"
        telegram_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
        username: Mapped[str | None] = mapped_column(String(64), nullable=True)

    class ActivityCheckIn(Base):
        __tablename__ = "activity_checkins"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))

    class UserTaskProgress(Base):
        __tablename__ = "user_task_progress"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
        reward_claimed: Mapped[bool] = mapped_column(nullable=False)

    class AchievementUnlock(Base):
        __tablename__ = "achievement_unlocks"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))

    class InteractiveIdea(Base):
        __tablename__ = "interactive_idea_submissions"
        id: Mapped[int] = mapped_column(Integer, primary_key=True)
        telegram_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.telegram_id"))
        status: Mapped[str] = mapped_column(String(24), nullable=False)

    def fake(name: str, **values):
        module = types.ModuleType(name)
        for key, value in values.items():
            setattr(module, key, value)
        sys.modules[name] = module
        return module

    backend = fake("server.backend_app", Base=Base, User=User)
    package.backend_app = backend
    fake("server.activity", ActivityCheckIn=ActivityCheckIn)
    fake("server.achievements", AchievementUnlock=AchievementUnlock)
    fake("server.daily_tasks", UserTaskProgress=UserTaskProgress)
    fake("server.interactive_ideas", InteractiveIdea=InteractiveIdea)
    spec = importlib.util.spec_from_file_location(
        "server.nyan_experience", ROOT / "server" / "nyan_experience.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["server.nyan_experience"] = module
    spec.loader.exec_module(module)
    return module, Base, User, ActivityCheckIn, UserTaskProgress, AchievementUnlock, InteractiveIdea


def run_tests():
    xp, Base, User, Checkin, Task, Badge, Idea = load_leaderboard()
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all([
            User(telegram_id=10, username="winnerx"),
            User(telegram_id=20, username=None),
            User(telegram_id=30, username="reader_b"),
            User(telegram_id=40, username=None),
        ])
        session.flush()
        session.add_all([Checkin(telegram_id=10) for _ in range(2)])
        session.add_all([Badge(telegram_id=10)])
        session.add_all([Task(telegram_id=10, reward_claimed=True)])
        session.add_all([Task(telegram_id=10, reward_claimed=False)])
        session.add_all([Idea(telegram_id=10, status="approved")])
        session.add_all([Idea(telegram_id=10, status="pending")])
        session.add_all([Checkin(telegram_id=20) for _ in range(20)])
        session.add_all([Checkin(telegram_id=30) for _ in range(20)])
        session.add(xp.NyanExperienceEvent(
            telegram_id=10, kind="quest_completed", event_key="q123",
            xp=70, awarded_by=10, created_at=__import__("datetime").datetime.now(
                __import__("datetime").timezone.utc,
            ),
        ))
        session.flush()

        # Optional Mafia schema: one completed match counts, unfinished does not.
        session.execute(text(
            "CREATE TABLE nyan_mafia_rounds (id INTEGER PRIMARY KEY, phase TEXT, winner TEXT)"
        ))
        session.execute(text(
            "CREATE TABLE nyan_mafia_players (round_id INTEGER, telegram_id BIGINT)"
        ))
        session.execute(text(
            "INSERT INTO nyan_mafia_rounds VALUES (1, 'finished', 'civilians'), "
            "(2, 'day', NULL)"
        ))
        session.execute(text(
            "INSERT INTO nyan_mafia_players VALUES (1, 10), (2, 10)"
        ))
        session.commit()

        ranking = xp.leaderboard_for_user(session, 30, limit=2)
        assert len(ranking["leaders"]) == 2, ranking
        assert ranking["leaders"][0]["name"] == "@winnerx", ranking
        assert ranking["leaders"][0]["xp"] == 185, ranking
        assert ranking["leaders"][0]["place"] == 1, ranking
        assert ranking["leaders"][1]["name"].startswith("Участник "), ranking
        assert ranking["leaders"][1]["xp"] == 100, ranking
        assert ranking["leaders"][1]["place"] == 2, ranking
        assert ranking["me"] == {"place": 2, "xp": 100, "level": 2}, ranking
        assert "telegram_id" not in json.dumps(ranking), "Raw IDs leaked"

        empty = xp.leaderboard_for_user(session, 40, limit=2)
        assert empty["me"] == {"place": None, "xp": 0, "level": 1}
        assert len(empty["leaders"]) == 2

        # The individual XP calculation must agree with the leaderboard.
        assert xp.experience_for_user(session, 10)["total_xp"] == 185

        # Optional Mafia tables can be absent in other deployments.
        session.execute(text("DROP TABLE nyan_mafia_players"))
        session.execute(text("DROP TABLE nyan_mafia_rounds"))
        session.commit()
        without_games = xp.leaderboard_for_user(session, 10, limit=20)
        assert without_games["leaders"][0]["xp"] == 155, without_games

    print("Nyan ID leaderboard SQLite integration: OK")


if __name__ == "__main__":
    run_tests()
