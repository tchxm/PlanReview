"""Widened scope: registry operations run the FULL pipeline against real Terraform and stay attribute-locked."""

import pytest

from engine import capabilities
from engine.exceptions import GuardRejectedError, UnsupportedOperationError
from engine.intent import CAPABILITY_REGISTRY, interpret
from engine.pipeline import Pipeline, ROOT

CASES = [
    ("Set the Lambda timeout to 45 seconds", "update_timeout", "timeout", 45, "aws_lambda_function.dev_api"),
    ("Set environment variable LOG_LEVEL=debug on the dev-api Lambda", "set_lambda_env", "environment.variables.LOG_LEVEL", "debug", "aws_lambda_function.dev_api"),
    ("Add tag Owner=platform to the assets bucket", "set_s3_tag", "tags.Owner", "platform", "aws_s3_bucket.assets"),
    ("Enable versioning on the assets bucket", "enable_s3_versioning", "versioning.enabled", True, "aws_s3_bucket.assets"),
]


@pytest.mark.parametrize("task,op,attr,val,address", CASES)
def test_new_operations_extract_and_validate(task, op, attr, val, address):
    p = interpret(task)
    assert (p.operation, p.attribute, p.requested_value, p.resource_address) == (op, attr, val, address)
    assert op in CAPABILITY_REGISTRY


@pytest.mark.parametrize("task,op,attr,val,address", CASES)
def test_new_operations_full_pipeline_allows_exactly_one_resource(tmp_path, task, op, attr, val, address):
    p = Pipeline(tmp_path)
    t = p.create(task)
    p.confirm(t["id"])
    p.agent(t["id"], "intended")
    p.plan(t["id"])
    p.canonicalize(t["id"])
    t = p.evaluate(t["id"])
    run = t["runs"][-1]
    assert [c["address"] for c in run["canonical"]] == [address]
    assert [(v["address"], v["verdict"]) for v in run["verdicts"]] == [(address, "ALLOW")]


@pytest.mark.parametrize("task,op,attr,val,address", CASES)
def test_guard_rejects_any_extra_change_on_top_of_the_confirmed_edit(tmp_path, task, op, attr, val, address):
    p = Pipeline(tmp_path)
    t = p.create(task)
    p.confirm(t["id"])
    t = p.agent(t["id"], "intended")
    main = tmp_path / "workspaces" / t["id"] / "main.tf"
    main.write_text(main.read_text().replace('Environment = "dev" }', 'Environment = "dev", Sneaky = "1" }', 1) if "tags" in attr and op != "set_s3_tag"
                    else main.read_text().replace("runtime = ", "reserved_concurrent_executions = 5\n  runtime = ", 1))
    with pytest.raises(GuardRejectedError):
        p.plan(t["id"])


@pytest.mark.parametrize("task", [
    "Set environment variable DB_PASSWORD=hunter2 on the dev-api Lambda",
    "Set environment variable AWS_REGION=us-east-1 on the dev-api Lambda",
    "Set the Environment tag to prod on the assets bucket",
    "Add tag aws:cost=1 to the assets bucket",
    "Set the Lambda timeout to 5000 seconds",
    "Set the Lambda timeout to 0 seconds",
])
def test_unsafe_values_are_rejected(task):
    with pytest.raises(UnsupportedOperationError):
        interpret(task)


def test_original_operations_are_unchanged():
    assert interpret("increase dev-api lambda memory to 2048").operation == "update_memory"
    assert interpret("set team tag to core on the assets bucket").attribute == "tags.Team"


def test_registry_entries_are_self_consistent():
    baseline = (ROOT / "terraform/fixtures/baseline/main.tf").read_text()
    for task, op, attr, val, address in CASES:
        out = capabilities.expected_config(baseline, op, attr, val)
        assert out != baseline and out.count("resource ") == baseline.count("resource ")
        assert capabilities.check_value(op, attr, val) is None


def test_capabilities_endpoint_lists_every_operation():
    from fastapi.testclient import TestClient

    from engine import api

    r = TestClient(api.app).get("/api/capabilities")
    assert r.status_code == 200
    assert set(r.json()) == {"update_memory", "update_tags", "update_timeout", "set_lambda_env", "set_s3_tag", "enable_s3_versioning"}
    assert TestClient(api.app, headers={}).get("/api/capabilities").status_code == 401


# ----------------------------------------------------- parsed-HCL structure guard
BASE = (ROOT / "terraform/fixtures/baseline/main.tf").read_text()


@pytest.mark.parametrize("extra,why", [
    ('\ndata "aws_caller_identity" "me" {}\n', "data source"),
    ('\nmodule "m" { source = "./x" }\n', "module"),
    ('\nvariable "v" {}\n', "variable"),
    ('\noutput "o" { value = 1 }\n', "output"),
    ('\nlocals { a = 1 }\n', "locals"),
])
def test_guard_rejects_unsupported_top_level_blocks(extra, why):
    from engine.guard import parse_config

    with pytest.raises(GuardRejectedError):
        parse_config(BASE + extra)


def test_guard_rejects_backend_and_provisioners_and_bad_hcl():
    from engine.guard import parse_config

    with pytest.raises(GuardRejectedError):
        parse_config(BASE.replace("terraform {", 'terraform {\n  backend "s3" {}\n', 1))
    with pytest.raises(GuardRejectedError):
        parse_config(BASE.replace('memory_size = 512', 'memory_size = 512\n  provisioner "local-exec" { command = "x" }', 1))
    with pytest.raises(GuardRejectedError):
        parse_config(BASE + "\nresource \"aws_s3_bucket\" \"x\" {")


def test_guard_accepts_the_baseline_and_lists_its_resources():
    from engine.guard import parse_config

    assert set(parse_config(BASE)) == {
        ("aws_lambda_function", "dev_api"), ("aws_security_group", "api"), ("aws_s3_bucket", "assets"), ("aws_s3_bucket_public_access_block", "assets"),
    }


def test_word_data_inside_a_string_is_no_longer_a_structural_problem():
    from engine.guard import parse_config

    parse_config(BASE.replace('function_name = "dev-api"', 'function_name = "dev-api"\n  description = "module data provisioner text"', 1))
