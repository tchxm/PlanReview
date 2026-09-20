"""Data-driven edit capabilities beyond the two original operations.

One entry per operation defines everything the system needs to know about it:
  * the ONE resource it may touch and the attribute (or attribute pattern) it may change,
  * how to validate the requested value,
  * `expected_config(baseline, ...)`: the exact main.tf a correct edit produces.

The guard compares the agent's workspace with `expected_config` byte for byte (after strip), so an
edit that changes anything else -- another attribute, another resource, an extra tag -- is rejected
before Terraform ever runs. Replay mode and the live agent both write `expected_config`, never
free-form text. Adding an operation = adding an entry here, one address allowlist name entry in
engine/intent, and (optionally) a phrase in the deterministic extractor.
"""

import re

LAMBDA = ("aws_lambda_function.dev_api", "aws_lambda_function")
BUCKET = ("aws_s3_bucket.assets", "aws_s3_bucket")

_LAMBDA_MEM_LINE = "  memory_size = 512\n"
_BUCKET_TAGS = 'resource "aws_s3_bucket" "assets" {\n  bucket = "planreview-demo-assets"\n  tags = { Environment = "dev" }\n}'

_ENV_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_ENV_VAL = re.compile(r"^[A-Za-z0-9_.:/-]{1,64}$")
_SECRET_LIKE = re.compile(r"SECRET|PASSWORD|PASSWD|TOKEN|KEY|CREDENTIAL|PRIVATE|AUTH", re.IGNORECASE)
_TAG_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,31}$")
_TAG_VAL = re.compile(r"^[a-zA-Z0-9_-]{1,32}$")


def _once(text, anchor, what):
    if text.count(anchor) != 1:
        raise ValueError(f"Expected exactly one baseline {what}")
    return text


def _timeout(baseline, attribute, value):
    _once(baseline, _LAMBDA_MEM_LINE, "Lambda memory declaration")
    return baseline.replace(_LAMBDA_MEM_LINE, f"{_LAMBDA_MEM_LINE}  timeout = {value}\n")


def _env(baseline, attribute, value):
    key = attribute.rsplit(".", 1)[1]
    _once(baseline, _LAMBDA_MEM_LINE, "Lambda memory declaration")
    block = f'  environment {{\n    variables = {{ {key} = "{value}" }}\n  }}\n'
    return baseline.replace(_LAMBDA_MEM_LINE, _LAMBDA_MEM_LINE + block)


def _s3_tag(baseline, attribute, value):
    key = attribute.split(".", 1)[1]
    _once(baseline, _BUCKET_TAGS, "dev assets bucket declaration")
    new = _BUCKET_TAGS.replace('tags = { Environment = "dev" }', f'tags = {{ Environment = "dev", {key} = "{value}" }}')
    return baseline.replace(_BUCKET_TAGS, new)


def _s3_versioning(baseline, attribute, value):
    _once(baseline, _BUCKET_TAGS, "dev assets bucket declaration")
    new = _BUCKET_TAGS.replace(
        '  tags = { Environment = "dev" }\n}', '  tags = { Environment = "dev" }\n  versioning {\n    enabled = true\n  }\n}'
    )
    return baseline.replace(_BUCKET_TAGS, new)


def _int_range(lo, hi, label):
    def check(attribute, value):
        if not isinstance(value, int) or isinstance(value, bool):
            return f"{label} must be an integer, got {type(value).__name__} ({value!r})."
        if not lo <= value <= hi:
            return f"{label} must be between {lo} and {hi}, got {value}."
        return None

    return check


def _check_env(attribute, value):
    key = attribute.rsplit(".", 1)[-1]
    if not _ENV_KEY.match(key):
        return f"Environment variable name {key!r} must be UPPER_SNAKE_CASE (1-32 chars)."
    if key.startswith("AWS_") or key.startswith("_"):
        return f"Environment variable {key!r} is reserved by Lambda."
    if _SECRET_LIKE.search(key):
        return f"Environment variable {key!r} looks like a secret; secrets are not editable here."
    if not isinstance(value, str) or not _ENV_VAL.match(value):
        return "Environment variable value must be 1-64 characters of letters, digits and _ . : / -"
    return None


def _check_tag(attribute, value):
    key = attribute.split(".", 1)[1] if "." in attribute else ""
    if not _TAG_KEY.match(key):
        return f"Tag key {key!r} must start with a letter and use letters, digits, _ or - (max 32)."
    if key.lower() == "environment":
        return "The Environment tag drives policy decisions and cannot be edited."
    if key.lower().startswith("aws"):
        return "Tag keys starting with 'aws' are reserved."
    if not isinstance(value, str) or not _TAG_VAL.match(value):
        return f"Tag value must be alphanumeric/hyphen/underscore (1-32 chars), got {value!r}."
    return None


def _check_versioning(attribute, value):
    if value is not True:
        return "Only enabling versioning (requested_value true) is supported."
    return None


# operation -> registry entry (shape matches intent.CAPABILITY_REGISTRY) + behaviour
EDITS = {
    "update_timeout": {
        "resource_address": LAMBDA[0], "resource_type": LAMBDA[1], "attribute": "timeout",
        "allowed_operations": ("update",), "allowed_regions": ("ap-south-1",),
        "description": "Set AWS Lambda timeout between 1 and 900 seconds",
        "check": _int_range(1, 900, "Lambda timeout"), "edit": _timeout,
    },
    "set_lambda_env": {
        "resource_address": LAMBDA[0], "resource_type": LAMBDA[1], "attribute_pattern": r"^environment\.variables\.[A-Z][A-Z0-9_]{0,31}$",
        "allowed_operations": ("update",), "allowed_regions": ("ap-south-1",),
        "description": "Add one non-secret environment variable to the dev-api Lambda",
        "check": _check_env, "edit": _env,
    },
    "set_s3_tag": {
        "resource_address": BUCKET[0], "resource_type": BUCKET[1], "attribute_pattern": r"^tags\.[A-Za-z][A-Za-z0-9_-]{0,31}$",
        "allowed_operations": ("update",), "allowed_regions": ("ap-south-1",),
        "description": "Add one non-policy tag to the dev assets S3 bucket",
        "check": _check_tag, "edit": _s3_tag,
    },
    "enable_s3_versioning": {
        "resource_address": BUCKET[0], "resource_type": BUCKET[1], "attribute": "versioning.enabled",
        "allowed_operations": ("update",), "allowed_regions": ("ap-south-1",),
        "description": "Enable versioning on the dev assets S3 bucket",
        "check": _check_versioning, "edit": _s3_versioning,
    },
}


def check_value(operation, attribute, value):
    """Return an error string, or None when the value is acceptable."""
    return EDITS[operation]["check"](attribute, value)


def expected_config(baseline, operation, attribute, value):
    """The exact main.tf a correct edit of `operation` produces from `baseline`."""
    return EDITS[operation]["edit"](baseline, attribute, value)


def registry_view():
    """Registry entries without callables, in the shape intent.CAPABILITY_REGISTRY uses."""
    return {op: {k: v for k, v in e.items() if k not in ("check", "edit")} for op, e in EDITS.items()}
