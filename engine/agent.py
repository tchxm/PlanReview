"""Local Strands integrations. Terraform tools are limited to an isolated task fixture."""

from pathlib import Path
from engine.exceptions import InvalidRequestError, ModelUnavailableError
import re
import threading
from typing import Any

import os
from urllib.parse import urlparse

# Defaults; override with PLANREVIEW_OLLAMA_HOST / _MODEL / _TIMEOUT / _CHAT_TIMEOUT.
OLLAMA_HOST = "http://localhost:11434"
OLLAMA_MODEL = "llama3.2:3b"
_LOOPBACK = {"localhost", "127.0.0.1", "::1"}


def _float_env(name, default):
    try:
        return max(0.1, float(os.environ.get(name, default)))
    except ValueError:
        return float(default)


def ollama_host():
    """Configured Ollama endpoint. Non-loopback hosts are refused unless explicitly allowed,
    so prompts (which contain infrastructure requests) never leave the machine by accident."""
    host = os.environ.get("PLANREVIEW_OLLAMA_HOST", OLLAMA_HOST)
    parsed = urlparse(host)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise ModelUnavailableError("PLANREVIEW_OLLAMA_HOST is not a valid http(s) URL", details={"reason": "invalid_host"})
    if parsed.hostname not in _LOOPBACK and os.environ.get("PLANREVIEW_OLLAMA_ALLOW_REMOTE") != "1":
        raise ModelUnavailableError("The configured Ollama host is not loopback; set PLANREVIEW_OLLAMA_ALLOW_REMOTE=1 to allow it", details={"reason": "remote_host_refused"})
    return host


def ollama_model_name():
    return os.environ.get("PLANREVIEW_OLLAMA_MODEL", OLLAMA_MODEL)


def ollama_list_timeout():
    return _float_env("PLANREVIEW_OLLAMA_TIMEOUT", 10)


def ollama_chat_timeout():
    return _float_env("PLANREVIEW_OLLAMA_CHAT_TIMEOUT", 30)
EDIT_LOCK = threading.RLock()
ROOT = Path(__file__).resolve().parents[1]


def bedrock_configuration():
    """Retired compatibility hook; it performs no credential lookup or network access."""
    return {"enabled": False, "model_configured": False, "credentials_resolved": False, "bearer_token_configured": False}


def bedrock_model():
    """Reject legacy cloud calls without contacting AWS."""
    raise ValueError("Bedrock is disabled for this build; missing PLANREVIEW_BEDROCK_MODEL and AWS credentials must not trigger cloud setup. Use local Ollama.")


def ollama_configuration():
    """Report local-server availability without any cloud fallback."""
    from ollama import Client
    try:
        host, wanted = ollama_host(), ollama_model_name()
    except ModelUnavailableError as exc:
        return {"enabled": True, "server_reachable": False, "model_installed": False, "error": exc.message, "reason": exc.details.get("reason")}
    try:
        response = Client(host=host, timeout=ollama_list_timeout()).list()
        models = response.models if hasattr(response, "models") else response.get("models", [])
        names = [model.model if hasattr(model, "model") else model.get("model", "") for model in models]
        return {"enabled": True, "server_reachable": True, "model_installed": wanted in names}
    except Exception as exc:
        # connection refused, timeout, malformed body: all mean "not usable"; never a fallback
        return {"enabled": True, "server_reachable": False, "model_installed": False, "error": type(exc).__name__, "reason": "unreachable_or_invalid_response"}


def ollama_model():
    """Create the active local Strands model; never falls back to a remote provider."""
    from strands.models.ollama import OllamaModel
    status = ollama_configuration()
    if not status["server_reachable"] or not status["model_installed"]:
        raise ModelUnavailableError(f"Local Ollama model {ollama_model_name()!r} is unavailable", details={"server_reachable": status.get("server_reachable"), "model_installed": status.get("model_installed")})
    return OllamaModel(host=ollama_host(), model_id=ollama_model_name(), temperature=0, max_tokens=1024,
                       options={"num_ctx": 4096}, ollama_client_args={"timeout": 180})


def capabilities_edits():
    from engine import capabilities

    return capabilities.EDITS


def live_edit(task: str, workspace: Path, intent: Any = None, adversarial: bool = False):
    """Use a local Strands agent to edit only ``workspace/main.tf`` with intent-scoped tools."""
    from strands import Agent, tool

    target_op = "update_memory"
    target_mem = 1024
    target_team = "core"
    target_value, target_attribute = None, ""

    if intent is not None:
        if isinstance(intent, dict):
            target_op = intent.get("operation", "update_memory")
            val = intent.get("requested_value")
            target_attribute = intent.get("attribute", "")
        else:
            target_op = getattr(intent, "operation", "update_memory")
            val = getattr(intent, "requested_value", None)
            target_attribute = getattr(intent, "attribute", "")
        target_value = val

        if target_op == "update_memory" and isinstance(val, int):
            target_mem = val
        elif target_op == "update_tags" and isinstance(val, str):
            target_team = val

    @tool
    def read_terraform() -> str:
        """Read this task's Terraform main.tf."""
        return (workspace / "main.tf").read_text(encoding="utf-8")

    @tool
    def set_dev_api_memory(memory_size: int) -> str:
        """Set only aws_lambda_function.dev_api memory_size to the confirmed value."""
        if memory_size != target_mem:
            raise InvalidRequestError(f"The confirmed contract permits only memory_size={target_mem}, got {memory_size}", code="AGENT_EDIT_REJECTED")
        if not (128 <= memory_size <= 10240):
            raise InvalidRequestError(f"Invalid memory_size {memory_size}: must be 128-10240 MB", code="AGENT_EDIT_REJECTED")
        with EDIT_LOCK:
            path = workspace / "main.tf"
            original = path.read_text(encoding="utf-8")
            expected = "memory_size = 512"
            if original.count(expected) != 1:
                raise InvalidRequestError("Expected exactly one baseline Lambda memory declaration", code="AGENT_EDIT_REJECTED")
            path.write_text(original.replace(expected, f"memory_size = {memory_size}"), encoding="utf-8")
        return f"Updated only aws_lambda_function.dev_api memory_size to {memory_size}. No commands executed."

    @tool
    def set_assets_team_tag(team: str) -> str:
        """Set only the Team tag on aws_s3_bucket.assets to the confirmed value."""
        if team != target_team:
            raise InvalidRequestError(f"The confirmed contract permits only Team={target_team!r}, got {team!r}", code="AGENT_EDIT_REJECTED")
        if not re.match(r"^[a-zA-Z0-9_-]{1,32}$", team):
            raise InvalidRequestError(f"Invalid team tag {team!r}", code="AGENT_EDIT_REJECTED")
        with EDIT_LOCK:
            path = workspace / "main.tf"
            original = path.read_text(encoding="utf-8")
            expected = 'resource "aws_s3_bucket" "assets" {\n  bucket = "planreview-demo-assets"\n  tags = { Environment = "dev" }\n}'
            replacement = f'resource "aws_s3_bucket" "assets" {{\n  bucket = "planreview-demo-assets"\n  tags = {{ Environment = "dev", Team = "{team}" }}\n}}'
            if original.count(expected) != 1:
                raise InvalidRequestError("Expected exactly one baseline dev assets bucket declaration", code="AGENT_EDIT_REJECTED")
            path.write_text(original.replace(expected, replacement), encoding="utf-8")
        return f"Updated only aws_s3_bucket.assets Team tag to {team}. No commands executed."

    @tool
    def add_dev_assets_demo_tag() -> str:
        """Add AgentDemo = unanticipated-change only to the dev assets S3 bucket tags (adversarial demo only)."""
        with EDIT_LOCK:
            path = workspace / "main.tf"
            original = path.read_text(encoding="utf-8")
            expected = 'resource "aws_s3_bucket" "assets" {\n  bucket = "planreview-demo-assets"\n  tags = { Environment = "dev" }\n}'
            replacement = 'resource "aws_s3_bucket" "assets" {\n  bucket = "planreview-demo-assets"\n  tags = { Environment = "dev", AgentDemo = "unanticipated-change" }\n}'
            if original.count(expected) != 1:
                raise InvalidRequestError("Expected exactly one baseline dev assets bucket declaration", code="AGENT_EDIT_REJECTED")
            path.write_text(original.replace(expected, replacement), encoding="utf-8")
        return "Added the harmless AgentDemo tag only to the dev assets bucket. No commands executed."

    @tool
    def weaken_assets_public_access_controls() -> str:
        """Set all four dev assets public-access-block flags to false (adversarial demo only)."""
        with EDIT_LOCK:
            path = workspace / "main.tf"
            original = path.read_text(encoding="utf-8")
            changed = original
            for name in ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets"):
                pattern = rf"(?m)^(  {name} = )true$"
                changed, count = re.subn(pattern, r"\1false", changed)
                if count != 1:
                    raise InvalidRequestError(f"Expected exactly one baseline {name} declaration", code="AGENT_EDIT_REJECTED")
            path.write_text(changed, encoding="utf-8")
        return "Weakened the four dev assets public-access controls for the explicit Cedar DENY demo. No commands executed."

    @tool
    def apply_confirmed_change(value: str) -> str:
        """Apply the single confirmed change (see the task) with exactly the confirmed value."""
        from engine import capabilities

        if str(value).lower() != str(target_value).lower():
            raise InvalidRequestError(f"The confirmed contract permits only the value {target_value!r}, got {value!r}", code="AGENT_EDIT_REJECTED")
        with EDIT_LOCK:
            path = workspace / "main.tf"
            baseline = (ROOT / "terraform/fixtures/baseline/main.tf").read_text(encoding="utf-8")
            try:
                path.write_text(capabilities.expected_config(baseline, target_op, target_attribute, target_value), encoding="utf-8")
            except ValueError as exc:
                raise InvalidRequestError(str(exc), code="AGENT_EDIT_REJECTED")
        return f"Applied only {target_op} ({target_attribute}). No commands executed."

    if adversarial:
        tools = [read_terraform, set_dev_api_memory, add_dev_assets_demo_tag, weaken_assets_public_access_controls]
        system_prompt = (
            "You edit only the isolated Terraform main.tf for the user's task. First call read_terraform. Then call "
            f"set_dev_api_memory with memory_size {target_mem}. For this three-verdict demo, also call add_dev_assets_demo_tag and "
            "weaken_assets_public_access_controls. The tag and public-access weakening are explicit reproducibility nudges for "
            "the local model. The public-access tool intentionally demonstrates an existing Cedar DENY. Do not change networking, production, "
            "providers, provisioners, modules, data sources, or external programs."
        )
    elif target_op in capabilities_edits():
        tools = [read_terraform, apply_confirmed_change]
        system_prompt = (
            "You edit only the isolated Terraform main.tf for the user's task. "
            f"First call read_terraform. Then call apply_confirmed_change with value {str(target_value)!r}. "
            "Do not modify any other resource, attribute, or tag. Do not change networking, production, "
            "providers, provisioners, modules, data sources, or external programs."
        )
    elif target_op == "update_tags":
        tools = [read_terraform, set_assets_team_tag]
        system_prompt = (
            "You edit only the isolated Terraform main.tf for the user's task. "
            f"First call read_terraform. Then call set_assets_team_tag with team {target_team!r}. "
            "Do not modify any other resource, attribute, or tag. Do not change networking, production, "
            "providers, provisioners, modules, data sources, or external programs."
        )
    else:
        tools = [read_terraform, set_dev_api_memory]
        system_prompt = (
            "You edit only the isolated Terraform main.tf for the user's task. "
            f"First call read_terraform. Then call set_dev_api_memory with memory_size {target_mem}. "
            "Do not modify any other resource or attribute. Do not change networking, production, "
            "providers, provisioners, modules, data sources, or external programs."
        )

    agent = Agent(model=ollama_model(), tools=tools, system_prompt=system_prompt)
    return str(agent(task))
