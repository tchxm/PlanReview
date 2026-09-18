"""Single process-spawn boundary; callers supply server-owned run artifacts."""

import hashlib, subprocess
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gate_reason(contract, verdicts, resolutions):
    if not contract.active():
        return "Contract expired or unconfirmed"
    denied = [v for v in verdicts if v["verdict"] == "DENY"]
    if denied:
        return (
            f"{len(denied)} unresolved DENY; edit configuration and create a new plan"
        )
    reviews = [
        v
        for v in verdicts
        if v["verdict"] == "REVIEW" and resolutions.get(v["address"]) != "approve"
    ]
    if reviews:
        return f"{len(reviews)} unresolved or rejected REVIEW"
    return None


def apply_saved(contract, run, resolutions):
    reason = gate_reason(contract, run["verdicts"], resolutions)
    if reason:
        return {"status": "BLOCKED", "reason": reason, "spawned": False}
    path = Path(run["plan_path"])
    if not path.exists() or digest(path) != run["plan_hash"]:
        return {
            "status": "BLOCKED",
            "reason": "Saved plan missing or hash mismatch",
            "spawned": False,
        }
    # This build intentionally has no route to a real cloud apply.
    if any(c["resource_type"] != "terraform_data" for c in run["canonical"]):
        return {
            "status": "BLOCKED",
            "reason": "AWS apply disabled: configure and verify an isolated emulator first",
            "spawned": False,
        }
    command = ["terraform", "apply", "-input=false", "-no-color", str(path.resolve())]
    try:
        p = subprocess.run(
            command, cwd=run["workspace"], capture_output=True, text=True, timeout=180
        )
        return {
            "status": "APPLIED" if p.returncode == 0 else "FAILED",
            "spawned": True,
            "command": command,
            "exit_code": p.returncode,
            "stdout": p.stdout,
            "stderr": p.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "FAILED",
            "spawned": True,
            "reason": "Terraform apply timed out; inspect state before retrying",
        }
