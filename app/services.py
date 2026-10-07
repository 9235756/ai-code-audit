"""Business logic: users, password hashing, active users and background work."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import sqlite3
import threading
from collections import deque
from collections.abc import Iterable, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from app.models import User

logger = logging.getLogger(__name__)

MAX_ACTIVE_USERS = 5
PBKDF2_ALGORITHM = "sha256"
PBKDF2_ITERATIONS = 600_000
SALT_SIZE = 16


# --- users -------------------------------------------------------------------


def create_user(
    conn: sqlite3.Connection, name: str, tags: Iterable[str] | None = None
) -> User:
    """Insert a user with a parameterised query and return it."""
    tag_list = list(tags or [])
    with conn:
        cur = conn.execute(
            "INSERT INTO users (name, tags) VALUES (?, ?)",
            (name, json.dumps(tag_list)),
        )
    return User(id=int(cur.lastrowid or 0), name=name, tags=tag_list)


def get_user(conn: sqlite3.Connection, user_id: int) -> User | None:
    """Return the user with ``user_id`` or ``None`` when it does not exist."""
    row = conn.execute(
        "SELECT id, name, tags FROM users WHERE id = ?", (user_id,)
    ).fetchone()
    return User.from_row(row) if row else None


def get_user_by_name(conn: sqlite3.Connection, name: str) -> User | None:
    """Return the first user called ``name`` or ``None``."""
    row = conn.execute(
        "SELECT id, name, tags FROM users WHERE name = ? ORDER BY id LIMIT 1", (name,)
    ).fetchone()
    return User.from_row(row) if row else None


def is_admin(user: Mapping[str, Any] | None) -> bool:
    """Fail closed: only an explicit ``role == "admin"`` grants admin rights."""
    return isinstance(user, Mapping) and user.get("role") == "admin"


# --- passwords ---------------------------------------------------------------


@dataclass(frozen=True)
class PasswordHash:
    """PBKDF2 hash together with the parameters needed to verify it."""

    salt: bytes
    hash: bytes
    iterations: int


def hash_password(
    password: str, salt: bytes | None = None, iterations: int = PBKDF2_ITERATIONS
) -> PasswordHash:
    """Hash ``password`` with PBKDF2-HMAC-SHA256 and a random salt."""
    salt = salt if salt is not None else os.urandom(SALT_SIZE)
    digest = hashlib.pbkdf2_hmac(
        PBKDF2_ALGORITHM, password.encode("utf-8"), salt, iterations
    )
    return PasswordHash(salt=salt, hash=digest, iterations=iterations)


def verify_password(password: str, stored: PasswordHash) -> bool:
    """Check ``password`` against ``stored`` in constant time."""
    candidate = hash_password(password, stored.salt, stored.iterations)
    return hmac.compare_digest(candidate.hash, stored.hash)


def store_password(
    conn: sqlite3.Connection,
    user_id: int,
    password: str,
    iterations: int = PBKDF2_ITERATIONS,
) -> PasswordHash:
    """Hash and save the password of ``user_id``, replacing any previous one."""
    hashed = hash_password(password, iterations=iterations)
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO passwords (user_id, salt, hash, iterations) "
            "VALUES (?, ?, ?, ?)",
            (user_id, hashed.salt, hashed.hash, hashed.iterations),
        )
    return hashed


def check_password(conn: sqlite3.Connection, user_id: int, password: str) -> bool:
    """Return ``True`` if ``password`` matches the stored hash of ``user_id``."""
    row = conn.execute(
        "SELECT salt, hash, iterations FROM passwords WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row is None:
        return False
    stored = PasswordHash(
        salt=row["salt"], hash=row["hash"], iterations=row["iterations"]
    )
    return verify_password(password, stored)


# --- active users ------------------------------------------------------------


class ActiveUsers:
    """Thread-safe list of the most recently activated user ids."""

    def __init__(self, max_size: int = MAX_ACTIVE_USERS) -> None:
        """Keep at most ``max_size`` ids; older ones are evicted first."""
        self._items: deque[int] = deque(maxlen=max_size)
        self._lock = threading.Lock()

    def set_active(self, user_id: int) -> list[int]:
        """Mark ``user_id`` active and return a snapshot of the list."""
        with self._lock:
            self._items.append(user_id)
            return list(self._items)

    def snapshot(self) -> list[int]:
        """Return a copy of the current list."""
        with self._lock:
            return list(self._items)


# --- background work ---------------------------------------------------------


def heavy_computation(n: int) -> int:
    """CPU-bound stand-in for a slow job: sum of ``0..n-1``."""
    return sum(range(n))


def schedule_heavy_computation(executor: ThreadPoolExecutor, n: int) -> Future[int]:
    """Run :func:`heavy_computation` in ``executor`` and log the outcome."""
    future = executor.submit(heavy_computation, n)
    future.add_done_callback(_log_task_result)
    return future


def _log_task_result(future: Future[int]) -> None:
    exc = future.exception()
    if exc is not None:
        logger.error("slow task failed", exc_info=exc)
    else:
        logger.info("slow task finished: %s", future.result())


def divide(dividend: float, divisor: float) -> float:
    """Divide two numbers; raises ``ZeroDivisionError`` for a zero divisor."""
    return dividend / divisor
