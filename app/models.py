"""Domain models and request validation."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

MAX_NAME_LENGTH = 100


class ValidationError(ValueError):
    """Raised when client input does not match the expected shape."""


@dataclass(frozen=True)
class User:
    """A stored user."""

    id: int
    name: str
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> User:
        """Build a user from a ``users`` table row, decoding JSON tags."""
        return cls(id=row["id"], name=row["name"], tags=json.loads(row["tags"]))

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation."""
        return asdict(self)


@dataclass(frozen=True)
class AddUserRequest:
    """Validated body of ``POST /adduser``."""

    name: str
    tags: list[str] = field(default_factory=list)

    @classmethod
    def from_json(cls, payload: Any) -> AddUserRequest:
        """Validate a decoded JSON body.

        Raises:
            ValidationError: if the body is not an object, ``name`` is missing,
                not a string, blank or too long, or ``tags`` is not a list of
                strings.

        """
        if not isinstance(payload, dict):
            raise ValidationError("body must be a JSON object")

        name = payload.get("name")
        if not isinstance(name, str):
            raise ValidationError("name must be a string")
        name = name.strip()
        if not name:
            raise ValidationError("name must not be empty")
        if len(name) > MAX_NAME_LENGTH:
            raise ValidationError(f"name must be at most {MAX_NAME_LENGTH} characters")

        tags = payload.get("tags", [])
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            raise ValidationError("tags must be a list of strings")

        return cls(name=name, tags=list(tags))
