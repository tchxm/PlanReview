"""Explicit regression tests for the non-negotiable rules that previously had no dedicated
test at the API level (policy staleness, DENY approval through the API, gate bypass)."""

import shutil

import pytest
from fastapi.testclient import TestClient

from engine import api, evaluator
from engine.pipeline import Pipeline


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    return TestClient(api.app, raise_server_exceptions=False)


def run_to_evaluated(client, variant):
    t = client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}).json()
    tid = t["id"]
    assert client.post(f"/api/tasks/{tid}/confirm", json=t["contract"]).status_code == 200
    assert client.post(f"/api/tasks/{tid}/agent?variant={variant}").status_code == 200
    for stage in ("plan", "canonicalize", "evaluate"):
        assert client.post(f"/api/tasks/{tid}/{stage}").status_code == 200
    return tid


def verdicts(client, tid):
    return {v["address"]: v["verdict"] for v in client.get(f"/api/tasks/{tid}").json()["runs"][-1]["verdicts"]}


def err(r):
    return r.json()["detail"]["error"]


def test_deny_cannot_be_approved_through_the_api(client):
    tid = run_to_evaluated(client, "poisoned")
    denied = [a for a, v in verdicts(client, tid).items() if v == "DENY"]
    assert denied
    for a in denied:
        r = client.post(f"/api/tasks/{tid}/resolve", json={a: "approve"})
        assert r.status_code == 409 and err(r) == "RESOLUTION_NOT_ALLOWED"
    assert client.get(f"/api/tasks/{tid}").json()["runs"][-1]["resolutions"] == {}


def test_gate_stays_closed_and_never_spawns_terraform_apply_via_api(client, monkeypatch):
    tid = run_to_evaluated(client, "poisoned")
    spawned = []
    real = __import__("subprocess").run
    monkeypatch.setattr("engine.gate.run_tree", lambda *a, **k: spawned.append(a) or real(*a, **k))
    r = client.post(f"/api/tasks/{tid}/apply")
    assert r.status_code == 200
    assert r.json()["runs"][-1]["apply_result"]["status"] == "BLOCKED" and not spawned


def test_policy_change_invalidates_stale_evaluations(client, monkeypatch, tmp_path):
    tid = run_to_evaluated(client, "poisoned")
    review = [a for a, v in verdicts(client, tid).items() if v == "REVIEW"]
    changed = tmp_path / "security.cedar"
    shutil.copy(evaluator.POLICY, changed)
    changed.write_text(changed.read_text() + "\n// policy edited after evaluation\n")
    monkeypatch.setattr(evaluator, "POLICY", changed)
    r = client.post(f"/api/tasks/{tid}/apply")
    assert r.status_code == 409 and err(r) == "POLICY_CHANGED"
    if review:
        r = client.post(f"/api/tasks/{tid}/resolve", json={review[0]: "approve"})
        assert r.status_code == 409 and err(r) == "POLICY_CHANGED"
    # re-evaluating under the new policy is the only way forward
    assert client.post(f"/api/tasks/{tid}/evaluate").status_code == 200


def test_new_plan_clears_earlier_review_approvals(client):
    tid = run_to_evaluated(client, "review")
    review = [a for a, v in verdicts(client, tid).items() if v == "REVIEW"]
    if not review:
        pytest.skip("fixture produced no REVIEW item")
    assert client.post(f"/api/tasks/{tid}/resolve", json={review[0]: "approve"}).status_code == 200
    assert client.get(f"/api/tasks/{tid}").json()["runs"][-1]["resolutions"]
    for stage in ("agent?variant=review", "plan", "canonicalize", "evaluate"):
        assert client.post(f"/api/tasks/{tid}/{stage}").status_code == 200
    assert client.get(f"/api/tasks/{tid}").json()["runs"][-1]["resolutions"] == {}
