"""Adversarial and chaos tests for PlanReview.
Validates the gate, evaluator, storage, API, and agent error boundaries.
Every blocked apply scenario verifies that the Terraform apply subprocess is not spawned.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from engine import api
from engine.evaluator import evaluate
from engine.gate import apply_saved, digest, gate_reason
from engine.pipeline import Pipeline, ROOT
from engine.types import Contract, CanonicalChange, Change


def create_confirmed_pipeline_task(tmp_path, task_desc="Demo task", denies=("production", "public_access"), max_changed=3):
    p = Pipeline(tmp_path)
    t = p.create(task_desc)
    c = t["contract"]
    c["denies"] = list(denies)
    c["max_changed_resources"] = max_changed
    p.confirm(t["id"], c)
    return p, t["id"]


def test_chaos_01_direct_api_apply_with_deny_blocks_and_never_spawns(tmp_path, monkeypatch):
    """Scenario 1: Direct API apply request when plan has a DENY must return BLOCKED and never spawn subprocess."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    monkeypatch.setattr(api, "pipeline", p)
    client = TestClient(api.app)

    # Run pipeline with poisoned fixture (has S3 public-access weakening -> DENY)
    p.agent(task_id, "poisoned")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    task_data = p.store.get(task_id)
    verdicts = task_data["runs"][-1]["verdicts"]
    assert any(v["verdict"] == "DENY" for v in verdicts)

    with patch("engine.gate.subprocess.run") as mock_spawn:
        resp = client.post(f"/api/tasks/{task_id}/apply")
        mock_spawn.assert_not_called()

    assert resp.status_code == 200
    apply_result = resp.json()["runs"][-1]["apply_result"]
    assert apply_result["status"] == "BLOCKED"
    assert apply_result["spawned"] is False
    assert "DENY" in apply_result["reason"]


def test_chaos_02_missing_or_corrupted_canonical_plan_blocks(tmp_path):
    """Scenario 2: Apply request with missing canonical plan data blocks with spawned=False."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    p.agent(task_id, "intended")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    task_data = p.store.get(task_id)
    run = task_data["runs"][-1]

    # Corrupt canonical to None
    run_no_canonical = dict(run)
    run_no_canonical["canonical"] = None

    c = Contract.model_validate(task_data["contract"])
    with patch("engine.gate.subprocess.run") as mock_spawn:
        res = apply_saved(c, run_no_canonical, {})
        mock_spawn.assert_not_called()

    assert res["status"] == "BLOCKED"
    assert res["spawned"] is False
    assert "canonical" in res["reason"].lower()


def test_chaos_03_unresolved_and_rejected_review_blocks_apply(tmp_path):
    """Scenario 3: Unresolved or rejected REVIEW must block apply before subprocess start."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    p.agent(task_id, "review")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    # 1. Apply without any resolution
    with patch("engine.gate.subprocess.run") as mock_spawn:
        t = p.apply(task_id)
        mock_spawn.assert_not_called()

    assert t["runs"][-1]["apply_result"]["status"] == "BLOCKED"
    assert t["runs"][-1]["apply_result"]["spawned"] is False
    assert "unresolved or rejected REVIEW" in t["runs"][-1]["apply_result"]["reason"]

    # 2. Resolve to 'reject'
    p.resolve(task_id, {"aws_security_group.api": "reject"})
    with patch("engine.gate.subprocess.run") as mock_spawn:
        t2 = p.apply(task_id)
        mock_spawn.assert_not_called()

    assert t2["runs"][-1]["apply_result"]["status"] == "BLOCKED"
    assert t2["runs"][-1]["apply_result"]["spawned"] is False
    assert "unresolved or rejected REVIEW" in t2["runs"][-1]["apply_result"]["reason"]


def test_chaos_04_expired_contract_blocks_apply(tmp_path):
    """Scenario 4: Expired contract must block apply even if verdicts were otherwise clean."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    p.agent(task_id, "intended")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    # Fast-forward contract expiry into the past
    task_data = p.store.get(task_id)
    task_data["contract"]["expires_at"] = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    
    # Re-calculate hash for integrity check to pass, but active() check will fail
    encoded = json.dumps(task_data["contract"], sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    task_data["confirmed_contract_hash"] = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    
    with sqlite3.connect(p.store.path) as db:
        db.execute("UPDATE tasks SET body=? WHERE id=?", (json.dumps(task_data), task_id))

    with patch("engine.gate.subprocess.run") as mock_spawn:
        t = p.apply(task_id)
        mock_spawn.assert_not_called()

    assert t["runs"][-1]["apply_result"]["status"] == "BLOCKED"
    assert t["runs"][-1]["apply_result"]["spawned"] is False
    assert "expired" in t["runs"][-1]["apply_result"]["reason"].lower()


def test_chaos_05_modified_saved_plan_blocks_apply(tmp_path):
    """Scenario 5: If the binary plan file is tampered with on disk, apply must block."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    p.agent(task_id, "intended")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    task_data = p.store.get(task_id)
    plan_file = Path(task_data["runs"][-1]["plan_path"])
    assert plan_file.exists()

    # Tamper with saved binary plan
    plan_file.write_bytes(b"tampered binary plan contents")

    with patch("engine.gate.subprocess.run") as mock_spawn:
        t = p.apply(task_id)
        mock_spawn.assert_not_called()

    assert t["runs"][-1]["apply_result"]["status"] == "BLOCKED"
    assert t["runs"][-1]["apply_result"]["spawned"] is False
    assert "hash mismatch" in t["runs"][-1]["apply_result"]["reason"].lower()


def test_chaos_06_modified_confirmed_contract_raises_integrity_error(tmp_path):
    """Scenario 6: Modifying confirmed contract directly in storage triggers integrity mismatch before apply."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    p.agent(task_id, "intended")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    # Tamper with contract in SQLite without updating hash
    with sqlite3.connect(p.store.path) as db:
        row = db.execute("SELECT body FROM tasks WHERE id=?", (task_id,)).fetchone()[0]
        data = json.loads(row)
        data["contract"]["allowed_resource_addresses"] = ["aws_lambda_function.evil"]
        db.execute("UPDATE tasks SET body=? WHERE id=?", (json.dumps(data), task_id))

    with patch("engine.gate.subprocess.run") as mock_spawn:
        with pytest.raises(ValueError, match="Confirmed contract integrity hash mismatch"):
            p.apply(task_id)
        mock_spawn.assert_not_called()


def test_chaos_07_reused_review_approval_cleared_on_new_plan(tmp_path):
    """Scenario 7: Approving a REVIEW on plan 1 must never carry over to plan 2."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    p.agent(task_id, "review")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    # Approve SG on run 1
    p.resolve(task_id, {"aws_security_group.api": "approve"})

    # Run a second agent edit and plan
    p.agent(task_id, "review")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    task_data = p.store.get(task_id)
    assert task_data["runs"][-1]["resolutions"] == {}

    with patch("engine.gate.subprocess.run") as mock_spawn:
        t = p.apply(task_id)
        mock_spawn.assert_not_called()

    assert t["runs"][-1]["apply_result"]["status"] == "BLOCKED"
    assert t["runs"][-1]["apply_result"]["spawned"] is False


def test_chaos_08_cedar_failure_fails_closed_to_review():
    """Scenario 8: If Cedar evaluation fails with an exception, verdict must fail closed to REVIEW, never ALLOW."""
    c = Contract.model_validate({
        "contract_id": "test",
        "task": "test",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "status": "confirmed",
    })
    ch = CanonicalChange(
        address="aws_lambda_function.dev_api",
        resource_type="aws_lambda_function",
        action="update",
        environment="dev",
        region="ap-south-1",
        changes=[Change(attribute="memory_size", before=512, after=1024)],
        unknown=False,
    )

    with patch("cedarpy.is_authorized", side_effect=RuntimeError("Simulated Cedar engine panic")):
        v = evaluate(c, ch, backend="cedar")

    assert v.verdict == "REVIEW"
    assert "Cedar evaluation unavailable" in v.reason
    assert v.verdict != "ALLOW"


def test_chaos_09_repeated_apply_rejected(tmp_path):
    """Scenario 9: Applying an already applied run must be rejected."""
    p, task_id = create_confirmed_pipeline_task(tmp_path)
    p.agent(task_id, "intended")
    p.plan(task_id)
    p.canonicalize(task_id)
    p.evaluate(task_id)

    task_data = p.store.get(task_id)
    task_data["runs"][-1]["apply_result"] = {"status": "APPLIED", "spawned": True}
    p.store.save(task_data, "apply_result", task_data["runs"][-1]["apply_result"])

    with pytest.raises(ValueError, match="Run already applied"):
        p.apply(task_id)


def test_chaos_10_ollama_failure_preserves_safe_workspace(tmp_path, monkeypatch):
    """Scenario 10: Ollama failure during edit raises an error without corrupting workspace."""
    p = Pipeline(tmp_path)
    t = p.create("Task for ollama test", mode="ollama")
    p.confirm(t["id"], t["contract"])

    def mock_failing_live_edit(task, workspace):
        raise ConnectionError("Ollama daemon disconnected")

    monkeypatch.setattr("engine.agent.live_edit", mock_failing_live_edit)

    with pytest.raises(ConnectionError, match="Ollama daemon disconnected"):
        p.agent(t["id"])

    # Task stage should not be marked as edited
    task_state = p.store.get(t["id"])
    assert task_state.get("stage") != "edited"
    assert not task_state.get("prepared", False)

