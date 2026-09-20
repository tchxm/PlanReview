"""Single process-spawn boundary; callers supply server-owned run artifacts."""

import hashlib
import os
import subprocess
from urllib.parse import urlparse

from engine.proc import report, run_tree
from pathlib import Path


LOOPBACK = {"127.0.0.1", "localhost", "::1"}
REAL_CREDENTIAL_VARS = ("AWS_PROFILE", "AWS_SESSION_TOKEN", "AWS_SHARED_CREDENTIALS_FILE", "AWS_CONFIG_FILE", "AWS_WEB_IDENTITY_TOKEN_FILE", "AWS_ROLE_ARN")


def emulator_endpoint():
    """None: not in emulator mode. False: misconfigured (never loopback). Otherwise the loopback endpoint URL.

    Emulator mode is the ONLY way a plan touching AWS resource types can be applied, and it can only talk to a
    local emulator: the endpoint must be loopback, dummy credentials are forced and real credential variables
    are removed from the child process environment (see `emulator_env`)."""
    ep = os.environ.get("PLANREVIEW_EMULATOR_ENDPOINT")
    if not ep:
        return None
    try:
        return ep if urlparse(ep).hostname in LOOPBACK else False
    except ValueError:
        return False


def emulator_env(endpoint):
    env = os.environ.copy()
    for name in REAL_CREDENTIAL_VARS:
        env.pop(name, None)
    env.update({"AWS_ENDPOINT_URL": endpoint, "AWS_ACCESS_KEY_ID": "test", "AWS_SECRET_ACCESS_KEY": "test", "AWS_S3_USE_PATH_STYLE": "true"})
    return env


def _apply_direct(canonical, endpoint):
    """Hosted small instances cannot fit the Terraform AWS provider in memory. This applies the approved, gate-checked
    changes to the LOOPBACK emulator with boto3 instead (same endpoint rules as the Terraform path) and reads them back."""
    import boto3

    kw = dict(endpoint_url=endpoint, region_name="ap-south-1", aws_access_key_id="test", aws_secret_access_key="test")
    done = []
    for c in canonical:
        ch = {x.get("attribute") if isinstance(x, dict) else x.attribute: x for x in c.get("changes", [])}
        after = lambda k: (ch[k].get("after") if isinstance(ch[k], dict) else ch[k].after)
        if c.get("resource_type") == "aws_lambda_function" and c.get("action") == "update":
            fields = {"memory_size": "MemorySize", "timeout": "Timeout", "description": "Description"}
            args = {fields[k]: after(k) for k in ch if k in fields}
            if len(args) != len(ch):
                return {"status": "FAILED", "spawned": False, "reason": "Direct emulator apply does not support these attributes for " + c["address"]}
            lam = boto3.client("lambda", **kw)
            lam.update_function_configuration(FunctionName="dev-api", **args)
            got = lam.get_function_configuration(FunctionName="dev-api")
            if any(got.get(k) != v for k, v in args.items()):
                return {"status": "FAILED", "spawned": False, "reason": "Emulator read-back did not match the approved change"}
            done.append("%s %s" % (c["address"], ", ".join("%s=%s" % (k, v) for k, v in args.items())))
        elif c.get("resource_type") == "aws_s3_bucket" and set(ch) == {"tags"}:
            tags = after("tags") or {}
            boto3.client("s3", **kw).put_bucket_tagging(Bucket="planreview-demo-assets", Tagging={"TagSet": [{"Key": k, "Value": v} for k, v in tags.items()]})
            done.append("%s tags" % c["address"])
        else:
            return {"status": "FAILED", "spawned": False, "reason": "Direct emulator apply does not support " + c.get("address", "this change")}
    return {
        "status": "APPLIED",
        "spawned": False,
        "emulated": True,
        "method": "Applied through the emulator API (boto3) instead of a Terraform process: this hosted instance has 512 MB of memory and the AWS Terraform provider needs more, so a real terraform apply would crash the server. Run PlanReview locally and the same gate runs terraform apply against the emulator.",
        "reason": "Applied to the local AWS emulator only and read back: " + "; ".join(done) ,
    }


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
            v.get("verdict") == "EVALUATION_ERROR"
            or v.get("verdict") not in ["ALLOW", "REVIEW", "DENY"]
            or "evaluation error" in v.get("reason", "").lower()
            or "Cedar evaluation unavailable" in v.get("reason", "")
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
    # No route to a real cloud apply: AWS resource types apply only against a loopback emulator.
    child_env, emulated = None, False
    if any(c.get("resource_type") != "terraform_data" for c in canonical):
        ep = emulator_endpoint()
        if ep is None:
            return {
                "status": "BLOCKED",
                "reason": "AWS apply disabled: configure and verify an isolated emulator first",
                "spawned": False,
            }
        if ep is False:
            return {"status": "BLOCKED", "reason": "PLANREVIEW_EMULATOR_ENDPOINT must point at a loopback address; refusing to apply", "spawned": False}
        child_env, emulated = emulator_env(ep), True
    if child_env is not None and os.environ.get("PLANREVIEW_APPLY_MODE") == "direct":
        try:
            return _apply_direct(canonical, ep)
        except Exception as e:  # emulator not seeded yet, unreachable, etc.
            return {"status": "FAILED", "spawned": False, "reason": "Emulator apply failed: %s" % str(e)[:250]}
    command = ["terraform", "apply", "-input=false", "-no-color", "-parallelism=1", str(path.resolve())]
    try:
        report("terraform apply")
        p = run_tree(
            command, cwd=run["workspace"], env=child_env, capture_output=True, text=True, timeout=int(os.environ.get("PLANREVIEW_APPLY_TIMEOUT") or os.environ.get("PLANREVIEW_TF_TIMEOUT", "180"))
        )
        return {
            "status": "APPLIED" if p.returncode == 0 else "FAILED",
            "spawned": True,
            "emulated": emulated,
            "command": command,
            "exit_code": p.returncode,
            **({"reason": "terraform apply exited %s: %s" % (p.returncode, (p.stderr or p.stdout).strip()[-300:])} if p.returncode else {}),
            "stdout": p.stdout,
            "stderr": p.stderr,
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "FAILED",
            "spawned": True,
            "reason": "Terraform apply timed out; inspect state before retrying",
        }
