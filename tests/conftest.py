import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def app(db_path: Path) -> Iterator[Flask]:
    application = create_app(
        {"TESTING": True, "DB_PATH": str(db_path), "SLOW_TASK_N": 1000}
    )
    yield application
    application.extensions["task_executor"].shutdown(wait=True)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    return app.test_client()


@pytest.fixture
def conn(db_path: Path, app: Flask) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    yield connection
    connection.close()
