import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from flask.testing import FlaskClient

from app import create_app, services
from app.models import MAX_NAME_LENGTH

# --- /health -----------------------------------------------------------------


def test_health_returns_ok(client: FlaskClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok"}


# --- POST /adduser -----------------------------------------------------------


def test_add_user_returns_201_with_id(client: FlaskClient) -> None:
    response = client.post("/adduser", json={"name": "alice"})
    assert response.status_code == 201
    assert response.get_json() == {"status": "created", "id": 1, "name": "alice"}


def test_add_user_strips_name_and_keeps_tags(client: FlaskClient) -> None:
    created = client.post("/adduser", json={"name": "  bob  ", "tags": ["dev"]})
    assert created.get_json()["name"] == "bob"
    user = client.get(f"/user/{created.get_json()['id']}").get_json()
    assert user["tags"] == ["dev"]


def test_add_user_ids_increment(client: FlaskClient) -> None:
    first = client.post("/adduser", json={"name": "a"}).get_json()["id"]
    second = client.post("/adduser", json={"name": "b"}).get_json()["id"]
    assert second == first + 1


@pytest.mark.parametrize(
    "payload",
    [
        {"name": ""},
        {"name": "   "},
        {"name": 123},
        {"name": None},
        {"name": ["alice"]},
        {"name": True},
        {},
        {"name": "x" * (MAX_NAME_LENGTH + 1)},
        {"name": "alice", "tags": "admin"},
        {"name": "alice", "tags": [1, 2]},
        ["alice"],
        "alice",
    ],
)
def test_add_user_rejects_invalid_json(client: FlaskClient, payload: object) -> None:
    response = client.post("/adduser", json=payload)
    assert response.status_code == 400
    assert response.get_json()["error"] == "validation_error"


def test_add_user_rejects_non_json_body(client: FlaskClient) -> None:
    response = client.post("/adduser", data="name=alice", content_type="text/plain")
    assert response.status_code == 400


def test_add_user_rejects_empty_body(client: FlaskClient) -> None:
    response = client.post("/adduser")
    assert response.status_code == 400


def test_add_user_get_method_not_allowed(client: FlaskClient) -> None:
    response = client.get("/adduser")
    assert response.status_code == 405
    assert response.get_json() == {"error": "method_not_allowed"}


# --- GET /user/<uid> ---------------------------------------------------------


def test_get_user_returns_200(client: FlaskClient) -> None:
    uid = client.post("/adduser", json={"name": "alice"}).get_json()["id"]
    response = client.get(f"/user/{uid}")
    assert response.status_code == 200
    assert response.get_json() == {"id": uid, "name": "alice", "tags": []}


def test_get_user_missing_returns_404(client: FlaskClient) -> None:
    response = client.get("/user/999")
    assert response.status_code == 404
    assert response.get_json() == {"error": "not_found"}


@pytest.mark.parametrize("uid", ["abc", "1 OR 1=1", "0 UNION SELECT 1,2,3", "-1"])
def test_get_user_non_integer_id_returns_404(client: FlaskClient, uid: str) -> None:
    client.post("/adduser", json={"name": "alice"})
    response = client.get(f"/user/{uid}")
    assert response.status_code == 404
    assert response.get_json() == {"error": "not_found"}


# --- SQL injection -----------------------------------------------------------


def test_sql_injection_name_is_stored_as_plain_string(
    client: FlaskClient, conn: sqlite3.Connection
) -> None:
    client.post("/adduser", json={"name": "alice"})
    malicious = "x'); DROP TABLE users;--"

    response = client.post("/adduser", json={"name": malicious})
    assert response.status_code == 201
    uid = response.get_json()["id"]

    assert client.get(f"/user/{uid}").get_json()["name"] == malicious
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "users" in tables
    assert conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 2


def test_sql_injection_multi_values_does_not_add_rows(
    client: FlaskClient, conn: sqlite3.Connection
) -> None:
    malicious = "x', '[]'), ('hacked', '[\"admin\"]') --"
    client.post("/adduser", json={"name": malicious})
    rows = conn.execute("SELECT name FROM users").fetchall()
    assert [r["name"] for r in rows] == [malicious]


# --- GET /activate/<uid> -----------------------------------------------------


def test_activate_returns_200_with_list(client: FlaskClient) -> None:
    response = client.get("/activate/7")
    assert response.status_code == 200
    assert response.get_json() == {"active": [7]}


def test_activate_keeps_last_five(client: FlaskClient) -> None:
    for uid in range(1, 8):
        response = client.get(f"/activate/{uid}")
    assert response.get_json() == {"active": [3, 4, 5, 6, 7]}


def test_activate_non_integer_returns_404(client: FlaskClient) -> None:
    assert client.get("/activate/abc").status_code == 404


# --- set_active thread safety -------------------------------------------------


def test_set_active_is_thread_safe_with_100_threads() -> None:
    threads_count = 100
    active = services.ActiveUsers(max_size=threads_count)
    barrier = threading.Barrier(threads_count)
    errors: list[BaseException] = []

    def worker(uid: int) -> None:
        try:
            barrier.wait()
            active.set_active(uid)
        except BaseException as exc:  # collected for the assertion
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(threads_count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    snapshot = active.snapshot()
    assert len(snapshot) == threads_count
    assert sorted(snapshot) == list(range(threads_count))


def test_set_active_bounded_under_concurrency() -> None:
    active = services.ActiveUsers()
    with ThreadPoolExecutor(max_workers=100) as pool:
        results = list(pool.map(active.set_active, range(100)))

    assert all(len(r) <= services.MAX_ACTIVE_USERS for r in results)
    assert len(active.snapshot()) == services.MAX_ACTIVE_USERS


def test_activate_endpoint_under_concurrency(client: FlaskClient) -> None:
    with ThreadPoolExecutor(max_workers=20) as pool:
        codes = list(
            pool.map(lambda i: client.get(f"/activate/{i}").status_code, range(100))
        )
    assert set(codes) == {200}
    assert len(client.get("/activate/1000").get_json()["active"]) == 5


# --- GET /slow ---------------------------------------------------------------


def test_slow_returns_202_immediately(client: FlaskClient) -> None:
    response = client.get("/slow")
    assert response.status_code == 202
    assert response.get_json() == {"status": "scheduled"}


def test_slow_task_runs_in_background() -> None:
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = services.schedule_heavy_computation(pool, 1000)
        assert future.result(timeout=5) == sum(range(1000))


# --- GET /wrong --------------------------------------------------------------


def test_wrong_returns_500_json(client: FlaskClient) -> None:
    response = client.get("/wrong")
    assert response.status_code == 500
    assert response.get_json() == {"msg": "error", "detail": "division by zero"}


def test_unknown_route_returns_json_404(client: FlaskClient) -> None:
    response = client.get("/nope")
    assert response.status_code == 404
    assert response.get_json() == {"error": "not_found"}


# --- passwords and admin check ----------------------------------------------


def test_hash_password_is_salted_and_verifiable() -> None:
    first = services.hash_password("secret", iterations=1000)
    second = services.hash_password("secret", iterations=1000)

    assert first.salt != second.salt
    assert first.hash != second.hash
    assert b"secret" not in first.hash
    assert services.verify_password("secret", first)
    assert not services.verify_password("wrong", first)


def test_store_and_check_password(client: FlaskClient, db_path: Path) -> None:
    uid = client.post("/adduser", json={"name": "alice"}).get_json()["id"]
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        services.store_password(connection, uid, "s3cret", iterations=1000)
        stored = connection.execute("SELECT hash FROM passwords").fetchone()["hash"]
        assert b"s3cret" not in stored
        assert services.check_password(connection, uid, "s3cret")
        assert not services.check_password(connection, uid, "nope")
        assert not services.check_password(connection, uid + 1, "s3cret")
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("user", "expected"),
    [({"role": "admin"}, True), ({"role": "user"}, False), ({}, False), (None, False)],
)
def test_is_admin_fails_closed(user: dict | None, expected: bool) -> None:
    assert services.is_admin(user) is expected


# --- configuration -----------------------------------------------------------


def test_db_path_from_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "nested" / "env.db"
    monkeypatch.setenv("DB_PATH", str(target))

    application = create_app()
    try:
        assert application.config["DB_PATH"] == str(target)
        assert target.exists()
    finally:
        application.extensions["task_executor"].shutdown(wait=True)
