"""SQLite access: connection helpers, per-request connection and schema setup."""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from flask import Flask, current_app, g

DEFAULT_DB_PATH = "data/app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT    NOT NULL,
    tags TEXT    NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS passwords (
    user_id    INTEGER PRIMARY KEY REFERENCES users (id) ON DELETE CASCADE,
    salt       BLOB    NOT NULL,
    hash       BLOB    NOT NULL,
    iterations INTEGER NOT NULL
);
"""


def get_db_path() -> str:
    """Return the database path from the ``DB_PATH`` environment variable."""
    return os.environ.get("DB_PATH", DEFAULT_DB_PATH)


def open_connection(db_path: str) -> sqlite3.Connection:
    """Open a new SQLite connection with rows accessible by column name.

    The parent directory is created when missing, so a fresh volume works
    out of the box.
    """
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def connect(db_path: str) -> Iterator[sqlite3.Connection]:
    """Yield a connection, commit on success, roll back on error, always close."""
    conn = open_connection(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(db_path: str) -> None:
    """Create tables if they do not exist yet."""
    with connect(db_path) as conn:
        conn.executescript(SCHEMA)


def get_db() -> sqlite3.Connection:
    """Return the connection bound to the current request, opening it lazily."""
    if "db" not in g:
        g.db = open_connection(current_app.config["DB_PATH"])
    return g.db


def close_db(_exc: BaseException | None = None) -> None:
    """Close the request connection; registered as a teardown callback."""
    conn: sqlite3.Connection | None = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_app(app: Flask) -> None:
    """Create the schema and register connection teardown for ``app``."""
    init_db(app.config["DB_PATH"])
    app.teardown_appcontext(close_db)
