"""Database connection layer (SQLite via the standard library).

* One connection per request, stored on flask.g and closed on teardown.
* isolation_level=None  -> we control transactions explicitly.
* transaction() uses BEGIN IMMEDIATE so the write lock is taken up-front;
  two people redeeming the same code at once are serialised by SQLite.
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from flask import current_app, g

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
TS_FORMAT = "%Y-%m-%d %H:%M:%S"


def now_str(offset_minutes: int = 0, offset_days: int = 0) -> str:
    t = datetime.now(timezone.utc) + timedelta(minutes=offset_minutes, days=offset_days)
    return t.strftime(TS_FORMAT)


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, isolation_level=None, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE_PATH"])
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


@contextmanager
def transaction(db: sqlite3.Connection):
    """BEGIN IMMEDIATE ... COMMIT, rolling back on any exception."""
    db.execute("BEGIN IMMEDIATE")
    try:
        yield db
    except BaseException:
        db.execute("ROLLBACK")
        raise
    else:
        db.execute("COMMIT")


def init_db(path: str):
    conn = connect(path)
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        conn.executescript(f.read())
    conn.close()
