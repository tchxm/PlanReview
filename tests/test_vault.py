"""Encryption at rest of plan evidence."""

from pathlib import Path

import pytest

from engine.pipeline import Pipeline
from engine.vault import Vault


@pytest.fixture
def pipe(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANREVIEW_ENCRYPT_AT_REST", "1")
    return Pipeline(tmp_path)


def planned(p):
    t = p.create("Increase dev-api Lambda memory to 1024 MB")
    p.confirm(t["id"])
    p.agent(t["id"], "intended")
    return p.plan(t["id"])


def test_plan_artifacts_are_sealed_and_the_pipeline_still_works(pipe, tmp_path):
    t = planned(pipe)
    ws = Path(t["workspace"])
    names = {f.name for f in ws.iterdir()}
    assert not any(n.endswith((".tfplan", ".json")) for n in names)
    assert sum(n.endswith(".tfplan.enc") for n in names) == 1 and sum(n.endswith(".json.enc") for n in names) == 1
    for f in ws.glob("*.enc"):
        assert b"resource_changes" not in f.read_bytes() and b"format_version" not in f.read_bytes()
    pipe.canonicalize(t["id"])
    t = pipe.evaluate(t["id"])
    assert [v["verdict"] for v in t["runs"][-1]["verdicts"]] == ["ALLOW"]


def test_raw_plan_is_not_plaintext_in_the_database_but_evidence_reads_back(pipe, tmp_path):
    t = planned(pipe)
    db = (tmp_path / "planreview.sqlite").read_bytes()
    assert b"resource_changes" not in db and b"format_version" not in db
    plan_event = [e for e in pipe.store.audit(t["id"]) if e["kind"] == "plan"][-1]
    assert "resource_changes" in plan_event["data"]["raw_plan"]  # decrypted for the evidence-scoped reader
    assert "raw_plan_enc" not in plan_event["data"]
    assert pipe.store.verify_audit()["ok"]  # the chain covers the sealed form


def test_tampered_sealed_plan_fails_closed(pipe):
    t = planned(pipe)
    raw = next(Path(t["workspace"]).glob("*.json.enc"))
    raw.write_bytes(raw.read_bytes()[:-5] + b"AAAAA")
    with pytest.raises(Exception) as e:
        pipe.canonicalize(t["id"])
    assert getattr(e.value, "code", "") == "PLAN_INTEGRITY_FAILED"


def test_wrong_secret_cannot_read_sealed_evidence(pipe, tmp_path):
    t = planned(pipe)
    raw = next(Path(t["workspace"]).glob("*.json.enc"))
    other = Vault(b"a-different-secret-" + b"y" * 32, enabled=True)
    with pytest.raises(ValueError):
        other.read_bytes(str(raw)[: -len(".enc")])


def test_unsealed_restores_plaintext_only_inside_the_block(pipe):
    t = planned(pipe)
    plan = t["runs"][-1]["plan_path"]
    assert not Path(plan).exists()
    with pipe.vault.unsealed(plan) as p:
        assert p.exists() and pipe.vault.digest(plan) == t["runs"][-1]["plan_hash"]
    assert not Path(plan).exists() and Path(plan + ".enc").exists()


def test_apply_path_unseals_verifies_then_reseals(pipe):
    t = planned(pipe)
    pipe.canonicalize(t["id"])
    pipe.evaluate(t["id"])
    t = pipe.apply(t["id"])  # AWS apply is disabled: BLOCKED, but the saved plan was restored, hash-checked and resealed
    assert t["runs"][-1]["apply_result"]["status"] == "BLOCKED"
    assert not list(Path(t["workspace"]).glob("*.tfplan"))


def test_disabled_vault_keeps_plaintext(tmp_path, monkeypatch):
    monkeypatch.setenv("PLANREVIEW_ENCRYPT_AT_REST", "0")
    t = planned(Pipeline(tmp_path))
    assert list(Path(t["workspace"]).glob("*.tfplan")) and not list(Path(t["workspace"]).glob("*.enc"))
