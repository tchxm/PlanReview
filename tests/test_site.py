"""PlanBound site API: rule parity with the browser engine, hashes, sessions, evidence chain."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from engine import api, site
from engine.pipeline import Pipeline

CONTRACT = {"environment": "dev", "allowed": ["aws_s3_bucket", "aws_security_group", "aws_iam_role"], "maxBlast": 5, "note": ""}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    site._store.clear()
    yield TestClient(api.app, headers={})
    site._store.clear()


def start(c, contract=CONTRACT):
    s = c.post("/api/site/sessions").json()
    sid = s["sessionId"]
    r = c.post(f"/api/site/sessions/{sid}/confirm", json={"contract": contract, "consent": True})
    assert r.status_code == 200, r.text
    return sid, r.json()


def verdicts(state):
    return {k: v["verdict"] for k, v in state["verdicts"].items()}


def test_fresh_session_matches_browser_init(client):
    s = client.post("/api/site/sessions").json()
    assert len(s["records"]) == 15 and sum(r["seed"] for r in s["records"]) == 12
    assert set(verdicts(s).values()) == {"DENY"} and not s["gateOpen"]
    assert s["metrics"] == {"plansEvaluated": 5, "changesGated": 11, "humanDecisions": 0}


def test_hashes_are_the_browser_algorithms():
    # Values produced by the in-browser engine (verified in tests/browser parity run).
    assert site.fnv("") == "cbf29ce484222325"
    assert site.contract_hash({**CONTRACT, "confirmed": True}) == site.contract_hash({**CONTRACT, "allowed": CONTRACT["allowed"][::-1], "confirmed": True})
    assert len(site.plan_key(site.PLANS["sample-a"])) == 16


@pytest.mark.parametrize("plan,expected", [
    ("sample-a", {"chg_1": "DENY", "chg_2": "REVIEW", "chg_3": "ALLOW"}),
    ("sample-b", {"chg_1": "ALLOW", "chg_2": "ALLOW", "chg_3": "ALLOW", "chg_4": "ALLOW"}),
    ("sample-c", {"chg_1": "DENY", "chg_2": "REVIEW"}),  # db instances are outside the default scope; dev open ingress needs review
])
def test_sample_plans(client, plan, expected):
    sid, _ = start(client)
    r = client.post(f"/api/site/sessions/{sid}/plan", json={"id": plan}).json()
    assert verdicts(r) == expected


def test_review_flow_gate_apply_and_undo(client):
    sid, _ = start(client, {**CONTRACT, "allowed": CONTRACT["allowed"] + ["aws_db_instance"]})
    st = client.post(f"/api/site/sessions/{sid}/plan", json={"id": "sample-c"}).json()
    assert verdicts(st) == {"chg_1": "REVIEW", "chg_2": "REVIEW"} and not st["gateOpen"]
    assert client.post(f"/api/site/sessions/{sid}/apply").json()["ok"] is False
    for cid, ch in (("chg_1", "approved"), ("chg_2", "rejected")):
        assert client.post(f"/api/site/sessions/{sid}/resolve", json={"change_id": cid, "choice": ch}).json()["ok"]
    st = client.get(f"/api/site/sessions/{sid}").json()
    assert st["gateOpen"]
    undone = client.post(f"/api/site/sessions/{sid}/resolve", json={"change_id": "chg_2", "undo": True}).json()
    assert undone["ok"] and not undone["state"]["gateOpen"]
    client.post(f"/api/site/sessions/{sid}/resolve", json={"change_id": "chg_2", "choice": "approved"})
    n = len(client.get(f"/api/site/sessions/{sid}").json()["records"])
    assert client.post(f"/api/site/sessions/{sid}/apply").json()["ok"] is True
    again = client.post(f"/api/site/sessions/{sid}/apply").json()
    assert again["ok"] is False and len(again["state"]["records"]) == n + 2  # idempotent: no duplicate records


def test_resolve_rejects_bad_input_and_non_review(client):
    sid, _ = start(client)
    client.post(f"/api/site/sessions/{sid}/plan", json={"id": "sample-a"})
    for body in ({"change_id": "chg_1", "choice": "approved"}, {"change_id": "chg_2", "choice": "yes"}, {"change_id": "nope", "choice": "approved"}):
        assert client.post(f"/api/site/sessions/{sid}/resolve", json=body).json()["ok"] is False


def test_validation_matches_browser_messages(client):
    sid = client.post("/api/site/sessions").json()["sessionId"]
    bad = client.put(f"/api/site/sessions/{sid}/contract", json={"contract": {**CONTRACT, "allowed": []}})
    assert bad.status_code == 400 and "at least one resource class" in bad.json()["detail"]["message"]
    r = client.post(f"/api/site/sessions/{sid}/plan", json={"id": "x", "changes": [{"id": "a"}]})
    assert r.status_code == 400 and "needs a short resource" in r.json()["detail"]["message"]
    assert client.post(f"/api/site/sessions/{sid}/confirm", json={"contract": CONTRACT}).json()["detail"]["message"].startswith("Confirm the consent")


def test_client_cannot_inject_verdicts_or_gate(client):
    sid, _ = start(client)
    r = client.post(f"/api/site/sessions/{sid}/plan", json={"id": "sample-a", "verdicts": {"chg_1": {"verdict": "ALLOW"}}, "gateOpen": True})
    assert verdicts(r.json())["chg_1"] == "DENY" and r.json()["gateOpen"] is False


def test_unknown_session_and_bad_ids(client):
    assert client.get("/api/site/sessions/" + "0" * 24).status_code == 404
    assert client.get("/api/site/sessions/not-a-session").status_code == 404


def test_chain_verifies_and_detects_tampering(client, tmp_path):
    sid, _ = start(client)
    v = client.get(f"/api/site/sessions/{sid}/evidence/verify").json()
    assert v["ok"] and v["records"] == 18 and v["verified_by"] == "server" and len(v["latest_hash"]) == 64
    db = tmp_path / "site.sqlite"
    con = sqlite3.connect(db)
    st = json.loads(con.execute("select state from site_sessions where id=?", (sid,)).fetchone()[0])
    st["records"][5]["reason"] = "edited"
    con.execute("update site_sessions set state=? where id=?", (json.dumps(st), sid))
    con.commit()
    bad = client.get(f"/api/site/sessions/{sid}/evidence/verify").json()
    assert not bad["ok"] and bad["first_broken"]["index"] == 5
    con.close()


def test_truncated_tail_is_detected(client, tmp_path):
    sid, _ = start(client)
    con = sqlite3.connect(tmp_path / "site.sqlite")
    st = json.loads(con.execute("select state from site_sessions where id=?", (sid,)).fetchone()[0])
    st["records"].pop()
    con.execute("update site_sessions set state=? where id=?", (json.dumps(st), sid))
    con.commit()
    v = client.get(f"/api/site/sessions/{sid}/evidence/verify").json()
    assert not v["ok"]


def test_records_are_bounded(client):
    sid, _ = start(client)
    for _ in range(60):
        client.post(f"/api/site/sessions/{sid}/plan", json={"id": "sample-b"})
    st = client.get(f"/api/site/sessions/{sid}").json()
    assert len(st["records"]) == 200
    assert client.get(f"/api/site/sessions/{sid}/evidence/verify").json()["ok"]


def test_site_is_served_from_the_same_origin(client):
    r = client.get("/")
    assert r.status_code == 200 and "PlanBound" in r.text


def test_cross_origin_mutation_is_blocked(client):
    r = client.post("/api/site/sessions", headers={"Origin": "http://evil.example"})
    assert r.status_code == 403


def test_pipeline_bridge_status_and_guard(client, monkeypatch):
    monkeypatch.setenv("PLANBOUND_PIPELINE", "0")
    assert client.get("/api/site/pipeline/status").json()["enabled"] is False
    assert client.post("/api/site/pipeline/tasks", json={"task": "x"}).status_code == 404  # off => not reachable
    monkeypatch.setenv("PLANBOUND_PIPELINE", "1")
    t = client.post("/api/site/pipeline/tasks", json={"task": "Increase memory for dev-api Lambda"}).json()
    assert t["stage"] == "draft" and t["contract"]["allowed_resource_types"] == ["aws_lambda_function"]
    assert client.post(f"/api/site/pipeline/tasks/{t['id']}/jobs", json={"op": "rm"}).status_code == 400
    assert client.post(f"/api/site/pipeline/tasks/{t['id']}/resolve", json={"resolutions": {"a": "maybe"}}).status_code == 400
    assert client.get("/api/site/pipeline/audit/verify").json()["ok"] is True
