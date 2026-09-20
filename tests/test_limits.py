"""Request-size cap, rate limiting, pagination and stage-level idempotency."""

import pytest
from fastapi.testclient import TestClient

from engine import api, ratelimit
from engine.pipeline import Pipeline
from tests.conftest import token


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    return TestClient(api.app)


def mk(client, task="Increase dev-api Lambda memory to 1024 MB"):
    return client.post("/api/tasks", json={"task": task}).json()["id"]


def code(r):
    return r.json()["detail"]["error"]


# ------------------------------------------------------------------- size
def test_oversized_body_is_rejected_before_processing(client, monkeypatch):
    monkeypatch.setattr(api, "MAX_BODY", 500)
    r = client.post("/api/tasks", json={"task": "x" * 2000})
    assert r.status_code == 413 and code(r) == "REQUEST_TOO_LARGE"
    assert client.post("/api/tasks", json={"task": "Increase dev-api Lambda memory to 1024 MB"}).status_code == 200


# ------------------------------------------------------------------- rate
def test_rate_limit_per_credential_returns_429_with_retry_after(client, monkeypatch):
    monkeypatch.setattr(api, "LIMITERS", {"read": ratelimit.RateLimiter(3), "write": ratelimit.RateLimiter(0), "ip": ratelimit.RateLimiter(0)})
    alice = {"Authorization": "Bearer " + api.authlib.mint(api._secret(), ["read"], 600, sub="alice")}
    bob = {"Authorization": "Bearer " + api.authlib.mint(api._secret(), ["read"], 600, sub="bob")}
    assert [client.get("/api/tasks", headers=alice).status_code for _ in range(3)] == [200, 200, 200]
    r = client.get("/api/tasks", headers=alice)
    assert r.status_code == 429 and code(r) == "RATE_LIMITED" and int(r.headers["Retry-After"]) >= 1
    assert client.get("/api/tasks", headers=bob).status_code == 200  # another subject is unaffected


def test_ip_limit_applies_but_health_is_exempt(client, monkeypatch):
    monkeypatch.setattr(api, "LIMITERS", {"read": ratelimit.RateLimiter(0), "write": ratelimit.RateLimiter(0), "ip": ratelimit.RateLimiter(2)})
    assert [client.get("/api/tasks").status_code for _ in range(2)] == [200, 200]
    assert client.get("/api/tasks").status_code == 429
    assert client.get("/api/health").status_code == 200


def test_token_bucket_refills():
    rl = ratelimit.RateLimiter(60)  # 1 per second
    assert all(rl.allow("k", now=0)[0] for _ in range(60))
    assert not rl.allow("k", now=0)[0]
    assert rl.allow("k", now=2)[0]


# ------------------------------------------------------------- pagination
def test_task_list_pagination_and_total_header(client):
    ids = [mk(client) for _ in range(3)]
    r = client.get("/api/tasks?limit=2")
    assert [t["id"] for t in r.json()] == ids[::-1][:2] and r.headers["X-Total-Count"] == "3"
    assert [t["id"] for t in client.get("/api/tasks?limit=2&offset=2").json()] == ids[::-1][2:]
    for bad in ("limit=0", "limit=100000", "offset=-1"):
        r = client.get("/api/tasks?" + bad)
        assert r.status_code == 422 and code(r) == "INVALID_PAGINATION"


def test_audit_pagination(client):
    tid = mk(client)
    client.post(f"/api/tasks/{tid}/confirm", json={})
    full = client.get(f"/api/tasks/{tid}/audit").json()
    assert len(full) == 2
    r = client.get(f"/api/tasks/{tid}/audit?limit=1&offset=1")
    assert r.headers["X-Total-Count"] == "2" and [e["id"] for e in r.json()] == [full[1]["id"]]


# ------------------------------------------------------------ idempotency
def test_stage_retry_with_same_key_replays_instead_of_repeating(client):
    tid = mk(client)
    h = {"Idempotency-Key": "confirm-key-0001"}
    first = client.post(f"/api/tasks/{tid}/confirm", json={}, headers=h)
    again = client.post(f"/api/tasks/{tid}/confirm", json={}, headers=h)
    assert first.status_code == again.status_code == 200
    assert again.headers["X-Idempotent-Replay"] == "true" and again.json() == first.json()
    assert [e["kind"] for e in client.get(f"/api/tasks/{tid}/audit").json()].count("human_confirmation") == 1
    # without a key the same retry is (correctly) refused by the state machine
    assert client.post(f"/api/tasks/{tid}/confirm", json={}).status_code == 409


def test_same_key_different_request_is_rejected(client):
    tid = mk(client)
    client.post(f"/api/tasks/{tid}/confirm", json={})
    h = {"Idempotency-Key": "agent-key-000001"}
    assert client.post(f"/api/tasks/{tid}/agent?variant=intended", headers=h).status_code == 200
    r = client.post(f"/api/tasks/{tid}/agent?variant=poisoned", headers=h)
    assert r.status_code == 422 and code(r) == "IDEMPOTENCY_KEY_REUSED"
    assert client.post(f"/api/tasks/{tid}/agent?variant=intended", headers=h).headers["X-Idempotent-Replay"] == "true"


def test_failed_attempt_does_not_consume_the_key(client):
    tid = mk(client)
    h = {"Idempotency-Key": "agent-key-000002"}
    assert client.post(f"/api/tasks/{tid}/agent?variant=intended", headers=h).status_code == 409  # not confirmed yet
    client.post(f"/api/tasks/{tid}/confirm", json={})
    r = client.post(f"/api/tasks/{tid}/agent?variant=intended", headers=h)
    assert r.status_code == 200 and "X-Idempotent-Replay" not in r.headers


def test_keys_are_scoped_per_task_and_stage(client):
    a, b = mk(client), mk(client)
    h = {"Idempotency-Key": "shared-key-00001"}
    assert client.post(f"/api/tasks/{a}/confirm", json={}, headers=h).status_code == 200
    r = client.post(f"/api/tasks/{b}/confirm", json={}, headers=h)
    assert r.status_code == 200 and "X-Idempotent-Replay" not in r.headers


def test_invalid_key_format(client):
    tid = mk(client)
    r = client.post(f"/api/tasks/{tid}/confirm", json={}, headers={"Idempotency-Key": "short"})
    assert r.status_code == 422 and code(r) == "INVALID_IDEMPOTENCY_KEY"
