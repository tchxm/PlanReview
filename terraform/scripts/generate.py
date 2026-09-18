"""Generate fixtures from real Terraform. Only seed STATE is constructed by hand."""

import json, os, subprocess, uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = """terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
      version = "5.99.0"
    }
  }
}
provider "aws" {
  region = "ap-south-1"
  access_key = "test"
  secret_key = "test"
  skip_credentials_validation = true
  skip_requesting_account_id = true
  skip_metadata_api_check = true
}
resource "aws_lambda_function" "dev_api" {
  function_name = "dev-api"
  role = "arn:aws:iam::123456789012:role/demo"
  filename = "lambda.zip"
  handler = "index.handler"
  runtime = "python3.12"
  memory_size = MEMORY
  tags = { Environment = "ENVIRONMENT" }
}
resource "aws_security_group" "api" {
  name = "dev-api"
  description = "Demo security group"
  vpc_id = "vpc-12345678"
  ingress = INGRESS
  egress = []
  tags = { Environment = "dev" }
}
resource "aws_s3_bucket" "assets" {
  bucket = "planreview-demo-assets"
  tags = { Environment = "dev" }
}
resource "aws_s3_bucket_public_access_block" "assets" {
  bucket = aws_s3_bucket.assets.id
  block_public_acls = PUBLIC
  block_public_policy = PUBLIC
  ignore_public_acls = PUBLIC
  restrict_public_buckets = PUBLIC
}
"""
INGRESS = '[{from_port=443,to_port=443,protocol="tcp",cidr_blocks=["10.0.0.0/8"],ipv6_cidr_blocks=[],prefix_list_ids=[],security_groups=[],self=false,description="Internal HTTPS"}]'


def run(args, cwd):
    p = subprocess.run(
        ["terraform", *args], cwd=cwd, capture_output=True, text=True, timeout=300
    )
    print(f"terraform {' '.join(args)} -> {p.returncode}")
    if p.returncode:
        raise RuntimeError(p.stdout + p.stderr)
    return p.stdout


def seed():
    common = {"tags": {"Environment": "dev"}, "tags_all": {"Environment": "dev"}}
    attrs = {
        ("aws_lambda_function", "dev_api"): dict(
            common,
            id="dev-api",
            function_name="dev-api",
            role="arn:aws:iam::123456789012:role/demo",
            filename="lambda.zip",
            handler="index.handler",
            runtime="python3.12",
            memory_size=512,
            timeout=3,
            architectures=["x86_64"],
            package_type="Zip",
            publish=False,
            reserved_concurrent_executions=-1,
            skip_destroy=False,
            source_code_size=100,
            last_modified="2026-09-17T00:00:00.000+0000",
            version="$LATEST",
            arn="arn:aws:lambda:ap-south-1:123456789012:function:dev-api",
            logging_config=[
                {
                    "log_format": "Text",
                    "log_group": "/aws/lambda/dev-api",
                    "application_log_level": "",
                    "system_log_level": "",
                }
            ],
            ephemeral_storage=[{"size": 512}],
            tracing_config=[{"mode": "PassThrough"}],
        ),
        ("aws_security_group", "api"): dict(
            common,
            id="sg-12345678",
            name="dev-api",
            description="Demo security group",
            vpc_id="vpc-12345678",
            ingress=[],
            egress=[],
            revoke_rules_on_delete=False,
        ),
        ("aws_s3_bucket", "assets"): dict(
            common,
            id="planreview-demo-assets",
            bucket="planreview-demo-assets",
            force_destroy=False,
        ),
        ("aws_s3_bucket_public_access_block", "assets"): dict(
            id="planreview-demo-assets",
            bucket="planreview-demo-assets",
            block_public_acls=True,
            block_public_policy=True,
            ignore_public_acls=True,
            restrict_public_buckets=True,
        ),
    }
    return {
        "version": 4,
        "terraform_version": "1.13.0",
        "serial": 1,
        "lineage": str(uuid.uuid4()),
        "outputs": {},
        "resources": [
            {
                "mode": "managed",
                "type": t,
                "name": n,
                "provider": 'provider["registry.terraform.io/hashicorp/aws"]',
                "instances": [
                    {
                        "schema_version": 1 if t == "aws_security_group" else 0,
                        "attributes": a,
                        "sensitive_attributes": [],
                    }
                ],
            }
            for (t, n), a in attrs.items()
        ],
    }


def main():
    import zipfile

    out = ROOT / "tests/fixtures"
    out.mkdir(parents=True, exist_ok=True)
    cache = ROOT / ".provider-cache"
    cache.mkdir(exist_ok=True)
    os.environ.setdefault("TF_PLUGIN_CACHE_DIR", str(cache))
    state = seed()
    for variant in [
        "baseline",
        "intended",
        "review",
        "poisoned",
        "production",
        "replacement",
        "unknown",
        "indexed",
    ]:
        path = ROOT / "terraform/fixtures" / variant
        path.mkdir(parents=True, exist_ok=True)
        config = (
            BASE.replace("MEMORY", "512" if variant == "baseline" else "1024")
            .replace("ENVIRONMENT", "production" if variant == "production" else "dev")
            .replace("INGRESS", INGRESS if variant in ["review", "poisoned"] else "[]")
            .replace("PUBLIC", "false" if variant == "poisoned" else "true")
        )
        if variant == "replacement":
            config = config.replace(
                'function_name = "dev-api"', 'function_name = "dev-api-replaced"'
            )
        if variant == "unknown":
            config += '\nresource "terraform_data" "later" { input = "later" }\noutput "later" { value = terraform_data.later.output }\n'
        if variant == "indexed":
            config = config.replace(
                'resource "aws_lambda_function" "dev_api" {',
                'resource "aws_lambda_function" "dev_api" {\n  for_each = toset(["x"])',
            )
        (path / "main.tf").write_text(config)
        (path / "terraform.tfstate").write_text(json.dumps(state))
        with zipfile.ZipFile(path / "lambda.zip", "w") as z:
            z.writestr("index.py", "def handler(event, context): return {}")
        if not (path / ".terraform").exists():
            run(["init", "-input=false", "-no-color"], path)
        run(
            ["plan", "-refresh=false", "-input=false", "-no-color", "-out=plan.tfplan"],
            path,
        )
        raw = run(["show", "-json", "plan.tfplan"], path)
        (out / f"{variant}.json").write_text(raw)
        parsed = json.loads(raw)
        print(
            variant,
            [
                (r["address"], r["change"]["actions"])
                for r in parsed["resource_changes"]
            ],
        )


if __name__ == "__main__":
    main()
