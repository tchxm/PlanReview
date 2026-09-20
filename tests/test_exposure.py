"""Normal API responses must not expose paths, full Terraform output or raw plans.
Raw evidence is available only through the evidence-scoped endpoint."""

import re

import pytest
from fastapi.testclient import TestClient

from engine import api
from engine.pipeline import Pipeline
from tests.conftest import token

FORBIDDEN_KEYS = {"workspace", "plan_path", "raw_path", "plan_stdout", "raw_plan", "terraform", "log"}
PATH_RE = re.compile(r"[A-Za-z]:[\\/]|/(?:home|Users|tmp|var)/")


def walk(obj, path=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield path + "/" + str(k), k, v
            yield from walk(v, path + "/" + str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def assert_clean(payload, where):
    for p, k, v in walk(payload):
        assert k not in FORBIDDEN_KEYS, f"{where}: forbidden key {p}"
        if isinstance(v, str):
            assert not PATH_RE.search(v), f"{where}: path-like value at {p}: {v[:80]}"


@pytest.fixture(scope="module")
def flow(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("exposure")
    old = api.pipeline
    api.pipeline = Pipeline(tmp)
    client = TestClient(api.app)
    try:
        t = client.post("/api/tasks", json={"task": "Increase memory for dev-api Lambda"}).json()
        tid = t["id"]
        steps = {"create": t}
        steps["confirm"] = client.post(f"/api/tasks/{tid}/confirm", json=t["contract"]).json()
        for name, url in [("agent", f"/api/tasks/{tid}/agent?variant=intended"), ("plan", f"/api/tasks/{tid}/plan"), ("canonicalize", f"/api/tasks/{tid}/canonicalize"), ("evaluate", f"/api/tasks/{tid}/evaluate"), ("apply", f"/api/tasks/{tid}/apply")]:
            r = client.post(url)
            assert r.status_code == 200, (name, r.text)
            steps[name] = r.json()
        yield client, tid, steps, str(tmp)
    finally:
        api.pipeline = old


def test_every_action_response_is_clean(flow):
    client, tid, steps, tmp = flow
    for name, body in steps.items():
        assert_clean(body, name)
        assert tmp not in str(body)


def test_reads_are_clean(flow):
    client, tid, steps, tmp = flow
    for path in (f"/api/tasks/{tid}", "/api/tasks", f"/api/tasks/{tid}/audit"):
        r = client.get(path)
        assert r.status_code == 200
        assert_clean(r.json(), path)
        assert tmp not in r.text


def test_safe_plan_view_still_carries_what_the_ui_needs(flow):
    client, tid, steps, _ = flow
    run = client.get(f"/api/tasks/{tid}").json()["runs"][-1]
    assert run["plan_hash"] and run["raw_hash"] and run["policy_hash"]
    assert run["canonical"] and run["verdicts"]
    assert run["plan_summary"] == {"total": 1, "create": 0, "update": 1, "delete": 0, "replace": 0, "other": 0}
    assert run["raw_evidence_available"] is True
    assert run["apply_result"]["status"] == "BLOCKED"


def test_audit_keeps_the_chain_but_not_the_raw_payload(flow):
    client, tid, _, _ = flow
    kinds = [e["kind"] for e in client.get(f"/api/tasks/{tid}/audit").json()]
    assert kinds == ["draft", "human_confirmation", "agent_edits", "plan", "canonical", "verdicts", "apply_result"]
    edits = next(e for e in client.get(f"/api/tasks/{tid}/audit").json() if e["kind"] == "agent_edits")
    assert re.fullmatch(r"[0-9a-f]{64}", edits["data"]["terraform_sha256"])


def test_raw_evidence_needs_the_evidence_scope_and_contains_the_raw_record(flow):
    client, tid, _, tmp = flow
    events = client.get(f"/api/tasks/{tid}/audit").json()
    plan_id = next(e["id"] for e in events if e["kind"] == "plan")
    no_scope = {"Authorization": "Bearer " + token(["read", "write"])}
    r = TestClient(api.app, headers={}).get(f"/api/tasks/{tid}/evidence/{plan_id}", headers=no_scope)
    assert r.status_code == 403
    raw = client.get(f"/api/tasks/{tid}/evidence/{plan_id}")
    assert raw.status_code == 200
    data = raw.json()["data"]
    assert "raw_plan" in data and "plan_stdout" in data and data["workspace"].startswith(tmp)  # raw evidence really is retained


def test_stored_task_still_has_internal_fields_for_the_gate(flow):
    """Views strip the response only; the stored record the gate verifies is untouched."""
    client, tid, _, _ = flow
    stored = api.pipeline.store.get(tid)
    assert stored["workspace"] and stored["runs"][-1]["plan_path"] and stored["runs"][-1]["plan_stdout"]
