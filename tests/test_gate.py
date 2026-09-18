import json, subprocess
from unittest.mock import patch
from engine.gate import apply_saved, digest
from tests.test_engine import contract, changes, ROOT
from engine.evaluator import evaluate_all


def tf(args, path):
    p = subprocess.run(
        ["terraform", *args], cwd=path, capture_output=True, text=True, timeout=60
    )
    assert p.returncode == 0, p.stdout + p.stderr
    return p.stdout


def test_deny_preserves_real_aws_state():
    path = ROOT / "terraform/fixtures/poisoned"
    before = tf(["show", "-json", "terraform.tfstate"], path)
    run = {
        "verdicts": [
            v.model_dump() for v in evaluate_all(contract(), changes("poisoned"))
        ]
    }
    with patch("engine.gate.subprocess.run") as spawn:
        result = apply_saved(contract(), run, {})
        spawn.assert_not_called()
    after = tf(["show", "-json", "terraform.tfstate"], path)
    assert result["status"] == "BLOCKED" and before == after
    evidence = ROOT / "docs/evidence"
    evidence.mkdir(parents=True, exist_ok=True)
    (evidence / "blocked-state.json").write_text(
        json.dumps(
            {
                "result": result,
                "state_before": json.loads(before),
                "state_after": json.loads(after),
                "equal": before == after,
            },
            indent=2,
        )
    )


def test_real_local_apply(tmp_path):
    (tmp_path / "main.tf").write_text(
        'resource "terraform_data" "proof" { input = "gate-verified" }'
    )
    tf(["init", "-input=false", "-no-color"], tmp_path)
    tf(["plan", "-out=plan.tfplan", "-input=false", "-no-color"], tmp_path)
    run = {
        "plan_path": str(tmp_path / "plan.tfplan"),
        "plan_hash": digest(tmp_path / "plan.tfplan"),
        "workspace": str(tmp_path),
        "verdicts": [{"address": "terraform_data.proof", "verdict": "REVIEW"}],
        "canonical": [{"resource_type": "terraform_data"}],
    }
    blocked = apply_saved(contract(), run, {})
    assert not blocked["spawned"]
    result = apply_saved(contract(), run, {"terraform_data.proof": "approve"})
    assert result["status"] == "APPLIED", result
    state = json.loads(tf(["show", "-json", "terraform.tfstate"], tmp_path))
    assert (
        state["values"]["root_module"]["resources"][0]["values"]["input"]
        == "gate-verified"
    )
    (ROOT / "docs/evidence/local-apply.json").write_text(
        json.dumps({"result": result, "state": state}, indent=2)
    )


def test_hash_tampering(tmp_path):
    p = tmp_path / "plan"
    p.write_text("changed")
    result = apply_saved(
        contract(), {"plan_path": str(p), "plan_hash": "wrong", "verdicts": []}, {}
    )
    assert not result["spawned"] and "hash" in result["reason"]
