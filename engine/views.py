"""Safe API views. Raw evidence (paths, full Terraform stdout/JSON, edited .tf text)
stays server side and is only served by the evidence-scoped endpoint."""

import hashlib

RUN_HIDDEN = {"workspace", "plan_path", "raw_path", "plan_stdout", "raw_plan"}
TASK_HIDDEN = {"workspace"}


def plan_summary(canonical):
    """Counts by action derived from canonical changes (None until canonicalized)."""
    if canonical is None:
        return None
    out = {"total": len(canonical), "create": 0, "update": 0, "delete": 0, "replace": 0, "other": 0}
    for c in canonical:
        a = c.get("action")
        out[a if a in out else "other"] += 1
    return out


def run_view(run):
    r = {k: v for k, v in run.items() if k not in RUN_HIDDEN}
    r["plan_summary"] = plan_summary(run.get("canonical"))
    r["raw_evidence_available"] = bool(run.get("raw_hash"))
    return r


def task_view(task):
    t = {k: v for k, v in task.items() if k not in TASK_HIDDEN}
    t["runs"] = [run_view(r) for r in task.get("runs", [])]
    return t


def audit_event_view(event):
    kind, data = event["kind"], event["data"]
    if kind in ("draft", "human_confirmation") and isinstance(data, dict) and "runs" in data:
        safe = task_view(data)
    elif kind in ("plan", "canonical", "verdicts") and isinstance(data, dict):
        safe = run_view(data)
    elif kind == "agent_edits" and isinstance(data, dict):
        tf = data.get("terraform", "")
        safe = {
            "mode": data.get("mode"),
            "variant": data.get("variant"),
            "terraform_sha256": hashlib.sha256(tf.encode()).hexdigest() if tf else None,
        }
    else:
        safe = data
    return {"id": event["id"], "timestamp": event["timestamp"], "kind": kind, "data": safe}


def audit_view(events):
    return [audit_event_view(e) for e in events]
