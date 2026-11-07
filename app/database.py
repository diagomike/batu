"""One database for everything the portal stores: PostgreSQL in production, SQLite on a laptop.

    DATABASE_URL=postgresql://user:pass@host:5432/batu    (Render, Railway, Fly, any Postgres)
    DATABASE_URL=mysql://user:pass@host:3306/batu         (also works; needs `pip install pymysql`)
    (unset)                                                SQLite file var/batu.db

Tables are defined here once; migrations/ (Alembic) creates and upgrades them. The app runs
`migrate()` at start-up, so a fresh database is ready without a manual step.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path

from sqlalchemy import (JSON, Boolean, Column, Float, Integer, LargeBinary, MetaData, String, Table, Text,
                        create_engine, event, inspect)
from sqlalchemy.dialects import mysql, postgresql
from sqlalchemy.engine import Engine

ROOT = Path(__file__).resolve().parent.parent
metadata = MetaData()

Json = JSON().with_variant(postgresql.JSONB(), "postgresql")
Blob = LargeBinary().with_variant(mysql.LONGBLOB(), "mysql")
LongText = Text().with_variant(mysql.LONGTEXT(), "mysql")

# ---------- residents ----------
requests = Table(
    "requests", metadata,
    Column("ref", String(40), primary_key=True),
    Column("kind", String(20), nullable=False),          # report, complaint, booking, application, bill
    Column("service_id", String(80)),
    Column("title", String(300)),
    Column("data", Json, nullable=False),                # what the resident filled in
    Column("status", String(30), nullable=False, index=True),
    Column("amount", Float),
    Column("paid", Boolean, nullable=False, default=False),
    Column("created", String(25), nullable=False, index=True),
    Column("updated", String(25), nullable=False),
    Column("history", Json, nullable=False),             # [{at, status, note}]
)
payments = Table(
    "payments", metadata,
    Column("id", String(20), primary_key=True),
    Column("request_ref", String(40), nullable=False, index=True),
    Column("amount", Float, nullable=False),
    Column("provider", String(20), nullable=False),
    Column("status", String(20), nullable=False),        # pending, paid, failed
    Column("created", String(25), nullable=False),
    Column("receipt", String(20)),
)
subscriptions = Table(
    "subscriptions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("at", String(25), nullable=False),
    Column("channel", String(20), nullable=False),
    Column("contact", String(200), nullable=False),
    Column("topics", String(200)),
)
ask_log = Table(
    "ask_log", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("at", String(25), nullable=False, index=True),
    Column("lang", String(5)),
    Column("question", Text),
    Column("mode", String(20)),
    Column("found", Boolean),
    Column("sources", Json),
    Column("ms", Integer),
)
uploads = Table(  # photos residents attach to reports
    "uploads", metadata,
    Column("name", String(40), primary_key=True),
    Column("content_type", String(40), nullable=False),
    Column("data", Blob, nullable=False),
    Column("created", String(25), nullable=False),
)

# ---------- content and the studio ----------
content_docs = Table(  # one row per content file: site.json, services.json, i18n/om.json ...
    "content_docs", metadata,
    Column("name", String(80), primary_key=True),
    Column("data", Json, nullable=False),
    Column("updated_at", String(26), nullable=False),
    Column("updated_by", String(64), nullable=False),    # "seed" until someone edits it in the studio
    Column("seed_hash", String(40)),                     # hash of the data/ file it was last loaded from
)
content_versions = Table(  # every earlier version, for History and restore
    "content_versions", metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("name", String(80), nullable=False, index=True),
    Column("data", Json, nullable=False),
    Column("saved_at", String(26), nullable=False),
    Column("who", String(64)),
    Column("note", String(300)),
)
media_files = Table(  # photos uploaded in the studio, two sizes each
    "media_files", metadata,
    Column("slug", String(80), primary_key=True),
    Column("size", Integer, primary_key=True),
    Column("content_type", String(40), nullable=False),
    Column("data", Blob, nullable=False),
    Column("updated_at", String(26), nullable=False),
)
studio_users = Table(
    "studio_users", metadata,
    Column("name", String(32), primary_key=True),
    Column("salt", String(64), nullable=False),
    Column("hash", String(128), nullable=False),
    Column("role", String(10), nullable=False),
    Column("created", String(25), nullable=False),
)
settings = Table(
    "settings", metadata,
    Column("key", String(64), primary_key=True),
    Column("value", LongText, nullable=False),
    Column("updated_at", String(26)),
    Column("updated_by", String(64)),
)


# ---------- connection ----------
def url() -> str:
    raw = os.getenv("DATABASE_URL", "").strip()
    if os.getenv("BATU_BUILD") == "1":
        raw = ""  # static builds always use their own throwaway SQLite file, never the live database
    if not raw:
        from . import db  # the SQLite path can be moved by tests and builds (db.DB_PATH)
        Path(db.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{Path(db.DB_PATH).as_posix()}"
    for old, new in (("postgres://", "postgresql+psycopg://"), ("postgresql://", "postgresql+psycopg://"),
                     ("mysql://", "mysql+pymysql://")):
        if raw.startswith(old):
            return new + raw[len(old):]
    return raw


_engine: Engine | None = None
_lock = threading.Lock()


def engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            u = url()
            if u.startswith("sqlite"):
                _engine = create_engine(u, connect_args={"check_same_thread": False, "timeout": 15})

                @event.listens_for(_engine, "connect")
                def _sqlite_pragmas(con, _):
                    con.execute("PRAGMA journal_mode=WAL")
                    con.execute("PRAGMA foreign_keys=ON")
            else:
                _engine = create_engine(u, pool_pre_ping=True, pool_size=5, max_overflow=5, pool_recycle=1800)
        return _engine


def reset():
    """Forget the engine (tests and builds that point DB_PATH elsewhere)."""
    global _engine
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None


def kind() -> str:
    return engine().dialect.name  # sqlite, postgresql, mysql


def migrate() -> None:
    """Bring the database to the latest schema (Alembic). Safe to call on every start."""
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    eng = engine()
    with eng.begin() as conn:
        cfg.attributes["connection"] = conn
        names = set(inspect(conn).get_table_names())
        if "requests" in names and "alembic_version" not in names:
            # A database from before migrations (the old SQLite file): add the new tables, then mark it current.
            metadata.create_all(conn)
            command.stamp(cfg, "head")
        else:
            command.upgrade(cfg, "head")
