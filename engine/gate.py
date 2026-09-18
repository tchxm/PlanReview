"""Single process-spawn boundary; callers supply server-owned run artifacts."""

import hashlib
import subprocess
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def gate_reason(contract, verdicts, resolutions, canonical=None):
    if not contract.active():
        return "Contract expired or unconfirmed"
    if verdicts is None:
        return "Missing evaluation verdicts; evaluate plan before applying"
    if not isinstance(verdicts, list):
        return "Invalid evaluation verdicts structure"

    # Evaluation error verification: Cedar failures cannot become approvable REVIEWs
    eval_errors = [
        v
        for v in verdicts
        if isinstance(v, dict)
        and (
            "Cedar evaluation unavailable" in v.get("reason", "")
            or "evaluation error" in v.get("reason", "").lower()
            or v.get("verdict") == "EVALUATION_ERROR"
        )
    ]
    if eval_errors:
        return f"{len(eval_errors)} evaluation errors; cannot apply without valid policy evaluation"

    # Canonical-to-verdict consistency and completeness checks
    if canonical is not None and isinstance(canonical, list):
        if len(canonical) > 0 and len(verdicts) == 0:
            return "Empty verdicts for nonempty plan; plan must be evaluated"
        canonical_addrs = [
            c.get("address") for c in canonical if isinstance(c, dict) and c.get("address")
        ]
        verdict_addrs = [
            v.get("address") for v in verdicts if isinstance(v, dict) and v.get("address")
        ]
        if len(verdict_addrs) != len(set(verdict_addrs)):
            return "Duplicate verdicts detected for resource address"
        if canonical_addrs and len(verdicts) < len(canonical_addrs):
            return "Missing evaluation verdicts for canonical plan resources"
        if canonical_addrs and len(verdicts) > len(canonical_addrs):
            return "Extra evaluation verdicts not present in canonical plan"
        if canonical_addrs and verdict_addrs and set(canonical_addrs) != set(verdict_addrs):
            return "Mismatched verdicts: verdict addresses do not match canonical plan addresses"

    res_map = resolutions if isinstance(resolutions, dict) else {}
    denied = [v for v in verdicts if isinstance(v, dict) and v.get("verdict") == "DENY"]
    if denied:
        return f"{len(denied)} unresolved DENY; edit configuration and create a new plan"

    reviews = [
        v
        for v in verdicts
        if isinstance(v, dict)
        and v.get("verdict") == "REVIEW"
        and res_map.get(v.get("address")) != "approve"
    ]
    if reviews:
        return f"{len(reviews)} unresolved or rejected REVIEW"
    return None


def apply_saved(contract, run, resolutions):
    reason = gate_reason(contract, run.get("verdicts"), resolutions, canonical=run.get("canonical"))
    if reason:
        return {"status": "BLOCKED", "reason": reason, "spawned": False}
    plan_path = run.get("plan_path")
    if not plan_path:
        return {
            "status": "BLOCKED",
            "reason": "Saved plan missing or hash mismatch",
            "spawned": False,
        }
    path = Path(plan_path)
    if not path.exists() or digest(path) != run.get("plan_hash"):
        return {
            "status": "BLOCKED",
            "reason": "Saved plan missing or hash mismatch",
            "spawned": False,
        }
    canonical = run.get("canonical")
    if canonical is None or not isinstance(canonical, list):
        return {
            "status": "BLOCKED",
            "reason": "Missing or invalid canonical plan data",
            "spawned": False,
        }
    # This build intentionally has no route to a real cloud apply.
    if any(c.get("resource_type") != "terraform_data" for c in canonical):
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
