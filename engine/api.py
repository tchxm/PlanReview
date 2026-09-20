import logging
import os
import subprocess
import uuid

import hashlib
import json
import re

from fastapi import Depends, FastAPI, Header, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from engine import auth as authlib
from engine.exceptions import (
    DependencyError,
    InvalidRequestError,
    NotFoundError,
    PlanReviewError,
    StateConflictError,
    TerraformError,
)
from engine.gate import emulator_endpoint as gate_emulator
from engine.jobs import JobRunner
from engine import ratelimit
from engine.pipeline import LOCKS, Pipeline
from engine.sanitize import scrub
from engine.views import audit_view, task_view

log = logging.getLogger("planreview")

API_VERSION = "2"
app = FastAPI(title="PlanReview", version="0.2.0")
# A hosted deployment names its public host (Render sets RENDER_EXTERNAL_HOSTNAME itself).
PUBLIC_HOST = os.environ.get("PLANREVIEW_PUBLIC_HOST") or os.environ.get("RENDER_EXTERNAL_HOSTNAME") or ""
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"] + ([PUBLIC_HOST] if PUBLIC_HOST else [])
)
pipeline = Pipeline()

ALLOWED_ORIGINS = {
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
if PUBLIC_HOST:
    ALLOWED_ORIGINS.add("https://" + PUBLIC_HOST)
INSECURE = os.environ.get("PLANREVIEW_INSECURE_NO_AUTH") == "1"
if INSECURE:
    log.warning("PLANREVIEW_INSECURE_NO_AUTH=1: API authentication is DISABLED. Local development only.")
_secret_cache = {}
MAX_BODY = int(os.environ.get("PLANREVIEW_MAX_BODY_BYTES", 1_000_000))
LIMITERS = ratelimit.from_env()
MAX_PAGE = 500


def _secret():
    if "v" not in _secret_cache:
        _secret_cache["v"] = authlib.load_secret(pipeline.data)
    return _secret_cache["v"]


# --------------------------------------------------------------- errors
def error_response(status, code, message, details=None, request_id=None, headers=None):
    """One error envelope everywhere: {"detail": {error, message, details, request_id}}."""
    body = {"detail": {"error": code, "message": scrub(message), "details": details or {}, "request_id": request_id}}
    h = {"X-PlanReview-API": API_VERSION, "Cache-Control": "no-store", **(headers or {})}
    if request_id:
        h["X-Request-ID"] = request_id
    return JSONResponse(body, status_code=status, headers=h)


def rid(request: Request):
    return getattr(request.state, "request_id", None)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request.state.request_id = uuid.uuid4().hex[:12]
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"} and origin and origin not in ALLOWED_ORIGINS:
        return error_response(403, "ORIGIN_BLOCKED", "Cross-origin mutation blocked", request_id=rid(request))
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        declared = request.headers.get("content-length")
        too_big = declared is not None and declared.isdigit() and int(declared) > MAX_BODY
        if not too_big and declared is None:  # chunked upload: measure what actually arrives
            too_big = len(await request.body()) > MAX_BODY
        if too_big:
            return error_response(413, "REQUEST_TOO_LARGE", f"Request body exceeds {MAX_BODY} bytes", request_id=rid(request))
    if request.url.path != "/api/health":
        ok, wait = LIMITERS["ip"].allow(request.client.host if request.client else "unknown")
        if not ok:
            return error_response(429, "RATE_LIMITED", "Too many requests from this address", request_id=rid(request), headers={"Retry-After": str(wait)})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["X-PlanReview-API"] = API_VERSION
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(PlanReviewError)
async def on_domain_error(request: Request, exc: PlanReviewError):
    if exc.status_code >= 500:
        log.error("[%s] %s %s -> %s %s", rid(request), request.method, request.url.path, exc.code, exc.message)
    return error_response(exc.status_code, exc.code, exc.message, exc.details, rid(request))


@app.exception_handler(authlib.AuthError)
async def on_auth_error(request: Request, exc: authlib.AuthError):
    headers = {"WWW-Authenticate": "Bearer"} if exc.status == 401 else None
    if exc.retry_after:
        headers = {"Retry-After": str(exc.retry_after)}
    return error_response(exc.status, exc.code, exc.message, request_id=rid(request), headers=headers)


@app.exception_handler(RequestValidationError)
async def on_validation(request: Request, exc: RequestValidationError):
    errors = [{"field": ".".join(str(p) for p in e.get("loc", []) if p != "body"), "problem": scrub(e.get("msg", ""))} for e in exc.errors()]
    return error_response(422, "INVALID_REQUEST", "The request is invalid", {"errors": errors}, rid(request))


@app.exception_handler(StarletteHTTPException)
async def on_http(request: Request, exc: StarletteHTTPException):
    code = {404: "ROUTE_NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(exc.status_code, "HTTP_ERROR")
    return error_response(exc.status_code, code, str(exc.detail), request_id=rid(request))


@app.exception_handler(Exception)
async def on_unexpected(request: Request, exc: Exception):
    log.exception("[%s] unhandled error on %s %s", rid(request), request.method, request.url.path)
    return error_response(500, "INTERNAL_ERROR", "An internal error occurred; see the server log with this request id", request_id=rid(request))


def call(fn, *args, lock=True):
    """Run a pipeline operation; mutations hold the per-task lock, reads do not.
    Translates low-level failures into stable API errors."""
    try:
        if lock and args:
            active = pipeline.store.job_active(args[0])
            if active:
                raise StateConflictError(
                    "A background job is running for this task; wait for it or cancel it", code="JOB_IN_PROGRESS", details={"job_id": active["id"]}
                )
            with LOCKS.get(args[0]):
                return fn(*args)
        return fn(*args)
    except PlanReviewError:
        raise
    except ValidationError as exc:
        errors = [{"field": ".".join(str(p) for p in e.get("loc", [])), "problem": scrub(e.get("msg", ""))} for e in exc.errors()]
        raise InvalidRequestError("Invalid contract or request data", code="INVALID_CONTRACT", details={"errors": errors})
    except subprocess.TimeoutExpired:
        raise TerraformError("Terraform timed out", code="TERRAFORM_TIMEOUT", status_code=504)
    except (OSError, TimeoutError) as exc:
        log.error("dependency failure: %s", exc)
        raise DependencyError("A local dependency is unavailable; see the server log")
    # Anything else (including an untyped ValueError) propagates to the 500 handler:
    # unknown failures are never reported as a client error.


# ------------------------------------------------------------------ auth
def require(scope):
    def dep(request: Request):
        if INSECURE:
            return {"sub": "insecure-local", "scopes": {"read", "write", "evidence"}, "exp": None, "jti": None}
        token = authlib.parse_bearer(request.headers.get("authorization"))
        principal = authlib.verify(_secret(), token)
        if pipeline.store.is_revoked(principal["jti"]):
            raise authlib.AuthError("AUTH_REVOKED", "Credential has been revoked")
        scopes = principal["scopes"]
        if scope not in scopes:
            raise authlib.AuthError("AUTH_SCOPE", f"This credential lacks the '{scope}' scope", status=403)
        request.state.principal = principal
        ok, wait = LIMITERS["read" if request.method in {"GET", "HEAD"} else "write"].allow(principal["sub"] + ":" + request.method[:1])
        if not ok:
            raise authlib.AuthError("RATE_LIMITED", "Too many requests for this credential", status=429, retry_after=wait)
        return request.state.principal

    return dep


class TaskInput(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    mode: str = "replay"


READ, WRITE, EVIDENCE = Depends(require("read")), Depends(require("write")), Depends(require("evidence"))


@app.get("/api/health")
def health():
    """Public: no task data. Reports the auth posture so clients can tell."""
    return {"status": "ok", "evaluator": "cedar", "cloud_apply": False, "emulator_apply": gate_emulator() is not None and gate_emulator() is not False, "auth": "disabled" if INSECURE else "required", "api_version": API_VERSION}


@app.get("/api/auth/whoami")
def whoami(request: Request, principal=READ):
    return {"sub": principal["sub"], "scopes": sorted(principal["scopes"]), "expires_at": principal["exp"]}


@app.post("/api/auth/revoke")
def revoke_self(principal=READ):
    """Revoke the presented credential (logout / suspected leak). Effective immediately."""
    if principal["jti"]:
        pipeline.store.revoke(principal["jti"], principal["sub"])
    return {"revoked": True}


@app.get("/api/capabilities")
def capabilities(principal=READ):
    """The deterministic registry of operations the backend will accept (anything else is UNSUPPORTED_OPERATION)."""
    from engine.intent import CAPABILITY_REGISTRY

    return {op: {k: v for k, v in e.items()} for op, e in CAPABILITY_REGISTRY.items()}


def page(limit: int, offset: int):
    if not 1 <= limit <= MAX_PAGE or offset < 0:
        raise InvalidRequestError(f"limit must be 1..{MAX_PAGE} and offset >= 0", code="INVALID_PAGINATION")
    return limit, offset


@app.get("/api/tasks")
def tasks(response: Response, limit: int = 100, offset: int = 0, principal=READ):
    """Newest first. The body stays a plain list; the total is in the `X-Total-Count` header."""
    limit, offset = page(limit, offset)
    response.headers["X-Total-Count"] = str(pipeline.store.count())
    return [task_view(t) for t in pipeline.store.list(limit, offset)]


_IDEM_KEY = re.compile(r"^[A-Za-z0-9_\-]{8,128}$")


@app.post("/api/tasks")
def create(body: TaskInput, request: Request, principal=WRITE, idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
    """Create a task. With an `Idempotency-Key` header, a network retry of the same request returns
    the ORIGINAL task instead of creating a duplicate; reusing a key with a different body is 422."""
    if idempotency_key is None:
        return task_view(call(pipeline.create, body.task, body.mode, lock=False))
    if not _IDEM_KEY.match(idempotency_key):
        raise InvalidRequestError("Idempotency-Key must be 8-128 characters of A-Z a-z 0-9 _ -", code="INVALID_IDEMPOTENCY_KEY")
    req_hash = hashlib.sha256(json.dumps({"task": body.task, "mode": body.mode}, sort_keys=True).encode()).hexdigest()
    with LOCKS.get("idempotency:" + idempotency_key):
        prior = pipeline.store.idem_get(idempotency_key)
        if prior:
            if prior["req_hash"] != req_hash:
                raise InvalidRequestError("This Idempotency-Key was already used with a different request", code="IDEMPOTENCY_KEY_REUSED")
            resp = JSONResponse(task_view(pipeline.store.get(prior["task_id"])))
            resp.headers["X-Idempotent-Replay"] = "true"
            return resp
        created = call(pipeline.create, body.task, body.mode, lock=False)
        pipeline.store.idem_put(idempotency_key, req_hash, created["id"])
        return task_view(created)


IdemHeader = Header(default=None, alias="Idempotency-Key")


def idempotent(key, scope, payload, task_id, fn):
    """Run `fn` at most once per (scope, Idempotency-Key). A retry with the same key and request returns the
    ORIGINAL response (header `X-Idempotent-Replay: true`); the same key with a different request is 422.
    Failed attempts are not recorded, so a retry after an error really retries."""
    if key is None:
        return fn()
    if not _IDEM_KEY.match(key):
        raise InvalidRequestError("Idempotency-Key must be 8-128 characters of A-Z a-z 0-9 _ -", code="INVALID_IDEMPOTENCY_KEY")
    req_hash = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    full = f"{scope}:{task_id}:{key}"
    with LOCKS.get("idempotency:" + full):
        prior = pipeline.store.idem_get(full)
        if prior:
            if prior["req_hash"] != req_hash:
                raise InvalidRequestError("This Idempotency-Key was already used with a different request", code="IDEMPOTENCY_KEY_REUSED")
            resp = JSONResponse(json.loads(prior["response"]))
            resp.headers["X-Idempotent-Replay"] = "true"
            return resp
        out = fn()
        pipeline.store.idem_put(full, req_hash, task_id, json.dumps(out, default=str))
        return out


@app.get("/api/tasks/{id}")
def get(id: str, principal=READ):
    return task_view(call(pipeline.store.get, id, lock=False))


@app.get("/api/tasks/{id}/intent")
def intent(id: str, principal=READ):
    return call(pipeline.store.get, id, lock=False).get("intent")


@app.post("/api/tasks/{id}/confirm")
def confirm(id: str, body: dict | None = None, principal=WRITE, idempotency_key: str | None = IdemHeader):
    return idempotent(idempotency_key, "confirm", body, id, lambda: task_view(call(pipeline.confirm, id, body)))


@app.post("/api/tasks/{id}/agent")
def agent(id: str, variant: str = "poisoned", principal=WRITE, idempotency_key: str | None = IdemHeader):
    return idempotent(idempotency_key, "agent", {"variant": variant}, id, lambda: task_view(call(pipeline.agent, id, variant)))


@app.post("/api/tasks/{id}/plan")
def plan(id: str, principal=WRITE, idempotency_key: str | None = IdemHeader):
    return idempotent(idempotency_key, "plan", {}, id, lambda: task_view(call(pipeline.plan, id)))


@app.post("/api/tasks/{id}/canonicalize")
def canonical(id: str, principal=WRITE, idempotency_key: str | None = IdemHeader):
    return idempotent(idempotency_key, "canonicalize", {}, id, lambda: task_view(call(pipeline.canonicalize, id)))


@app.post("/api/tasks/{id}/evaluate")
def evaluate(id: str, principal=WRITE, idempotency_key: str | None = IdemHeader):
    return idempotent(idempotency_key, "evaluate", {}, id, lambda: task_view(call(pipeline.evaluate, id)))


@app.post("/api/tasks/{id}/resolve")
def resolve(id: str, body: dict[str, str], principal=WRITE, idempotency_key: str | None = IdemHeader):
    return idempotent(idempotency_key, "resolve", body, id, lambda: task_view(call(pipeline.resolve, id, body, principal["sub"])))


@app.post("/api/tasks/{id}/apply")
def apply(id: str, principal=WRITE, idempotency_key: str | None = IdemHeader):
    return idempotent(idempotency_key, "apply", {}, id, lambda: task_view(call(pipeline.apply, id, principal["sub"])))


class JobInput(BaseModel):
    op: str
    variant: str | None = None


_runner_state = {}


def _runner():
    r = _runner_state.get("r")
    if r is None or r.pipeline is not pipeline:
        if r:
            r.stop()
        r = JobRunner(pipeline)
        r.start()
        _runner_state["r"] = r
    return r


def _start_jobs():
    _runner()


app.router.on_startup.append(_start_jobs)


def job_view(j):
    return {
        "id": j["id"], "task_id": j["task_id"], "op": j["op"], "args": j["args"], "status": j["status"],
        "progress": j["progress"], "requested_by": j["actor"], "created_at": j["created_at"], "started_at": j["started_at"],
        "finished_at": j["finished_at"], "cancel_requested": j["cancel_requested"], "result": j["result"],
        "error": {"code": j["error_code"], "message": j["error_message"]} if j["error_code"] else None,
    }


@app.post("/api/tasks/{id}/jobs", status_code=202)
def submit_job(id: str, body: JobInput, principal=WRITE, idempotency_key: str | None = IdemHeader):
    """Run a long operation (agent | plan | apply) in the background. Returns 202 immediately; poll
    `GET /api/jobs/{job_id}`. One active job per task; survives client disconnects and restarts."""
    args = {"variant": body.variant} if body.op == "agent" and body.variant else {}
    return idempotent(idempotency_key, "job", {"op": body.op, "args": args}, id, lambda: job_view(call(_runner().submit, id, body.op, args, principal["sub"], lock=False)))


@app.get("/api/tasks/{id}/jobs")
def task_jobs(id: str, principal=READ):
    call(pipeline.store.get, id, lock=False)
    return [job_view(j) for j in pipeline.store.jobs_for_task(id)]


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, principal=READ):
    j = pipeline.store.job_get(job_id)
    if j is None:
        raise NotFoundError("Job not found", code="JOB_NOT_FOUND")
    return job_view(j)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, principal=WRITE):
    """Queued jobs cancel at once; a running job's Terraform process tree is killed within ~1 second."""
    return job_view(_runner().cancel(job_id))


@app.get("/api/tasks/{id}/audit")
def audit(id: str, response: Response, limit: int = 200, offset: int = 0, principal=READ):
    call(pipeline.store.get, id, lock=False)  # 404 for an unknown task
    limit, offset = page(limit, offset)
    response.headers["X-Total-Count"] = str(pipeline.store.audit_count(id))
    return audit_view(pipeline.store.audit(id, limit, offset))


@app.get("/api/tasks/{id}/evidence/{event_id}")
def raw_evidence(id: str, event_id: int, request: Request, principal=EVIDENCE):
    """Raw persisted evidence (may contain local paths, Terraform output and edited .tf text).
    Requires the separate `evidence` scope; every access is logged (without content)."""
    call(pipeline.store.get, id, lock=False)
    for e in pipeline.store.audit(id):
        if e["id"] == event_id:
            log.info("[%s] raw evidence read: task=%s event=%s kind=%s", rid(request), id, event_id, e["kind"])
            return e
    raise NotFoundError("Evidence record not found", code="EVIDENCE_NOT_FOUND")


@app.get("/api/audit/verify")
def verify_audit(principal=EVIDENCE):
    """Recompute the audit hash chain and compare it with the local anchor.
    `ok: true` means no tampering was DETECTED by someone without the key; see docs/audit-integrity.md."""
    return pipeline.store.verify_audit()


# ------------------------------------------------- PlanBound site (one origin)
from pathlib import Path as _Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402

from engine import site as site_api  # noqa: E402

app.include_router(site_api.router)
app.include_router(site_api.pipe)
SITE_HTML = _Path(__file__).resolve().parents[1] / "design" / "planbound-site.html"


@app.get("/", include_in_schema=False)
def site_index():
    """Serve the PlanBound site from the same origin as the API (no CORS needed)."""
    if not SITE_HTML.exists():
        raise NotFoundError("Site file not found", code="SITE_NOT_FOUND")
    return FileResponse(SITE_HTML, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-store"})
