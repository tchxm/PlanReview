"""Active attempts to break coordination: conflicting operations on one task must not
both succeed or corrupt state; unrelated tasks must not block each other."""

import threading
import time

import pytest
from fastapi.testclient import TestClient

from engine import api
from engine.pipeline import Pipeline


@pytest.fixture
def env(tmp_path, monkeypatch):
    p = Pipeline(tmp_path)
    monkeypatch.setattr(api, "pipeline", p)
    return p, TestClient(api.app, raise_server_exceptions=False)


def new(client, text="Increase memory for dev-api Lambda"):
    return client.post("/api/tasks", json={"task": text}).json()


def race(n, fn):
    barrier = threading.Barrier(n)
    out = [None] * n

    def run(i):
        barrier.wait()
        out[i] = fn(i)

    ts = [threading.Thread(target=run, args=(i,)) for i in range(n)]
    [t.start() for t in ts]
    [t.join(60) for t in ts]
    return out


def test_simultaneous_confirms_seal_the_contract_exactly_once(env):
    p, client = env
    t = new(client)
    res = race(8, lambda i: client.post(f"/api/tasks/{t['id']}/confirm", json=t["contract"]))
    codes = sorted(r.status_code for r in res)
    assert codes == [200] + [409] * 7, codes
    stored = p.store.get(t["id"])
    from engine.pipeline import assert_contract_integrity

    assert_contract_integrity(stored)  # the one confirmed contract is intact
    assert [e["kind"] for e in p.store.audit(t["id"])].count("human_confirmation") == 1


def test_simultaneous_edits_prepare_exactly_one_workspace_edit(env):
    p, client = env
    t = new(client)
    client.post(f"/api/tasks/{t['id']}/confirm", json=t["contract"])
    res = race(6, lambda i: client.post(f"/api/tasks/{t['id']}/agent?variant=intended"))
    assert sorted(r.status_code for r in res) == [200] + [409] * 5
    assert [e["kind"] for e in p.store.audit(t["id"])].count("agent_edits") == 1


def test_conflicting_resolve_and_replan_never_leave_stale_approvals(env):
    """A resolution racing a re-evaluation must end in a consistent state: either the
    approval is recorded against the current run, or it is cleared with the new plan."""
    p, client = env
    t = new(client, "Increase memory for dev-api Lambda")
    tid = t["id"]
    client.post(f"/api/tasks/{tid}/confirm", json=t["contract"])
    client.post(f"/api/tasks/{tid}/agent?variant=review")
    for s in ("plan", "canonicalize", "evaluate"):
        assert client.post(f"/api/tasks/{tid}/{s}").status_code == 200
    review = [v["address"] for v in client.get(f"/api/tasks/{tid}").json()["runs"][-1]["verdicts"] if v["verdict"] == "REVIEW"]
    if not review:
        pytest.skip("fixture produced no REVIEW item")

    def work(i):
        if i % 2 == 0:
            return client.post(f"/api/tasks/{tid}/resolve", json={review[0]: "approve"}).status_code
        return client.post(f"/api/tasks/{tid}/evaluate").status_code

    race(6, work)
    run = p.store.get(tid)["runs"][-1]
    assert set(run["resolutions"]) <= set(review)  # never an approval for a non-REVIEW address
    assert run["policy_hash"]


def test_slow_task_does_not_block_other_tasks(env, monkeypatch):
    p, client = env
    a, b = new(client), new(client)
    started, release = threading.Event(), threading.Event()
    real = p.confirm

    def slow_confirm(id, body=None):
        if id == a["id"]:
            started.set()
            release.wait(20)
        return real(id, body)

    monkeypatch.setattr(p, "confirm", slow_confirm)
    t = threading.Thread(target=lambda: client.post(f"/api/tasks/{a['id']}/confirm", json=a["contract"]))
    t.start()
    assert started.wait(10)
    t0 = time.time()
    r = client.post(f"/api/tasks/{b['id']}/confirm", json=b["contract"])  # different task: must not wait for A
    elapsed = time.time() - t0
    release.set()
    t.join(20)
    assert r.status_code == 200 and elapsed < 5, elapsed


def test_reads_are_not_blocked_by_a_running_mutation(env, monkeypatch):
    p, client = env
    a = new(client)
    started, release = threading.Event(), threading.Event()
    real = p.confirm

    def slow(id, body=None):
        started.set()
        release.wait(20)
        return real(id, body)

    monkeypatch.setattr(p, "confirm", slow)
    t = threading.Thread(target=lambda: client.post(f"/api/tasks/{a['id']}/confirm", json=a["contract"]))
    t.start()
    assert started.wait(10)
    t0 = time.time()
    assert client.get(f"/api/tasks/{a['id']}").status_code == 200
    assert client.get("/api/tasks").status_code == 200
    assert time.time() - t0 < 5
    release.set()
    t.join(20)


def test_creating_many_tasks_in_parallel_yields_distinct_intact_tasks(env):
    p, client = env
    res = race(12, lambda i: client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}))
    assert all(r.status_code == 200 for r in res)
    ids = {r.json()["id"] for r in res}
    assert len(ids) == 12 and len(p.store.list()) == 12


# ---- idempotency: network retries must not duplicate tasks -----------------------
def test_retry_with_the_same_key_returns_the_original_task(env):
    p, client = env
    h = {"Idempotency-Key": "retry-key-0001"}
    body = {"task": "Increase memory for dev-api Lambda"}
    a = client.post("/api/tasks", json=body, headers=dict(h, **{"Authorization": client.headers["Authorization"]}))
    b = client.post("/api/tasks", json=body, headers=dict(h, **{"Authorization": client.headers["Authorization"]}))
    assert a.status_code == b.status_code == 200
    assert a.json()["id"] == b.json()["id"] and b.headers["x-idempotent-replay"] == "true"
    assert len(p.store.list()) == 1


def test_simultaneous_retries_create_exactly_one_task(env):
    p, client = env
    auth = {"Authorization": client.headers["Authorization"], "Idempotency-Key": "burst-key-0001"}
    res = race(10, lambda i: client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}, headers=auth))
    assert all(r.status_code == 200 for r in res)
    assert len({r.json()["id"] for r in res}) == 1 and len(p.store.list()) == 1


def test_key_reuse_with_a_different_request_is_rejected(env):
    p, client = env
    auth = {"Authorization": client.headers["Authorization"], "Idempotency-Key": "reuse-key-0001"}
    assert client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}, headers=auth).status_code == 200
    r = client.post("/api/tasks", json={"task": "Set dev-api Lambda memory to 700"}, headers=auth)
    assert r.status_code == 422 and r.json()["detail"]["error"] == "IDEMPOTENCY_KEY_REUSED"
    assert len(p.store.list()) == 1


def test_failed_creation_does_not_consume_the_key(env):
    p, client = env
    auth = {"Authorization": client.headers["Authorization"], "Idempotency-Key": "fail-key-00001"}
    assert client.post("/api/tasks", json={"task": "Delete the production RDS database"}, headers=auth).status_code == 400
    assert client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}, headers=auth).status_code == 200


def test_invalid_key_is_422_and_no_key_means_no_deduplication(env):
    p, client = env
    bad = {"Authorization": client.headers["Authorization"], "Idempotency-Key": "short"}
    assert client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}, headers=bad).status_code == 422
    for _ in range(2):
        assert client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}).status_code == 200
    assert len(p.store.list()) == 2
