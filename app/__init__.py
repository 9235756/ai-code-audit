"""Application factory for the audited and fixed user service."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from app import db
from app.routes import bp
from app.services import ActiveUsers

DEFAULT_SLOW_TASK_N = 10**8
SLOW_TASK_WORKERS = 2


def create_app(config: dict[str, Any] | None = None) -> Flask:
    """Build and configure the Flask application.

    Args:
        config: values overriding the defaults, e.g. ``{"DB_PATH": ...}`` in tests.

    """
    app = Flask(__name__)
    app.config.from_mapping(
        DB_PATH=db.get_db_path(),
        SLOW_TASK_N=DEFAULT_SLOW_TASK_N,
    )
    app.json.sort_keys = False  # type: ignore[attr-defined]
    if config:
        app.config.update(config)

    logging.basicConfig(level=logging.INFO)

    app.extensions["active_users"] = ActiveUsers()
    app.extensions["task_executor"] = ThreadPoolExecutor(
        max_workers=SLOW_TASK_WORKERS, thread_name_prefix="slow-task"
    )

    db.init_app(app)
    app.register_blueprint(bp)
    _register_error_handlers(app)
    return app


def _register_error_handlers(app: Flask) -> None:
    """Return JSON instead of HTML for HTTP and unexpected errors."""

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException) -> tuple[Any, int]:
        code = exc.code or 500
        error = (exc.name or "error").lower().replace(" ", "_")
        return jsonify(error=error), code

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception) -> tuple[Any, int]:
        app.logger.exception("unhandled error", exc_info=exc)
        return jsonify(error="internal_error"), 500
