"""A PERMITTED change really applies -- proven against a local AWS emulator (moto), never real AWS.

The emulator is an in-process HTTP server on 127.0.0.1 with dummy credentials. The baseline infrastructure is
applied to it first, then a change goes through the full pipeline (intent -> guard -> plan -> canonicalize ->
Cedar -> human resolution -> gated apply) and the emulator's own API is read back to check exactly what changed.
"""

import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

pytest.importorskip("moto")

from engine import gate  # noqa: E402
from engine.pipeline import Pipeline, ROOT  # noqa: E402
from tools.emulator import Emulator  # noqa: E402


def terraform(args, cwd, env):
    r = subprocess.run(["terraform", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=300)
    assert r.returncode == 0, (args, (r.stdout + r.stderr)[-1500:])


@pytest.fixture
def emu(tmp_path, monkeypatch):
    with Emulator() as e:
        for k, v in e.env().items():
            monkeypatch.setenv(k, v)
        env = {**os.environ, "TF_PLUGIN_CACHE_DIR": str(ROOT / ".provider-cache")}
        base = tmp_path / "baseline-infra"
        base.mkdir()
        for n in ["lambda.zip", ".terraform.lock.hcl", "main.tf"]:
            shutil.copy2(ROOT / "terraform/fixtures/baseline" / n, base / n)
        terraform(["init", "-input=false", "-no-color"], base, env)
        terraform(["apply", "-auto-approve", "-input=false", "-no-color"], base, env)
        e.state_file = base / "terraform.tfstate"
        yield e


def run_pipeline(tmp_path, emu, task, variant):
    p = Pipeline(tmp_path / "data")
    t = p.create(task)
    p.confirm(t["id"])
    t = p.agent(t["id"], variant)
    shutil.copy2(emu.state_file, Path(t["workspace"]) / "terraform.tfstate")  # state that matches the emulated infrastructure
    p.plan(t["id"])
    p.canonicalize(t["id"])
    return p, p.evaluate(t["id"])


def test_permitted_memory_change_applies_and_nothing_else_changes(tmp_path, emu):
    before = emu.snapshot()
    assert before["lambda"]["MemorySize"] == 512
    p, t = run_pipeline(tmp_path, emu, "Increase dev-api Lambda memory to 1024 MB", "intended")
    assert [(v["address"], v["verdict"]) for v in t["runs"][-1]["verdicts"]] == [("aws_lambda_function.dev_api", "ALLOW")]
    t = p.apply(t["id"])
    result = t["runs"][-1]["apply_result"]
    assert result["status"] == "APPLIED" and result["emulated"] is True and result["exit_code"] == 0
    after = emu.snapshot()
    assert after["lambda"]["MemorySize"] == 1024
    for key in before:  # everything except the one permitted attribute is identical
        b, a = before[key], after[key]
        if key == "lambda":
            b, a = {**b, "MemorySize": None}, {**a, "MemorySize": None}
        assert a == b, key


@pytest.mark.parametrize("task,check", [
    ("Add tag Owner=platform to the assets bucket", lambda s: s["bucket_tags"] == {"Environment": "dev", "Owner": "platform"}),
    ("Set the Lambda timeout to 45 seconds", lambda s: s["lambda"]["Timeout"] == 45),
    ("Set environment variable LOG_LEVEL=debug on the dev-api Lambda", lambda s: s["lambda"]["Environment"]["Variables"] == {"LOG_LEVEL": "debug"}),
])
def test_new_operations_apply_in_the_emulator(tmp_path, emu, task, check):
    p, t = run_pipeline(tmp_path, emu, task, "intended")
    assert [v["verdict"] for v in t["runs"][-1]["verdicts"]] == ["ALLOW"]
    assert p.apply(t["id"])["runs"][-1]["apply_result"]["status"] == "APPLIED"
    assert check(emu.snapshot())


def test_denied_plan_never_reaches_the_emulator(tmp_path, emu):
    before = emu.snapshot()
    p, t = run_pipeline(tmp_path, emu, "Increase dev-api Lambda memory to 1024 MB", "poisoned")
    assert "DENY" in {v["verdict"] for v in t["runs"][-1]["verdicts"]}
    result = p.apply(t["id"])["runs"][-1]["apply_result"]
    assert result["status"] == "BLOCKED" and result["spawned"] is False
    assert emu.snapshot() == before  # the public-access weakening was NOT applied


def test_unresolved_review_never_reaches_the_emulator(tmp_path, emu):
    before = emu.snapshot()
    p, t = run_pipeline(tmp_path, emu, "Increase dev-api Lambda memory to 1024 MB", "review")
    result = p.apply(t["id"])["runs"][-1]["apply_result"]
    assert result["status"] == "BLOCKED" and result["spawned"] is False
    assert emu.snapshot() == before


def test_apply_without_emulator_mode_stays_blocked(tmp_path, emu, monkeypatch):
    monkeypatch.delenv("PLANREVIEW_EMULATOR_ENDPOINT")
    before = emu.snapshot()
    p, t = run_pipeline(tmp_path, emu, "Increase dev-api Lambda memory to 1024 MB", "intended")
    result = p.apply(t["id"])["runs"][-1]["apply_result"]
    assert result["status"] == "BLOCKED" and "emulator" in result["reason"] and result["spawned"] is False
    assert emu.snapshot() == before


# ------------------------------------------------------------- safety rails
@pytest.mark.parametrize("endpoint", ["https://lambda.ap-south-1.amazonaws.com", "http://10.0.0.5:4566", "http://evil.example", "not a url"])
def test_non_loopback_emulator_endpoint_is_refused(monkeypatch, endpoint):
    monkeypatch.setenv("PLANREVIEW_EMULATOR_ENDPOINT", endpoint)
    assert gate.emulator_endpoint() is False


def test_child_environment_is_forced_to_the_emulator_and_dummy_credentials(monkeypatch):
    monkeypatch.setenv("AWS_PROFILE", "prod-admin")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "real-token")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIAREAL")
    env = gate.emulator_env("http://127.0.0.1:4566")
    assert env["AWS_ENDPOINT_URL"] == "http://127.0.0.1:4566"
    assert env["AWS_ACCESS_KEY_ID"] == "test" and env["AWS_SECRET_ACCESS_KEY"] == "test"
    assert "AWS_PROFILE" not in env and "AWS_SESSION_TOKEN" not in env
