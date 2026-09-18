import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
import pytest
from engine.canonicalizer import canonicalize
from engine.contract import draft, confirm
from engine.evaluator import evaluate, evaluate_all
from engine.types import Contract

ROOT = Path(__file__).resolve().parents[1]


def plan(name):
    return json.loads((ROOT / "tests/fixtures" / f"{name}.json").read_text())


def changes(name):
    return canonicalize(plan(name))


def contract(**kw):
    return Contract.model_validate(
        {**confirm(draft("Increase dev-api memory")).model_dump(), **kw}
    )


@pytest.mark.parametrize("backend", ["deterministic", "cedar"])
def test_02_uncovered_network_is_review(backend):
    sg = next(c for c in changes("review") if c.resource_type == "aws_security_group")
    assert (
        evaluate(contract(denies=("production", "public_access")), sg, backend).verdict
        == "REVIEW"
    )


@pytest.mark.parametrize("backend", ["deterministic", "cedar"])
def test_01_intended_allow(backend):
    c = next(c for c in changes("intended") if c.resource_type == "aws_lambda_function")
    assert c.action == "update"
    assert evaluate(contract(), c, backend).verdict == "ALLOW"
    assert any(
        d.attribute == "memory_size" and d.before == 512 and d.after == 1024
        for d in c.changes
    )


@pytest.mark.parametrize("backend", ["deterministic", "cedar"])
def test_03_production_deny(backend):
    assert evaluate(contract(), changes("production")[0], backend).verdict == "DENY"


@pytest.mark.parametrize("backend", ["deterministic", "cedar"])
def test_04_public_deny(backend):
    c = next(
        c
        for c in changes("poisoned")
        if c.resource_type == "aws_s3_bucket_public_access_block"
    )
    assert evaluate(contract(), c, backend).verdict == "DENY"


@pytest.mark.parametrize("backend", ["deterministic", "cedar"])
def test_05_unknown_review(backend):
    c = next(c for c in changes("unknown") if c.resource_type == "terraform_data")
    assert c.unknown
    assert evaluate(contract(), c, backend).verdict == "REVIEW"


def test_06_replacement():
    assert (
        next(
            c
            for c in changes("replacement")
            if c.resource_type == "aws_lambda_function"
        ).action
        == "REPLACE"
    )


def test_07_expired():
    with pytest.raises(ValueError, match="expired"):
        evaluate_all(
            contract(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1)),
            changes("intended"),
        )


def test_08_independent():
    vs = evaluate_all(
        contract(denies=("production", "public_access"), max_changed_resources=3),
        changes("poisoned"),
    )
    assert {v.address: v.verdict for v in vs} == {
        "aws_lambda_function.dev_api": "ALLOW",
        "aws_security_group.api": "REVIEW",
        "aws_s3_bucket_public_access_block.assets": "DENY",
    }
    for v in vs:
        assert v.reason and v.address and v.changes


def test_noop_and_indices():
    assert all(c.resource_type != "aws_s3_bucket" for c in changes("intended"))
    assert any(
        c.address == 'aws_lambda_function.dev_api["x"]' for c in changes("indexed")
    )


def test_malformed():
    # Deliberately broken input, not a fabricated valid Terraform plan fixture.
    assert canonicalize({"broken": True})[0].unknown
    assert evaluate(contract(), canonicalize({"broken": True})[0]).verdict == "REVIEW"


def test_network_explicit_deny():
    c = next(c for c in changes("review") if c.resource_type == "aws_security_group")
    v = evaluate(contract(), c)
    assert v.verdict == "DENY" and v.determining_policies


def test_immutable():
    c = contract()
    with pytest.raises(Exception):
        c.task = "tampered"
    with pytest.raises(Exception):
        c.allowed_resource_addresses += ("evil",)


def test_count_limit():
    vs = evaluate_all(contract(), changes("review"))
    assert not any(v.verdict == "ALLOW" for v in vs)


def test_sensitive_diff():
    from engine.canonicalizer import diff

    d = diff(
        {"password": "secret"},
        {"password": "new"},
        {},
        {"password": True},
        {"password": True},
    )
    assert "secret" not in str(d) and "new" not in str(d)
    d = diff({"password": "secret"}, {}, True, {"password": True}, {})
    assert "secret" not in str(d)
