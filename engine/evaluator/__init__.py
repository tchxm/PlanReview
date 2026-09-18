from pathlib import Path
from engine.types import Contract, CanonicalChange, Verdict
from engine.mapper import context

POLICY = Path(__file__).resolve().parents[2] / "cedar/policies/security.cedar"


def evaluate(contract: Contract, change: CanonicalChange, backend="cedar") -> Verdict:
    if not contract.active():
        raise ValueError("Contract expired or unconfirmed; no verdicts are trusted")
    ctx = context(contract, change)
    ids = []
    if backend == "deterministic":
        forbidden = (
            ctx["production"]
            or ctx["public_access"]
            or (ctx["networking"] and ctx["deny_networking"])
        )
        allowed = (
            ctx["address"] in ctx["addresses"]
            and ctx["resource_type"] in ctx["types"]
            and ctx["operation"] in ctx["operations"]
            and ctx["region"] in ctx["regions"]
            and not ctx["unknown"]
        )
        value = "DENY" if forbidden else "ALLOW" if allowed else "REVIEW"
    else:
        try:
            import cedarpy

            result = cedarpy.is_authorized(
                {
                    "principal": 'User::"local"',
                    "action": 'Action::"evaluate"',
                    "resource": 'Resource::"change"',
                    "context": ctx,
                },
                POLICY.read_text(),
                [],
            )
            details = result.diagnostics
            if details.errors:
                raise ValueError(str(details.errors))
            ids = [str(x) for x in details.reasons]
            value = "ALLOW" if result.allowed else "DENY" if ids else "REVIEW"
        except Exception as exc:
            return Verdict(
                address=change.address,
                verdict="REVIEW",
                changes=change.changes,
                reason=f"Cedar evaluation unavailable: {type(exc).__name__}: {exc}",
            )
    reason = (
        (
            "Explicit policy forbids "
            + ", ".join(
                k
                for k in ["production", "public_access", "networking"]
                if ctx[k] and (k != "networking" or ctx["deny_networking"])
            )
        )
        if value == "DENY"
        else "Exact address, resource type, operation and region match confirmed scope"
        if value == "ALLOW"
        else "Unknown or sensitive values require review"
        if change.unknown
        else "Change is outside the confirmed address/type/operation/region scope"
    )
    return Verdict(
        address=change.address,
        verdict=value,
        changes=change.changes,
        reason=reason,
        determining_policies=ids,
    )


def evaluate_all(contract, changes, backend="cedar"):
    if not contract.active():
        raise ValueError("Contract expired or unconfirmed; apply blocked")
    verdicts = [evaluate(contract, c, backend) for c in changes]
    if len(changes) > contract.max_changed_resources:
        for v in verdicts:
            if v.verdict == "ALLOW":
                v.verdict = "REVIEW"
                v.reason = f"Resource count {len(changes)} exceeds contract maximum {contract.max_changed_resources}"
    if contract.max_cost_delta is not None:
        for v in verdicts:
            if v.verdict == "ALLOW":
                v.verdict = "REVIEW"
                v.reason = (
                    "Cost delta is unavailable; configured cost cap cannot be verified"
                )
    return verdicts
