"""HTTP endpoints."""

from __future__ import annotations

import logging

from flask import Blueprint, Response, current_app, jsonify, request

from app import services
from app.db import get_db
from app.models import AddUserRequest, ValidationError

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__)

ResponseWithStatus = tuple[Response, int]


@bp.post("/adduser")
def add_user() -> ResponseWithStatus:
    """Create a user from ``{"name": str, "tags": [str]?}``."""
    try:
        payload = AddUserRequest.from_json(request.get_json(silent=True))
    except ValidationError as exc:
        return jsonify(error="validation_error", detail=str(exc)), 400

    user = services.create_user(get_db(), payload.name, payload.tags)
    return jsonify(status="created", id=user.id, name=user.name), 201


@bp.get("/user/<int:uid>")
def get_user(uid: int) -> ResponseWithStatus:
    """Return a user by id or 404."""
    user = services.get_user(get_db(), uid)
    if user is None:
        return jsonify(error="not_found"), 404
    return jsonify(user.to_dict()), 200


@bp.get("/activate/<int:uid>")
def activate(uid: int) -> ResponseWithStatus:
    """Mark a user as active and return the most recent active ids."""
    active_users: services.ActiveUsers = current_app.extensions["active_users"]
    return jsonify(active=active_users.set_active(uid)), 200


@bp.get("/slow")
def slow() -> ResponseWithStatus:
    """Schedule the heavy job in the background and answer immediately."""
    services.schedule_heavy_computation(
        current_app.extensions["task_executor"], current_app.config["SLOW_TASK_N"]
    )
    return jsonify(status="scheduled"), 202


@bp.get("/wrong")
def wrong() -> ResponseWithStatus:
    """Demonstrate explicit error handling with a JSON 500 response."""
    try:
        services.divide(1, 0)
    except ZeroDivisionError as exc:
        logger.warning("handled error in /wrong: %s", exc)
        return jsonify(msg="error", detail=str(exc)), 500
    return jsonify(msg="unreachable"), 200


@bp.get("/health")
def health() -> ResponseWithStatus:
    """Liveness check that also verifies the database answers."""
    get_db().execute("SELECT 1").fetchone()
    return jsonify(status="ok"), 200
