"""Pre-planning configuration and workspace integrity guard.

Enforces:
1. Controlled workspace directory inventory (no unexpected executable or config files).
2. Provider block integrity (no unauthorized provider additions or credential overrides).
3. Rejection of unsupported executable constructs (modules, data sources, provisioners, backend).
4. Strict resource declaration allowlist (rejects unexpected resources like aws_instance).
5. Attribute-level post-edit verification against confirmed intent.
"""

from __future__ import annotations
from pathlib import Path
import re
from typing import Any

from engine.types import Contract

ALLOWED_WORKSPACE_FILES = {
    "main.tf",
    "terraform.tfstate",
    "lambda.zip",
    ".terraform.lock.hcl",
}

ALLOWED_RESOURCE_DECLARATIONS = {
    ("aws_lambda_function", "dev_api"),
    ("aws_security_group", "api"),
    ("aws_s3_bucket", "assets"),
    ("aws_s3_bucket_public_access_block", "assets"),
}

FORBIDDEN_CONSTRUCTS = re.compile(
    r"\b(provisioner|data|module|backend|terraform_remote_state|external|local-exec|remote-exec)\b"
)


def verify_workspace_files(workspace_path: Path) -> None:
    """Verify that no unexpected files or scripts exist in the workspace."""
    for entry in workspace_path.iterdir():
        if entry.is_dir():
            if entry.name != ".terraform":
                raise ValueError(
                    f"Unexpected directory in workspace: {entry.name}. Arbitrary directory structures are rejected."
                )
            continue
        if entry.name.endswith(".tfplan") or entry.name.endswith(".json"):
            # Generated plan artifacts
            continue
        if entry.name not in ALLOWED_WORKSPACE_FILES:
            raise ValueError(
                f"Unexpected file in workspace: {entry.name}. Only controlled baseline files are allowed."
            )


def extract_resource_declarations(config: str) -> list[tuple[str, str]]:
    """Extract all resource "type" "name" pairs from HCL with flexible whitespace."""
    pattern = re.compile(r'\bresource\s+["\']?([^"\'\s{]+)["\']?\s+["\']?([^"\'\s{]+)["\']?')
    return pattern.findall(config)


def verify_workspace_configuration(
    workspace_path: Path,
    contract: Contract,
    intent: dict[str, Any] | None = None,
    mode: str = "replay",
    variant: str = "intended",
    root_path: Path | None = None,
) -> None:
    """Run comprehensive pre-planning security and attribute checks."""
    if not workspace_path.exists():
        raise ValueError("Workspace does not exist")

    # 1. File inventory
    verify_workspace_files(workspace_path)

    # 2. Provider header verification
    config_path = workspace_path / "main.tf"
    if not config_path.exists():
        raise ValueError("Workspace main.tf is missing")

    config = config_path.read_text(encoding="utf-8")
    root = root_path or Path(__file__).resolve().parents[1]
    baseline_path = root / "terraform/fixtures/baseline/main.tf"
    baseline = baseline_path.read_text(encoding="utf-8")

    config_header = re.split(r'\bresource\s+["\']?', config, maxsplit=1)[0]
    baseline_header = re.split(r'\bresource\s+["\']?', baseline, maxsplit=1)[0]
    if config_header.strip() != baseline_header.strip():
        raise ValueError(
            "Provider header modified or unsupported provider declarations present; planning blocked"
        )

    # 3. Forbidden executable constructs
    if FORBIDDEN_CONSTRUCTS.search(config):
        raise ValueError(
            "Unsupported executable Terraform configuration (provisioners, modules, data sources, or backend); planning blocked"
        )

    # 4. Resource block allowlist
    declared_resources = extract_resource_declarations(config)
    for r_type, r_name in declared_resources:
        if (r_type, r_name) not in ALLOWED_RESOURCE_DECLARATIONS:
            raise ValueError(
                f"Unauthorized resource declaration '{r_type}.{r_name}' detected. "
                f"Genuine Phase 1 baseline only permits dev_api Lambda, api SG, and assets S3 bucket."
            )

    # 5. Attribute-level change verification
    is_adversarial = mode == "adversarial" or variant in ["poisoned", "adversarial"]
    if not is_adversarial and variant != "review":
        target_op = intent.get("operation") if intent else "update_memory"
        if target_op == "update_memory":
            # Verify that ONLY Lambda memory_size differs from baseline
            # Extract memory_size
            mem_match = re.search(r'resource\s+"aws_lambda_function"\s+"dev_api"\s*\{[^}]*?memory_size\s*=\s*(\d+)', config, re.DOTALL)
            if not mem_match:
                raise ValueError("aws_lambda_function.dev_api memory_size declaration missing")
            mem_val = int(mem_match.group(1))

            req_val = intent.get("requested_value") if intent else 1024
            if req_val and mem_val != req_val:
                raise ValueError(
                    f"Configuration memory_size ({mem_val}) does not match confirmed requested value ({req_val})"
                )

            # Reconstruct expected config and compare
            expected_config = baseline.replace("memory_size = 512", f"memory_size = {mem_val}")
            if config.strip() != expected_config.strip():
                raise ValueError(
                    "Unauthorized configuration changes detected outside permitted Lambda memory_size attribute"
                )

        elif target_op == "update_tags":
            # Verify that only S3 assets Team tag is modified, Environment is preserved
            team_val = intent.get("requested_value", "core") if intent else "core"
            expected_replacement = (
                f'resource "aws_s3_bucket" "assets" {{\n  bucket = "planreview-demo-assets"\n'
                f'  tags = {{ Environment = "dev", Team = "{team_val}" }}\n}}'
            )
            expected_config = baseline.replace(
                'resource "aws_s3_bucket" "assets" {\n  bucket = "planreview-demo-assets"\n  tags = { Environment = "dev" }\n}',
                expected_replacement,
            )
            if config.strip() != expected_config.strip():
                raise ValueError(
                    "Unauthorized configuration changes detected outside permitted S3 bucket Team tag"
                )

