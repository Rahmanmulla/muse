"""STIP backend — database setup.

SQLite WAL at ~/.stip/stip.db (override with STIP_DB_PATH). Naive UTC
datetimes everywhere — SQLite returns naive datetimes, so all timestamps
are naive UTC. (Lesson from Talkies: never store tz-aware and compare naive.)
"""
from __future__ import annotations

import os
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

DB_DIR = Path(os.environ.get("STIP_DATA_DIR", str(Path.home() / ".stip")))
DB_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = os.environ.get("STIP_DB_PATH", str(DB_DIR / "stip.db"))
MEDIA_DIR = DB_DIR / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
    # WAL: concurrent readers while writes proceed; busy-wait instead of locking errors
    pool_pre_ping=True,
)
Base = declarative_base()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA journal_mode=WAL")
        conn.exec_driver_sql("PRAGMA busy_timeout=5000")
    # fresh databases get the full current schema from models;
    # existing databases get v3 additions applied additively below.
    Base.metadata.create_all(engine)
    from migrate import backfill_v3, ensure_additive_schema
    ensure_additive_schema(engine)
    db = SessionLocal()
    try:
        backfill_v3(db)
    finally:
        db.close()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
