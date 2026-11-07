"""Database connection layer (SQLite).

Connection string: the SQLite file at DB_PATH (see .env). One connection per request,
opened in autocommit mode so transactions are explicit via `tx()`.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from flask import current_app, g

SCHEMA = Path(__file__).with_name("schema.sql")


def connect(path):
    conn = sqlite3.connect(path, timeout=15, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


def init_db(path):
    conn = connect(path)
    conn.executescript(SCHEMA.read_text())
    conn.close()


def get():
    if "db" not in g:
        g.db = connect(current_app.config["DB_PATH"])
    return g.db


def close(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


@contextmanager
def tx(conn):
    """Write transaction. BEGIN IMMEDIATE takes the write lock up front, so two
    simultaneous redemptions of one code are serialised and the second one fails."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        conn.execute("ROLLBACK")
        raise


def row(conn, sql, *args):
    r = conn.execute(sql, args).fetchone()
    return dict(r) if r else None


def rows(conn, sql, *args):
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def scalar(conn, sql, *args):
    return conn.execute(sql, args).fetchone()[0]
