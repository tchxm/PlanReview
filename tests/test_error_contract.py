"""Contract tests: every endpoint and every error family returns a stable envelope
{"detail": {"error", "message", "details", "request_id"}} with the right HTTP status."""

import logging
import subprocess

import pytest
from fastapi.testclient import TestClient

from engine import api
from engine.pipeline import Pipeline
from engine.sanitize import scrub


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "pipeline", Pipeline(tmp_path))
    return TestClient(api.app, raise_server_exceptions=False)


def err(r):
    d = r.json()["detail"]
    assert set(d) == {"error", "message", "details", "request_id"}, d
    assert d["request_id"] and r.headers["x-request-id"] == d["request_id"]
    return d


def new_task(client, text="Increase memory for dev-api Lambda"):
    r = client.post("/api/tasks", json={"task": text})
    assert r.status_code == 200, r.text
    return r.json()


def confirmed(client):
    t = new_task(client)
    assert client.post(f"/api/tasks/{t['id']}/confirm", json=t["contract"]).status_code == 200
    return t


# ---- 404: missing task on every {id} endpoint -------------------------------
MISSING = [
    ("GET", "/api/tasks/{id}"), ("GET", "/api/tasks/{id}/intent"), ("GET", "/api/tasks/{id}/audit"),
    ("GET", "/api/tasks/{id}/evidence/1"), ("POST", "/api/tasks/{id}/confirm"), ("POST", "/api/tasks/{id}/agent"),
    ("POST", "/api/tasks/{id}/plan"), ("POST", "/api/tasks/{id}/canonicalize"), ("POST", "/api/tasks/{id}/evaluate"),
    ("POST", "/api/tasks/{id}/resolve"), ("POST", "/api/tasks/{id}/apply"),
]


@pytest.mark.parametrize("method,path", MISSING)
def test_missing_task_is_404_everywhere(client, method, path):
    r = client.request(method, path.format(id="does-not-exist"), json={} if method == "POST" else None)
    assert r.status_code == 404, (path, r.text)
    assert err(r)["error"] == "TASK_NOT_FOUND"


def test_missing_evidence_record_is_404(client):
    t = new_task(client)
    r = client.get(f"/api/tasks/{t['id']}/evidence/99999")
    assert r.status_code == 404 and err(r)["error"] == "EVIDENCE_NOT_FOUND"


# ---- 422: invalid request or contract ---------------------------------------
def test_invalid_request_bodies_are_422(client):
    for body in ({"task": ""}, {"task": "x" * 4001}, {}, {"task": 5}):
        r = client.post("/api/tasks", json=body)
        assert r.status_code == 422 and err(r)["error"] == "INVALID_REQUEST", body
        assert err(r)["details"]["errors"]
    r = client.post("/api/tasks", json={"task": "Increase dev-api Lambda memory", "mode": "nonsense"})
    assert r.status_code == 422 and err(r)["error"] == "UNKNOWN_MODE"


def test_invalid_contract_data_is_422_and_does_not_echo_input(client):
    t = new_task(client)
    c = dict(t["contract"], denies=["<script>SECRET-CANARY</script>"])
    r = client.post(f"/api/tasks/{t['id']}/confirm", json=c)
    assert r.status_code == 422 and err(r)["error"] == "INVALID_CONTRACT"
    assert "SECRET-CANARY" not in r.text


def test_contract_id_change_is_422(client):
    t = new_task(client)
    r = client.post(f"/api/tasks/{t['id']}/confirm", json=dict(t["contract"], contract_id="another"))
    assert r.status_code == 422 and err(r)["error"] == "CONTRACT_ID_MISMATCH"


def test_bad_types_on_typed_routes_are_422(client):
    assert client.get("/api/tasks/x/evidence/not-a-number").status_code == 422
    assert client.post("/api/tasks/x/resolve", json=["not", "a", "dict"]).status_code == 422


def test_unknown_fixture_is_422(client):
    t = confirmed(client)
    r = client.post(f"/api/tasks/{t['id']}/agent?variant=../../etc/passwd")
    assert r.status_code == 422 and err(r)["error"] == "UNKNOWN_FIXTURE"


# ---- 400: unsupported (Phase 1 behaviour preserved) -------------------------
def test_unsupported_operation_keeps_its_code(client):
    r = client.post("/api/tasks", json={"task": "Delete the production RDS database"})
    assert r.status_code == 400 and err(r)["error"] == "UNSUPPORTED_OPERATION"


# ---- 409: genuine state conflicts -------------------------------------------
def test_state_conflicts_are_409_with_codes(client):
    t = new_task(client)
    tid = t["id"]
    r = client.post(f"/api/tasks/{tid}/agent")
    assert r.status_code == 409 and err(r)["error"] == "CONTRACT_NOT_ACTIVE"
    assert client.post(f"/api/tasks/{tid}/confirm", json=t["contract"]).status_code == 200
    r = client.post(f"/api/tasks/{tid}/confirm", json=t["contract"])
    assert r.status_code == 409 and err(r)["error"] == "CONTRACT_IMMUTABLE"
    for stage in ("plan", "canonicalize", "evaluate", "apply"):
        r = client.post(f"/api/tasks/{tid}/{stage}")
        assert r.status_code == 409, (stage, r.text)
        assert err(r)["error"] in {"STAGE_OUT_OF_ORDER", "NO_SAVED_PLAN"}, (stage, r.text)
    r = client.post(f"/api/tasks/{tid}/resolve", json={"aws_lambda_function.dev_api": "approve"})
    assert r.status_code == 409


def test_editing_twice_before_planning_conflicts(client):
    t = confirmed(client)
    assert client.post(f"/api/tasks/{t['id']}/agent?variant=intended").status_code == 200
    r = client.post(f"/api/tasks/{t['id']}/agent?variant=intended")
    assert r.status_code == 409 and err(r)["error"] == "EDIT_ALREADY_PREPARED"


# ---- 502/503/504: dependencies ----------------------------------------------
def test_model_unavailable_is_503_and_not_replay(client, monkeypatch):
    monkeypatch.setattr("engine.agent.ollama_configuration", lambda: {"enabled": True, "server_reachable": False, "model_installed": False, "error": "refused"})
    r = client.post("/api/tasks", json={"task": "Update dev-api memory to 1024", "mode": "ollama"})
    assert r.status_code == 503 and err(r)["error"] == "MODEL_UNAVAILABLE"
    assert client.get("/api/tasks").json() == []  # nothing was created, no silent replay


def _prepared(client):
    t = confirmed(client)
    assert client.post(f"/api/tasks/{t['id']}/agent?variant=intended").status_code == 200
    return t["id"]


def test_terraform_missing_is_503(client, monkeypatch):
    tid = _prepared(client)
    monkeypatch.setattr("engine.pipeline.subprocess.run", lambda *a, **k: (_ for _ in ()).throw(FileNotFoundError("terraform")))
    r = client.post(f"/api/tasks/{tid}/plan")
    assert r.status_code == 503 and err(r)["error"] == "TERRAFORM_UNAVAILABLE"


def test_terraform_timeout_is_504(client, monkeypatch):
    tid = _prepared(client)

    def boom(*a, **k):
        raise subprocess.TimeoutExpired("terraform", 180)

    monkeypatch.setattr("engine.pipeline.subprocess.run", boom)
    r = client.post(f"/api/tasks/{tid}/plan")
    assert r.status_code == 504 and err(r)["error"] == "TERRAFORM_TIMEOUT"


def test_terraform_failure_is_502_and_raw_output_stays_in_the_server_log(client, monkeypatch, caplog):
    tid = _prepared(client)
    leak = "Error: cannot read C:\\Users\\victim\\secrets\\terraform.tfvars value=SUPER-SECRET-VALUE"
    monkeypatch.setattr("engine.pipeline.subprocess.run", lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr=leak))
    with caplog.at_level(logging.ERROR, logger="planreview"):
        r = client.post(f"/api/tasks/{tid}/plan")
    assert r.status_code == 502 and err(r)["error"] == "TERRAFORM_FAILED"
    assert "SUPER-SECRET-VALUE" not in r.text and "victim" not in r.text and "tfvars" not in r.text
    assert "SUPER-SECRET-VALUE" in caplog.text  # diagnostics preserved server side


# ---- 500 and route errors ---------------------------------------------------
def test_unexpected_failure_is_500_without_leaking(client, monkeypatch, caplog):
    def boom():
        raise RuntimeError("db exploded at C:\\secret\\place with token=ABC123")

    monkeypatch.setattr(api.pipeline.store, "list", boom)
    with caplog.at_level(logging.ERROR, logger="planreview"):
        r = client.get("/api/tasks")
    assert r.status_code == 500 and err(r)["error"] == "INTERNAL_ERROR"
    assert "ABC123" not in r.text and "secret" not in r.text.lower()
    assert "ABC123" in caplog.text


def test_untyped_value_error_is_not_reported_as_a_client_error(client, monkeypatch):
    monkeypatch.setattr(api.pipeline.store, "get", lambda id: (_ for _ in ()).throw(ValueError("internal detail")))
    r = client.get("/api/tasks/x")
    assert r.status_code == 500 and "internal detail" not in r.text


def test_unknown_route_and_method_are_structured(client):
    r = client.get("/api/nope")
    assert r.status_code == 404 and err(r)["error"] == "ROUTE_NOT_FOUND"
    r = client.delete("/api/tasks")
    assert r.status_code == 405 and err(r)["error"] == "METHOD_NOT_ALLOWED"


# ---- scrub unit tests -------------------------------------------------------
@pytest.mark.parametrize(
    "text,forbidden",
    [
        ("open C:\\Users\\kario\\data\\x.tf failed", "kario"),
        ("open /home/kario/data/x.tf failed", "kario"),
        ("token v1.read+write.9999999999.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA", "AAAAAAAAAAAA"),
        ("Authorization: Bearer abc.def.ghi", "abc.def.ghi"),
    ],
)
def test_scrub_removes_paths_and_credentials(text, forbidden):
    assert forbidden not in scrub(text)


def test_scrub_truncates_and_strips_control_characters():
    s = scrub("a\x00b" + "z" * 2000)
    assert len(s) <= 501 and "\x00" not in s
