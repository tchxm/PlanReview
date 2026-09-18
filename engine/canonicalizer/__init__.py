"""Conservative structural normalization of Terraform's machine-readable plan."""

import re
from engine.types import CanonicalChange, Change


def flagged(value):
    if isinstance(value, dict):
        return any(flagged(v) for v in value.values())
    if isinstance(value, list):
        return any(flagged(v) for v in value)
    return value is True


def diff(before, after, unknown, sensitive_before, sensitive_after, path=""):
    if (
        sensitive_before is True
        or sensitive_after is True
        or (unknown is True and (flagged(sensitive_before) or flagged(sensitive_after)))
    ):
        return [
            Change(
                attribute=path or "*",
                before="[sensitive]",
                after="[sensitive; change indeterminate]",
            )
        ]
    if unknown is True:
        return [Change(attribute=path or "*", before=before, after="[unknown]")]
    if isinstance(before, dict) or isinstance(after, dict):
        b = before if isinstance(before, dict) else {}
        a = after if isinstance(after, dict) else {}
        u = unknown if isinstance(unknown, dict) else {}
        result = []
        for key in sorted(set(b) | set(a) | set(u)):
            sb = (
                sensitive_before.get(key, False)
                if isinstance(sensitive_before, dict)
                else False
            )
            sa = (
                sensitive_after.get(key, False)
                if isinstance(sensitive_after, dict)
                else False
            )
            result += diff(
                b.get(key),
                a.get(key),
                u.get(key, False),
                sb,
                sa,
                f"{path}.{key}".strip("."),
            )
        return result
    if flagged(sensitive_before) or flagged(sensitive_after):
        return [
            Change(
                attribute=path or "*",
                before="[sensitive]",
                after="[sensitive; change indeterminate]",
            )
        ]
    if before != after or flagged(unknown):
        return [
            Change(
                attribute=path or "*",
                before=before,
                after="[unknown]" if flagged(unknown) else after,
            )
        ]
    return []


def canonicalize(plan: dict) -> list[CanonicalChange]:
    malformed = lambda address: CanonicalChange(
        address=address,
        resource_type="unclassified",
        action="unknown",
        unknown=True,
        changes=[Change(attribute="*", after="[malformed plan]")],
    )
    if (
        not isinstance(plan, dict)
        or not str(plan.get("format_version", "")).startswith("1.")
        or not isinstance(plan.get("resource_changes"), list)
    ):
        return [malformed("[plan]")]
    configuration = plan.get("configuration", {})
    if not isinstance(configuration, dict):
        return [malformed("[configuration]")]
    providers = configuration.get("provider_config", {})
    if not isinstance(providers, dict):
        return [malformed("[providers]")]
    configs = {}

    def collect(module):
        for r in module.get("resources", []):
            configs[r["address"]] = r
        for m in module.get("module_calls", {}).values():
            collect(m.get("module", {}))

    try:
        collect(configuration.get("root_module", {}))
    except (KeyError, TypeError, AttributeError):
        return [malformed("[configuration]")]
    result = []
    for resource in plan["resource_changes"]:
        try:
            c = resource["change"]
            actions = c["actions"]
            address = resource["address"]
            if actions == ["no-op"]:
                continue
            action = (
                "REPLACE"
                if actions in [["delete", "create"], ["create", "delete"]]
                else actions[0]
                if len(actions) == 1
                and actions[0] in ["create", "update", "delete", "read"]
                else "unknown"
            )
            before = c.get("before") or {}
            after = c.get("after") or {}
            if not isinstance(before, dict) or not isinstance(after, dict):
                raise ValueError("Invalid values")
            config = configs.get(
                address, configs.get(re.sub(r"\[[^\]]+\]", "", address), {})
            )
            provider = providers.get(config.get("provider_config_key", ""), {})
            region = (
                provider.get("expressions", {})
                .get("region", {})
                .get("constant_value", "unknown")
            )
            tags = after.get("tags") or before.get("tags") or {}
            environment = tags.get("Environment", tags.get("environment", "unknown"))
            # Previous production identity must not be erased by a tag edit.
            previous_tags = before.get("tags") or {}
            if previous_tags.get("Environment", previous_tags.get("environment")) in [
                "production",
                "prod",
            ]:
                environment = "production"
            unknown = c.get("after_unknown", {})
            sb = c.get("before_sensitive", {})
            sa = c.get("after_sensitive", {})
            changes = diff(before, after, unknown, sb, sa)
            deps = sorted(
                {
                    ref
                    for ex in config.get("expressions", {}).values()
                    for ref in ex.get("references", [])
                }
            )
            result.append(
                CanonicalChange(
                    address=address,
                    resource_type=resource["type"],
                    action=action,
                    environment=environment,
                    region=region,
                    changes=changes
                    or [Change(attribute="*", after="[unclassified change]")],
                    dependencies=deps,
                    unknown=flagged(unknown)
                    or flagged(sb)
                    or flagged(sa)
                    or action == "unknown"
                    or region == "unknown"
                    or environment == "unknown"
                    or resource["type"]
                    not in {
                        "aws_lambda_function",
                        "aws_security_group",
                        "aws_s3_bucket",
                        "aws_s3_bucket_public_access_block",
                        "terraform_data",
                    }
                    or not changes,
                )
            )
        except (KeyError, TypeError, ValueError, IndexError, AttributeError):
            result.append(
                malformed(
                    resource.get("address", "[resource]")
                    if isinstance(resource, dict)
                    else "[resource]"
                )
            )
    return result
