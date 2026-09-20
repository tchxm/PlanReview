"""PlanBound site API: the browser experience's boundary engine, computed on the server.

What this is: a per-browser-session sandbox for the interactive site (confirm a boundary, evaluate a
sample or pasted plan, resolve REVIEW items, simulate an apply, read a hash-chained evidence trail).
It is a faithful port of the in-browser engine in design/planbound-site.html (same rules, same order,
same hashes), so server mode and offline mode produce identical verdicts. When both exist the server
is authoritative: the client only displays what this module computes.

What this is NOT: the sandbox engine below never touches Terraform, cloud accounts, the Cedar/task pipeline or the task
database. "Apply" only records a simulated apply event. It needs no bearer token because it holds no
real data and no capability; it is same-origin only (see the Origin check in api.py), rate limited per
address, body-size limited, and bounded (session count, records per session, plan size).

Evidence chain: every record carries prev_hash and hash = HMAC-SHA256(site key, prev_hash + canonical
record). The key is derived from the API secret, so the chain detects edits made without the key; it
is not a defence against someone who can read the secret. See docs/audit-integrity.md for the same
trust model on the task audit log.
"""

import copy
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Body

from engine.exceptions import PlanReviewError

CLASSES = ["aws_s3_bucket", "aws_security_group", "aws_iam_role", "aws_db_instance", "aws_lambda_function"]
MAX_RECORDS = 200
MAX_SESSIONS = 2000
SESSION_TTL = 14 * 24 * 3600
GENESIS = "0" * 64
SID_RE = re.compile(r"^[0-9a-f]{24}$")


def _chg(id_, resource, name, before, after, op="update", stateful=False, blast=1):
    return {"id": id_, "resource": resource, "name": name, "op": op, "before": before, "after": after, "attrs": {"stateful": stateful, "blast": blast}}


PLANS = {
    "sample-a": [
        _chg("chg_1", "aws_s3_bucket", "app-logs-bucket", {"acl": "private"}, {"acl": "public-read"}),
        _chg("chg_2", "aws_security_group", "web-sg", {"cidr_blocks": ["10.0.0.0/16"]}, {"cidr_blocks": ["0.0.0.0/0"]}),
        _chg("chg_3", "aws_iam_role", "ec2-role", {"policy": "AmazonS3FullAccess"}, {"policy": "AmazonS3ReadOnlyAccess"}),
    ],
    "sample-b": [
        _chg("chg_1", "aws_s3_bucket", "app-logs-bucket", {"acl": "public-read"}, {"acl": "private", "block_public_access": True}),
        _chg("chg_2", "aws_security_group", "web-sg", {"cidr_blocks": ["0.0.0.0/0"]}, {"cidr_blocks": ["10.0.0.0/16"]}),
        _chg("chg_3", "aws_iam_role", "ec2-role", {"policy": "AmazonS3FullAccess"}, {"policy": "AmazonS3ReadOnlyAccess"}),
        _chg("chg_4", "aws_s3_bucket", "artifacts", {"versioning": False}, {"versioning": True}),
    ],
    "sample-c": [
        _chg("chg_1", "aws_db_instance", "orders-prod", {"storage": 20}, {"storage": 40}, "replace", True, 3),
        _chg("chg_2", "aws_security_group", "prod-api", {"cidr_blocks": ["10.0.0.0/16"]}, {"cidr_blocks": ["0.0.0.0/0"]}),
    ],
}


class SiteError(PlanReviewError):
    def __init__(self, message, code="INVALID_INPUT", status=400):
        super().__init__(message, code=code, status_code=status)


# ------------------------------------------------------------ canonical forms
def _norm(v):
    """JSON values as JavaScript would print them: 5.0 -> 5."""
    if isinstance(v, float) and v.is_integer() and abs(v) < 1e15:
        return int(v)
    if isinstance(v, dict):
        return {k: _norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_norm(x) for x in v]
    return v


def js_json(v):
    """Equivalent of JSON.stringify: compact, non-ASCII kept."""
    return json.dumps(_norm(v), separators=(",", ":"), ensure_ascii=False)


def fnv(text):
    n = 0xCBF29CE484222325
    for byte in text.encode("utf-8"):
        n ^= byte
        n = (n * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return format(n, "016x")


def contract_hash(c):
    canon = {"environment": c["environment"], "allowed": sorted(c["allowed"]), "maxBlast": c["maxBlast"], "note": c["note"], "confirmed": bool(c["confirmed"])}
    return hashlib.sha256(js_json(canon).encode("utf-8")).hexdigest()[:12]


def plan_key(changes):
    return fnv(js_json(changes))


def _utf16_len(s):
    return len(s.encode("utf-16-le")) // 2


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


# ---------------------------------------------------------------- validation
def blank_contract():
    return {"environment": "dev", "allowed": CLASSES[:3], "maxBlast": 5, "note": "", "confirmed": False, "hash": None, "confirmedAt": None}


def validate_contract(c):
    msg = "Select at least one resource class and use a task note of 240 characters or fewer."
    if not isinstance(c, dict):
        raise SiteError(msg)
    allowed, blast, note = c.get("allowed"), c.get("maxBlast"), c.get("note")
    if isinstance(blast, float) and blast.is_integer():
        blast = int(blast)
    ok = (
        c.get("environment") in ("dev", "staging", "prod")
        and isinstance(allowed, list)
        and allowed
        and all(isinstance(x, str) and x in CLASSES for x in allowed)
        and len(set(allowed)) == len(allowed)
        and isinstance(blast, int)
        and not isinstance(blast, bool)
        and 1 <= blast <= 10
        and isinstance(note, str)
        and _utf16_len(note) <= 240
    )
    if not ok:
        raise SiteError(msg)
    return {"environment": c["environment"], "allowed": list(allowed), "maxBlast": blast, "note": note, "confirmed": False, "hash": None, "confirmedAt": None}


def validate_plan(data):
    if not isinstance(data, list) or not 1 <= len(data) <= 100:
        raise SiteError("Provide an array of 1–100 changes.")
    ids, out = set(), []
    for i, c in enumerate(data):
        n = i + 1
        if not isinstance(c, dict):
            raise SiteError(f"Change {n} must be an object.")
        for k in ("id", "resource", "name"):
            v = c.get(k)
            if not isinstance(v, str) or not v.strip() or _utf16_len(v) > 180:
                raise SiteError(f"Change {n} needs a short {k}.")
        if c["id"] in ids:
            raise SiteError("Change IDs must be unique.")
        ids.add(c["id"])
        if c.get("op") not in ("create", "update", "delete", "replace"):
            raise SiteError("Use create, update, delete or replace.")
        for k in ("before", "after"):
            if k not in c or (c[k] is not None and not isinstance(c[k], dict)):
                raise SiteError(f"{k} must be an object or null.")
        a = c.get("attrs")
        if not isinstance(a, dict) or not isinstance(a.get("stateful"), bool) or not _is_num(a.get("blast")) or a["blast"] < 0:
            raise SiteError("Each change needs attrs.stateful (boolean) and attrs.blast (nonnegative number).")
        out.append(_norm({"id": c["id"], "resource": c["resource"], "name": c["name"], "op": c["op"], "before": c["before"], "after": c["after"], "attrs": {"stateful": a["stateful"], "blast": a["blast"]}}))
    return out


# ------------------------------------------------------------ rules (ordered)
def _v(verdict, rule, reason):
    return {"verdict": verdict, "rule": rule, "reason": reason}


def evaluate(chg, c):
    """First match wins. Order and wording are identical to PB.engine.evaluate."""
    if not c["confirmed"]:
        return _v("DENY", "contract.unconfirmed", "No confirmed boundary exists.")
    if chg["resource"] not in c["allowed"]:
        return _v("DENY", "scope.resource_class", chg["resource"] + " is outside the confirmed scope.")
    after = chg["after"]
    if isinstance(after, dict) and after.get("acl") in ("public-read", "public-read-write"):
        return _v("DENY", "s3.public_acl", "Public bucket ACL exposes data.")
    if chg["resource"] == "aws_security_group" and "0.0.0.0/0" in js_json(after):
        if c["environment"] == "prod":
            return _v("DENY", "sg.open_ingress.prod", "Open ingress is prohibited in prod.")
        return _v("REVIEW", "sg.open_ingress.dev", "Unrestricted ingress needs human judgment.")
    if chg["resource"] == "aws_iam_role" and re.search(r"FullAccess|AdministratorAccess", js_json(after)):
        return _v("DENY", "iam.excess", "Excessive permissions.")
    if chg["attrs"]["stateful"] and chg["op"] in ("delete", "replace"):
        return _v("REVIEW", "stateful.destructive", "Destructive change to stateful resource.")
    if chg["attrs"]["blast"] > c["maxBlast"]:
        return _v("REVIEW", "blast.radius", "Blast radius exceeds contract limit.")
    return _v("ALLOW", "within.boundary", "Within the confirmed boundary.")


def scope_of(st):
    return str(st["contract"]["hash"] or "unconfirmed") + ":" + plan_key(st["changes"])


def resolution(st, cid):
    return st["resolutions"].get(scope_of(st) + ":" + cid)


def derive(st):
    verdicts = {c["id"]: evaluate(c, st["contract"]) for c in st["changes"]}
    gate = bool(st["contract"]["confirmed"] and st["changes"] and all(v["verdict"] == "ALLOW" or (v["verdict"] == "REVIEW" and resolution(st, cid) in ("approved", "rejected")) for cid, v in verdicts.items()))
    return verdicts, gate


# ------------------------------------------------------------------ evidence
class Chain:
    def __init__(self, key):
        self.key = key

    def mac(self, prev, rec):
        body = {k: v for k, v in rec.items() if k != "hash"}
        return hmac.new(self.key, (prev + js_json(body)).encode("utf-8"), hashlib.sha256).hexdigest()

    def append(self, st, rec):
        rec["prev_hash"] = st["head"]
        rec["hash"] = self.mac(st["head"], rec)
        st["head"] = rec["hash"]
        st["records"].append(rec)
        del st["records"][:-MAX_RECORDS]

    def verify(self, st):
        recs, prev, first_bad = st["records"], None, None
        for i, r in enumerate(recs):
            expected_prev = recs[i - 1]["hash"] if i else r.get("prev_hash")
            if r.get("prev_hash") != expected_prev or not hmac.compare_digest(str(r.get("hash")), self.mac(r.get("prev_hash", ""), r)):
                first_bad = {"index": i, "id": r.get("id")}
                break
        head_ok = (not recs and st["head"] == GENESIS) or (bool(recs) and recs[-1].get("hash") == st["head"])
        ok = first_bad is None and head_ok
        if first_bad is None and not head_ok:
            first_bad = {"index": len(recs), "id": None, "problem": "chain head does not match the newest record (records removed or replaced)"}
        return {"ok": ok, "records": len(recs), "first_broken": first_bad, "latest_hash": recs[-1]["hash"] if recs else None, "algorithm": "HMAC-SHA256 chain (server key)", "verified_by": "server", "scope": "server session"}


def make_record(st, chg, v, event="evaluated", seed=False):
    resolved = resolution(st, chg["id"])
    st["seq"] += 1
    return {
        "id": st["seq"],
        "status": "applied" if event == "applied" else resolved if event == "resolved" else v["verdict"].lower(),
        "verdict": v["verdict"],
        "event": event,
        "sample_data": True,
        "seed": seed,
        "timestamp": int(time.time()) - ((13 - st["seq"]) * 1800 if seed else 0),
        "plan": {"id": st["planId"], "hash": plan_key(st["changes"])},
        "contract": copy.deepcopy(st["contract"]),
        "change_0": {"resource": chg["resource"] + "." + chg["name"], "op": chg["op"], "rule": v["rule"], "verdict": v["verdict"]},
        "change": copy.deepcopy(chg),
        "reason": v["reason"],
        "evidence": {"checked_against": v["rule"], "blast": chg["attrs"]["blast"], "max_blast": st["contract"]["maxBlast"]},
        "resolution": resolved,
        "approval": {"intent_confirmed": st["contract"]["confirmed"], "plan_evaluated": True, "human_resolved": v["verdict"] == "ALLOW" or bool(resolved)},
    }


# ------------------------------------------------------------------- storage
class SiteStore:
    def __init__(self, path, key):
        self.path, self.chain = Path(path), Chain(key)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as c:
            c.execute("CREATE TABLE IF NOT EXISTS site_sessions (id TEXT PRIMARY KEY, state TEXT NOT NULL, updated INTEGER NOT NULL)")

    def _conn(self):
        c = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        c.execute("PRAGMA journal_mode=WAL")
        return c

    def new_state(self):
        st = {"contract": blank_contract(), "planId": "sample-a", "changes": copy.deepcopy(PLANS["sample-a"]), "resolutions": {}, "records": [], "head": GENESIS, "seq": 0, "appliedScope": None, "metrics": {"plansEvaluated": 4, "changesGated": 8, "humanDecisions": 0}}
        fresh = st["contract"]
        seed = {**blank_contract(), "confirmed": True, "confirmedAt": "2026-09-19T00:00:00.000Z"}
        seed["hash"] = contract_hash(seed)
        st["contract"] = seed
        for i in range(12):  # the same 12 seeded sample records the browser creates on init
            c = PLANS["sample-a"][i % 3]
            self.chain.append(st, make_record(st, c, evaluate(c, seed), "evaluated", True))
        st["contract"] = fresh
        self._evaluated(st)
        return st

    def _evaluated(self, st):
        verdicts, _ = derive(st)
        for c in st["changes"]:
            self.chain.append(st, make_record(st, c, verdicts[c["id"]]))
        st["metrics"]["plansEvaluated"] += 1
        st["metrics"]["changesGated"] += sum(1 for v in verdicts.values() if v["verdict"] != "ALLOW")

    def create(self):
        sid, now = secrets.token_hex(12), int(time.time())
        st = self.new_state()
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM site_sessions WHERE updated < ?", (now - SESSION_TTL,))
            n = c.execute("SELECT COUNT(*) FROM site_sessions").fetchone()[0]
            if n >= MAX_SESSIONS:
                c.execute("DELETE FROM site_sessions WHERE id IN (SELECT id FROM site_sessions ORDER BY updated LIMIT ?)", (n - MAX_SESSIONS + 1,))
            c.execute("INSERT INTO site_sessions VALUES (?,?,?)", (sid, json.dumps(st), now))
            c.execute("COMMIT")
        return sid, st

    def mutate(self, sid, fn):
        """Load, apply fn(state) -> result, save; atomic per session."""
        if not SID_RE.match(sid or ""):
            raise SiteError("Unknown session.", "SESSION_NOT_FOUND", 404)
        with self._lock, self._conn() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT state FROM site_sessions WHERE id=?", (sid,)).fetchone()
            if not row:
                c.execute("ROLLBACK")
                raise SiteError("This session no longer exists. Start a new one.", "SESSION_NOT_FOUND", 404)
            st = json.loads(row[0])
            try:
                result = fn(st)
            except Exception:
                c.execute("ROLLBACK")
                raise
            c.execute("UPDATE site_sessions SET state=?, updated=? WHERE id=?", (json.dumps(st), int(time.time()), sid))
            c.execute("COMMIT")
        return result, st


def view(sid, st):
    verdicts, gate = derive(st)
    return {
        "sessionId": sid,
        "contract": st["contract"],
        "planId": st["planId"],
        "planHash": plan_key(st["changes"]),
        "changes": st["changes"],
        "resolutions": st["resolutions"],
        "verdicts": verdicts,
        "gateOpen": gate,
        "records": st["records"],
        "metrics": st["metrics"],
        "appliedScope": st["appliedScope"],
    }


# --------------------------------------------------------------------- routes
router = APIRouter(prefix="/api/site", tags=["site"])
_store = {}


def get_store():
    if "s" not in _store:
        from engine import api  # late: api owns the data dir and secret

        key = hmac.new(api._secret(), b"planbound-site-chain-v1", hashlib.sha256).digest()
        _store["s"] = SiteStore(Path(api.pipeline.data) / "site.sqlite", key)
    return _store["s"]


def _body(b):
    if not isinstance(b, dict):
        raise SiteError("Send a JSON object.")
    return b


@router.post("/sessions", status_code=201)
def create_session():
    sid, st = get_store().create()
    return view(sid, st)


@router.get("/sessions/{sid}")
def get_session(sid: str):
    _, st = get_store().mutate(sid, lambda st: None)
    return view(sid, st)


@router.put("/sessions/{sid}/contract")
def put_contract(sid: str, body: dict = Body(...)):
    """Draft a boundary: unconfirmed until /confirm. Validation is the same as the confirm step."""
    draft = validate_contract(_body(body).get("contract"))

    def fn(st):
        st["contract"], st["appliedScope"] = draft, None

    return view(sid, get_store().mutate(sid, fn)[1])


@router.post("/sessions/{sid}/confirm")
def confirm(sid: str, body: dict = Body(...)):
    body = _body(body)
    draft = validate_contract(body.get("contract"))
    if body.get("consent") is not True:
        raise SiteError("Confirm the consent checkbox before submitting.")
    store = get_store()

    def fn(st):
        c = {**draft, "confirmed": True, "confirmedAt": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())}
        c["hash"] = contract_hash(c)
        st["contract"], st["appliedScope"] = c, None
        store._evaluated(st)

    return view(sid, store.mutate(sid, fn)[1])


@router.post("/sessions/{sid}/plan")
def load_plan(sid: str, body: dict = Body(...)):
    body = _body(body)
    pid = body.get("id")
    if not isinstance(pid, str) or not 1 <= len(pid) <= 40:
        raise SiteError("A plan id is required.")
    changes = validate_plan(body["changes"] if "changes" in body and body["changes"] is not None else PLANS.get(pid))
    store = get_store()

    def fn(st):
        st["planId"], st["changes"], st["appliedScope"] = pid, changes, None
        store._evaluated(st)

    return view(sid, store.mutate(sid, fn)[1])


@router.post("/sessions/{sid}/resolve")
def resolve(sid: str, body: dict = Body(...)):
    body = _body(body)
    cid, choice, undo = body.get("change_id"), body.get("choice"), body.get("undo") is True
    store = get_store()

    def fn(st):
        verdicts, _ = derive(st)
        if not isinstance(cid, str) or verdicts.get(cid, {}).get("verdict") != "REVIEW":
            return False
        key = scope_of(st) + ":" + cid
        if undo:
            if key not in st["resolutions"]:
                return False
            del st["resolutions"][key]
            event = "unresolved"
        else:
            if choice not in ("approved", "rejected"):
                return False
            st["resolutions"][key] = choice
            event = "resolved"
            st["metrics"]["humanDecisions"] += 1
        st["appliedScope"] = None
        chg = next(c for c in st["changes"] if c["id"] == cid)
        store.chain.append(st, make_record(st, chg, verdicts[cid], event))
        return True

    ok, st = store.mutate(sid, fn)
    return {"ok": ok, "state": view(sid, st)}


@router.post("/sessions/{sid}/apply")
def apply(sid: str):
    """SIMULATED: records an apply event in the evidence chain. Nothing is executed anywhere."""
    store = get_store()

    def fn(st):
        _, gate = derive(st)
        if not gate or st["appliedScope"] == scope_of(st):
            return False
        verdicts, _ = derive(st)
        selected = [c for c in st["changes"] if resolution(st, c["id"]) != "rejected"]
        if selected:
            for c in selected:
                store.chain.append(st, make_record(st, c, verdicts[c["id"]], "applied"))
        else:
            empty = _chg("empty-apply-set", "apply_set", "empty", None, None, "none")
            rec = make_record(st, empty, _v("ALLOW", "apply.empty_set", "No resources applied. All proposed changes were explicitly rejected."), "applied")
            rec["included"], rec["excluded"] = [], [c["id"] for c in st["changes"]]
            store.chain.append(st, rec)
        st["appliedScope"] = scope_of(st)
        return True

    ok, st = store.mutate(sid, fn)
    return {"ok": ok, "state": view(sid, st)}


@router.get("/sessions/{sid}/evidence/verify")
def verify(sid: str):
    store = get_store()
    _, st = store.mutate(sid, lambda st: None)
    return store.chain.verify(st)


# ------------------------------------------------ real pipeline bridge (opt-in)
# Lets the site drive the REAL task pipeline (Terraform plan + Cedar policies + the HMAC audit chain) with
# no bearer token. Because that runs Terraform, it is OFF unless it is safe: local machine with Terraform
# installed, requests from loopback only. PLANBOUND_PIPELINE=1 forces on, =0 forces off.
import os
import shutil

from fastapi import Depends, Request

pipe = APIRouter(prefix="/api/site/pipeline", tags=["pipeline"])
ACTOR = "planbound-site"
VARIANTS = {"intended": "Agent stays in scope", "poisoned": "Agent overreaches (network + public access)"}


def pipeline_enabled():
    flag = os.environ.get("PLANBOUND_PIPELINE")
    if flag in ("0", "1"):
        return flag == "1"
    return shutil.which("terraform") is not None and not (os.environ.get("PLANREVIEW_PUBLIC_HOST") or os.environ.get("RENDER_EXTERNAL_HOSTNAME"))


def guard(request: Request):
    if not pipeline_enabled():
        raise SiteError("The real pipeline is not enabled on this server (needs Terraform on a local machine).", "PIPELINE_DISABLED", 404)
    host = request.client.host if request.client else ""
    if host not in ("127.0.0.1", "::1", "testclient") and os.environ.get("PLANBOUND_PIPELINE") != "1":
        raise SiteError("The real pipeline only accepts local requests.", "PIPELINE_LOCAL_ONLY", 403)


def _api():
    from engine import api

    return api


@pipe.get("/status")
def pipe_status():
    return {"enabled": pipeline_enabled(), "terraform": shutil.which("terraform") is not None, "variants": VARIANTS, "evaluator": "cedar", "agent": "offline fixture replay"}


@pipe.post("/tasks", dependencies=[Depends(guard)])
def pipe_create(body: dict = Body(...)):
    api = _api()
    task = _body(body).get("task")
    if not isinstance(task, str) or not 1 <= len(task) <= 1000:
        raise SiteError("Describe the task in 1–1000 characters.")
    return api.task_view(api.call(api.pipeline.create, task, "replay", lock=False))


@pipe.get("/tasks/{tid}", dependencies=[Depends(guard)])
def pipe_get(tid: str):
    api = _api()
    return api.task_view(api.call(api.pipeline.store.get, tid, lock=False))


@pipe.post("/tasks/{tid}/confirm", dependencies=[Depends(guard)])
def pipe_confirm(tid: str):
    api = _api()
    t = api.call(api.pipeline.store.get, tid, lock=False)
    return api.task_view(api.call(api.pipeline.confirm, tid, t["contract"]))


@pipe.post("/tasks/{tid}/jobs", status_code=202, dependencies=[Depends(guard)])
def pipe_job(tid: str, body: dict = Body(...)):
    api = _api()
    body = _body(body)
    op, variant = body.get("op"), body.get("variant")
    if op not in ("agent", "plan", "apply"):
        raise SiteError("op must be agent, plan or apply.")
    if op == "agent" and variant not in VARIANTS:
        raise SiteError("Unknown agent variant.")
    args = {"variant": variant} if op == "agent" else {}
    return api.job_view(api.call(api._runner().submit, tid, op, args, ACTOR, lock=False))


@pipe.get("/jobs/{jid}", dependencies=[Depends(guard)])
def pipe_job_get(jid: str):
    api = _api()
    j = api.pipeline.store.job_get(jid)
    if j is None:
        raise SiteError("Job not found", "JOB_NOT_FOUND", 404)
    return api.job_view(j)


@pipe.post("/tasks/{tid}/step/{step}", dependencies=[Depends(guard)])
def pipe_step(tid: str, step: str):
    api = _api()
    if step not in ("canonicalize", "evaluate"):
        raise SiteError("Unknown step.")
    return api.task_view(api.call(getattr(api.pipeline, step), tid))


@pipe.post("/tasks/{tid}/resolve", dependencies=[Depends(guard)])
def pipe_resolve(tid: str, body: dict = Body(...)):
    api = _api()
    res = _body(body).get("resolutions")
    if not isinstance(res, dict) or not all(isinstance(k, str) and v in ("approve", "reject") for k, v in res.items()):
        raise SiteError("resolutions must map an address to approve or reject.")
    return api.task_view(api.call(api.pipeline.resolve, tid, res, ACTOR))


@pipe.get("/tasks/{tid}/audit", dependencies=[Depends(guard)])
def pipe_audit(tid: str):
    api = _api()
    api.call(api.pipeline.store.get, tid, lock=False)
    return api.audit_view(api.pipeline.store.audit(tid, 200, 0))


@pipe.get("/audit/verify", dependencies=[Depends(guard)])
def pipe_verify():
    return _api().pipeline.store.verify_audit()
