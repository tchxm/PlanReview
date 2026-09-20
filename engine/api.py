import logging
import os
import subprocess
import uuid

import hashlib
import json
import re

from fastapi import Depends, FastAPI, Header, Request
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
    TerraformError,
)
from engine.pipeline import LOCKS, Pipeline
from engine.sanitize import scrub
from engine.views import audit_view, task_view

log = logging.getLogger("planreview")

API_VERSION = "2"
app = FastAPI(title="PlanReview", version="0.2.0")
app.add_middleware(
    TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
)
pipeline = Pipeline()

ALLOWED_ORIGINS = {
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
}
INSECURE = os.environ.get("PLANREVIEW_INSECURE_NO_AUTH") == "1"
if INSECURE:
    log.warning("PLANREVIEW_INSECURE_NO_AUTH=1: API authentication is DISABLED. Local development only.")
_secret_cache = {}


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
            return {"scopes": {"read", "write", "evidence"}, "exp": None}
        token = authlib.parse_bearer(request.headers.get("authorization"))
        scopes, exp = authlib.verify(_secret(), token)
        if scope not in scopes:
            raise authlib.AuthError("AUTH_SCOPE", f"This credential lacks the '{scope}' scope", status=403)
        request.state.principal = {"scopes": scopes, "exp": exp}
        return request.state.principal

    return dep


class TaskInput(BaseModel):
    task: str = Field(min_length=1, max_length=4000)
    mode: str = "replay"


READ, WRITE, EVIDENCE = Depends(require("read")), Depends(require("write")), Depends(require("evidence"))


@app.get("/api/health")
def health():
    """Public: no task data. Reports the auth posture so clients can tell."""
    return {"status": "ok", "evaluator": "cedar", "cloud_apply": False, "auth": "disabled" if INSECURE else "required", "api_version": API_VERSION}


@app.get("/api/auth/whoami")
def whoami(request: Request, principal=READ):
    return {"scopes": sorted(principal["scopes"]), "expires_at": principal["exp"]}


@app.get("/api/tasks")
def tasks(principal=READ):
    return [task_view(t) for t in pipeline.store.list()]


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


@app.get("/api/tasks/{id}")
def get(id: str, principal=READ):
    return task_view(call(pipeline.store.get, id, lock=False))


@app.get("/api/tasks/{id}/intent")
def intent(id: str, principal=READ):
    return call(pipeline.store.get, id, lock=False).get("intent")


@app.post("/api/tasks/{id}/confirm")
def confirm(id: str, body: dict | None = None, principal=WRITE):
    return task_view(call(pipeline.confirm, id, body))


@app.post("/api/tasks/{id}/agent")
def agent(id: str, variant: str = "poisoned", principal=WRITE):
    return task_view(call(pipeline.agent, id, variant))


@app.post("/api/tasks/{id}/plan")
def plan(id: str, principal=WRITE):
    return task_view(call(pipeline.plan, id))


@app.post("/api/tasks/{id}/canonicalize")
def canonical(id: str, principal=WRITE):
    return task_view(call(pipeline.canonicalize, id))


@app.post("/api/tasks/{id}/evaluate")
def evaluate(id: str, principal=WRITE):
    return task_view(call(pipeline.evaluate, id))


@app.post("/api/tasks/{id}/resolve")
def resolve(id: str, body: dict[str, str], principal=WRITE):
    return task_view(call(pipeline.resolve, id, body))


@app.post("/api/tasks/{id}/apply")
def apply(id: str, principal=WRITE):
    return task_view(call(pipeline.apply, id))


@app.get("/api/tasks/{id}/audit")
def audit(id: str, principal=READ):
    call(pipeline.store.get, id, lock=False)  # 404 for an unknown task
    return audit_view(pipeline.store.audit(id))


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
