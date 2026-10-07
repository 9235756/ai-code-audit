"""Smoke-check a running server and print a result table.

Usage:
    python scripts/check_endpoints.py [BASE_URL]

BASE_URL defaults to the ``BASE_URL`` environment variable, then to
http://localhost:8080. Exits with code 1 if any check fails.
"""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any

import requests

DEFAULT_BASE_URL = "http://localhost:8080"
TIMEOUT_SECONDS = 10


@dataclass
class Check:
    """One HTTP request and the status code it must return."""

    label: str
    method: str
    path: str
    expected: int
    json: Any = None


@dataclass
class Result:
    """Outcome of a single check."""

    check: Check
    actual: int | str
    body: Any = None

    @property
    def ok(self) -> bool:
        """Whether the actual status matches the expected one."""
        return self.actual == self.check.expected


def run_check(session: requests.Session, base_url: str, check: Check) -> Result:
    """Perform ``check`` and capture the status code or the connection error."""
    try:
        response = session.request(
            check.method,
            base_url + check.path,
            json=check.json,
            timeout=TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        return Result(check, f"ERR {type(exc).__name__}")
    try:
        body = response.json()
    except ValueError:
        body = None
    return Result(check, response.status_code, body)


def create_user(session: requests.Session, base_url: str) -> tuple[Result, int | None]:
    """Create a uniquely named user; return the check result and its id."""
    check = Check(
        "POST /adduser (valid)",
        "POST",
        "/adduser",
        201,
        {"name": f"checker-{uuid.uuid4().hex[:8]}"},
    )
    result = run_check(session, base_url, check)
    user_id = (
        result.body.get("id") if result.ok and isinstance(result.body, dict) else None
    )
    return result, user_id


def build_checks(user_id: int) -> list[Check]:
    """Return the remaining checks that depend on an existing user id."""
    return [
        Check("POST /adduser (empty name)", "POST", "/adduser", 400, {"name": ""}),
        Check("POST /adduser (non-string)", "POST", "/adduser", 400, {"name": 42}),
        Check("POST /adduser (no body)", "POST", "/adduser", 400),
        Check(f"GET /user/{user_id}", "GET", f"/user/{user_id}", 200),
        Check("GET /user/999999999", "GET", "/user/999999999", 404),
        Check("GET /user/1 OR 1=1", "GET", "/user/1%20OR%201=1", 404),
        Check(f"GET /activate/{user_id}", "GET", f"/activate/{user_id}", 200),
        Check("GET /slow", "GET", "/slow", 202),
        Check("GET /wrong", "GET", "/wrong", 500),
    ]


def print_table(results: list[Result]) -> None:
    """Print results as an aligned text table."""
    headers = ("Эндпоинт", "Ожидаемый", "Фактический", "Итог")
    rows = [
        (r.check.label, str(r.check.expected), str(r.actual), "OK" if r.ok else "FAIL")
        for r in results
    ]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    line = "+".join("-" * (w + 2) for w in widths)

    def fmt(cells: tuple[str, ...]) -> str:
        return "|".join(f" {c:<{w}} " for c, w in zip(cells, widths, strict=True))

    print(fmt(headers))
    print(line)
    for row in rows:
        print(fmt(row))


def main(argv: list[str]) -> int:
    """Run all checks against the server and return the process exit code."""
    base_url = argv[1] if len(argv) > 1 else os.environ.get("BASE_URL", DEFAULT_BASE_URL)
    base_url = base_url.rstrip("/")
    print(f"Проверка {base_url}\n")

    with requests.Session() as session:
        results = [
            run_check(session, base_url, Check("GET /health", "GET", "/health", 200))
        ]
        add_result, user_id = create_user(session, base_url)
        results.append(add_result)
        results += [run_check(session, base_url, c) for c in build_checks(user_id or 1)]

    print_table(results)
    failed = sum(not r.ok for r in results)
    print(f"\nИтого: {len(results) - failed}/{len(results)} OK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
