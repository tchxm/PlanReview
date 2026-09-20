# PlanReview backend API contract

> ## API version 2 (backend hardening) supersedes parts of the text below
> Responses carry `X-PlanReview-API: 2`, `X-Request-ID` and `Cache-Control: no-store`.
>
> **Authentication.** Every route except `GET /api/health` requires `Authorization: Bearer <token>`. Tokens are signed, expiring and scoped (`read`, `write`, `evidence`). Mint one with `python -m engine.auth mint --scopes read,write --ttl 8h`. Errors: `401 AUTH_REQUIRED | AUTH_INVALID | AUTH_EXPIRED`, `403 AUTH_SCOPE`. `PLANREVIEW_INSECURE_NO_AUTH=1` disables authentication for local development only (logged loudly; `/api/health` reports `auth: "disabled"`).
>
> **One error envelope.** `{"detail": {"error": CODE, "message", "details", "request_id"}}` for every error, including 404 routes and 500s. Statuses: `404 TASK_NOT_FOUND | EVIDENCE_NOT_FOUND | ROUTE_NOT_FOUND`; `422 INVALID_REQUEST | INVALID_CONTRACT | UNKNOWN_MODE | UNKNOWN_FIXTURE | CONTRACT_ID_MISMATCH | TASK_REQUIRED | AGENT_EDIT_REJECTED`; `409 CONTRACT_NOT_ACTIVE | CONTRACT_IMMUTABLE | CONTRACT_EXPIRED | STAGE_OUT_OF_ORDER | NO_SAVED_PLAN | EDIT_ALREADY_PREPARED | RUN_ALREADY_APPLIED | UNPLANNED_EDITS | POLICY_CHANGED | RESOLUTION_NOT_ALLOWED | EVALUATION_ERROR_NOT_APPROVABLE | PREPLAN_GUARD_REJECTED | CONTRACT_INTEGRITY_FAILED | PLAN_INTEGRITY_FAILED`; `400 UNSUPPORTED_OPERATION | AMBIGUOUS_REQUEST`; `403 ORIGIN_BLOCKED`; `502 TERRAFORM_FAILED | MODEL_RESPONSE_INVALID`; `503 MODEL_UNAVAILABLE | DEPENDENCY_UNAVAILABLE | FIXTURES_UNAVAILABLE | TERRAFORM_UNAVAILABLE`; `504 TERRAFORM_TIMEOUT`; `500 INTERNAL_ERROR`. Messages are scrubbed of absolute paths and credentials; raw diagnostics are only in the server log, keyed by `request_id`. Unknown failures are never reported as client errors.
>
> **Data exposure.** Task and audit responses no longer contain `workspace`, `plan_path`, `raw_path`, `plan_stdout`, `raw_plan` or the edited Terraform text. Runs carry hashes, canonical changes, verdicts, resolutions, `apply_result`, `plan_summary` and `raw_evidence_available`. Audit events are summarised (`agent_edits` keeps only `terraform_sha256`). Raw records: `GET /api/tasks/{id}/evidence/{event_id}` (scope `evidence`, access is logged without content).
>
> **New routes.** `GET /api/auth/whoami` (read), `GET /api/tasks/{id}/evidence/{event_id}` (evidence), `GET /api/audit/verify` (evidence; see `docs/audit-integrity.md`). New optional field `intent.mapped_from` when a model's informal resource name was mapped by the deterministic allowlist.
>
> **Coordination.** Mutations are serialized per task; reads never wait for a mutation; different tasks run in parallel. Run a **single Uvicorn worker**: locks are in-process.
>
> **Configuration.** `PLANREVIEW_OLLAMA_HOST` (loopback only unless `PLANREVIEW_OLLAMA_ALLOW_REMOTE=1`), `PLANREVIEW_OLLAMA_MODEL`, `PLANREVIEW_OLLAMA_TIMEOUT`, `PLANREVIEW_OLLAMA_CHAT_TIMEOUT`, `PLANREVIEW_DATA_DIR`, `PLANREVIEW_API_SECRET`.
>
> **Not yet in v2:** durable jobs, progress and cancellation of long operations, idempotency keys. Long stages are still single blocking requests, and a browser timeout is not a cancellation.

---


Documents the API **as implemented** in `engine/api.py` and `engine/pipeline.py` on the Phase 1 code. Shapes were observed against a running backend. Nothing here is aspirational; gaps are listed in the last section. The machine-generated schema is at `/openapi.json` and `/docs`, but most responses are untyped dicts, so this document is the reference for response bodies.

The backend serves **only** the API. It does not host the frontend. It binds to `127.0.0.1:8000` by default.

## Conventions

- Base path `/api`. Bodies are JSON. Real AWS apply is disabled (`/api/health` → `cloud_apply: false`).
- **Local protections:** `TrustedHostMiddleware` accepts `Host` of `localhost`, `127.0.0.1` (any port), `testserver`. A non-`GET/HEAD/OPTIONS` request that carries an `Origin` header must be one of `http://localhost:8000`, `http://127.0.0.1:8000`, `http://localhost:5173`, `http://127.0.0.1:5173`, otherwise `403 {"detail":"Cross-origin mutation blocked"}`. There is no CORS middleware and no authentication. Origin checking is a local CSRF guard, not authorization. The Vite proxy forwards the browser's `Origin: http://127.0.0.1:5173` (or `localhost`), which is allowed.
- All task mutations run under one process-wide lock (`LOCK`); requests are serialized.
- Unknown routes return FastAPI's JSON `404 {"detail":"Not Found"}`, never HTML.

### Error shapes (three, all under `detail`)

| Shape | Source | Example |
|---|---|---|
| Structured | `PlanReviewError` subclasses | `{"detail":{"error":"UNSUPPORTED_OPERATION","message":"…","details":{…}}}` |
| Legacy string | `ValueError` → 409, `OSError/TimeoutError` → 503, origin block → 403, unknown route → 404 | `{"detail":"Pipeline incomplete: evaluate first"}` |
| Pydantic | request validation → 422 | `{"detail":[{"type":"string_too_short","loc":["body","task"],"msg":"…"}]}` |

Structured codes and HTTP status: `UNSUPPORTED_OPERATION` 400, `AMBIGUOUS_REQUEST` 400, `MODEL_UNAVAILABLE` 503 (Ollama unreachable or model not installed in `ollama`/`live` mode; the backend does **not** fall back to replay). Other `PlanReviewError`s default to `GENERIC_ERROR` 400.

Notable legacy errors (all HTTP 409 unless noted): `Task not found` (**409, not 404**), `Contract is immutable after confirmation`, `Active confirmed contract required`, `Contract expired`, `Pipeline incomplete: …` (wrong stage), `Plan the prepared edit before editing again`, `Run already applied`, `Unplanned edits exist; create and evaluate a new plan`, `Policies changed; evaluate again…`, `Address X experienced an evaluation error and cannot be approved…`, `Only REVIEW items accept approve/reject resolutions…`. `Pipeline incomplete: run fixture generator first` is also 409 (fixtures missing). A `503 Pipeline incomplete: …` comes from OS/timeouts (e.g. Terraform missing).

The frontend client (`web/src/api.js`) maps these to `{code, message, details, status}`; see the client rules below.

### Stages

`task.stage`: `draft` → `confirmed` → `edited` → `planned` → `canonicalized` → `evaluated` → `resolved` → (`blocked` | `applied` | `failed`, from the apply result status lowercased). Re-editing/re-planning starts a new **run** in `task.runs`; only `runs[-1]` (the latest) is authoritative. Resolutions are cleared by a new plan or re-evaluation.

## Endpoints

"Long" = may take seconds to minutes (Terraform, Ollama).

### `GET /api/health`
`200 {"status":"ok","evaluator":"cedar","cloud_apply":false}`. Read-only, safe to retry.

### `GET /api/tasks`
`200 [Task, …]` (full task objects, including all runs; newest first). Read-only. No pagination.

### `POST /api/tasks` — mutates, **long in `ollama`/`live` mode**
Body `{"task": string(1..4000), "mode": "replay"|"adversarial"|"ollama"|"live"}` (mode default `replay`). Interprets the request (AI-assisted in ollama/live), validates against the capability registry, drafts a contract.
Success `200 Task` with `stage:"draft"`, `contract.status:"draft"`, `intent` (`operation`, `resource_address`, `resource_type`, `attribute`, `requested_value`, `raw_task`, `status:"VALIDATED"`, `reason`).
Errors: 400 `UNSUPPORTED_OPERATION`, 400 `AMBIGUOUS_REQUEST`, 503 `MODEL_UNAVAILABLE`, 409 `Unknown mode`, 422 empty/oversized `task`.
Retry: **not idempotent** — every success creates a new task. Do not retry automatically.

### `GET /api/tasks/{id}` / `GET /api/tasks/{id}/intent`
`200 Task` / `200 Task.intent` (may be `null`). `409 Task not found`. Read-only.

### `POST /api/tasks/{id}/confirm` — mutates
Body: the contract object (optional; defaults to the stored draft). The contract id must not change. Seals the contract with a hash (`confirmed_contract_hash`) and sets `contract.status:"confirmed"`, `stage:"confirmed"`.
Errors: 409 `Contract is immutable after confirmation`, `Contract ID cannot change`, integrity mismatch, and an invalid contract body (raw pydantic text in a legacy 409 string, since `pydantic.ValidationError` is a `ValueError`; the body is `dict`, so FastAPI does not return 422). Retry: a second call fails (immutable).

### `POST /api/tasks/{id}/agent?variant=…` — mutates, **long**
Query `variant` ∈ `baseline|intended|review|poisoned|adversarial` (default `poisoned`; replay-mode fixture selector, ignored in `ollama`/`live` mode which edits the baseline with the Strands agent). Requires an active confirmed contract. Prepares `main.tf` in the task workspace. `stage:"edited"`, `prepared:true`.
Errors: 409 `Active confirmed contract required`, `Unknown fixture`, `Plan the prepared edit before editing again`, `Pipeline incomplete: run fixture generator first`; 503 `MODEL_UNAVAILABLE` (live). Retry: not while `prepared` is true.
Note: in replay mode the fixture variant, not the natural-language task, determines the edit.

### `POST /api/tasks/{id}/plan` — mutates, **long**
Runs a real `terraform plan -refresh=false -out=…` (dummy credentials, no AWS calls), enforces the pre-plan guard, saves the plan and hashes. Appends a run to `runs` (`plan_path`, `plan_hash`, `raw_path`, `raw_hash`, `plan_stdout`). `stage:"planned"`. Requires stage `edited`.
Errors: 409 `Pipeline incomplete: run edits first`, `Contract expired`, guard rejections and Terraform stderr (text of the failure), 503 on OS/timeout.
Retry: creates another run; do not retry blindly.

### `POST /api/tasks/{id}/canonicalize` — mutates
Converts the saved raw plan into `run.canonical[]`: `{address, resource_type, action, environment, region, changes:[{attribute,before,after}], dependencies, unknown}`. `stage:"canonicalized"`. Errors: 409 `Raw plan hash mismatch`. Idempotent for the same run.

### `POST /api/tasks/{id}/evaluate` — mutates
Evaluates each canonical change with Cedar against the confirmed contract. Sets `run.verdicts[]` (`{address, verdict, changes, reason, determining_policies}`) and `run.policy_hash`; clears `run.resolutions`. `stage:"evaluated"`. Errors: 409 `Pipeline incomplete: canonicalize first`.

**`verdict` is one of `ALLOW`, `REVIEW`, `DENY`, `EVALUATION_ERROR`.** `EVALUATION_ERROR` is a **technical failure** of Cedar evaluation (`reason` starts `Cedar evaluation failed:`). It is not REVIEW, cannot be approved through `/resolve`, and always blocks `/apply`. The client must present it as a failure, distinct from REVIEW.

### `POST /api/tasks/{id}/resolve` — mutates
Body `{ "<address>": "approve" | "reject", … }`. Only addresses whose verdict is `REVIEW` accept decisions; `DENY` and `EVALUATION_ERROR` addresses are rejected with 409. Stored on `run.resolutions` and bound to that run's plan/policy hash. `stage:"resolved"`.
Errors: 409 `Only REVIEW items accept approve/reject…`, `…experienced an evaluation error and cannot be approved…`, `Pipeline incomplete: evaluate first`. Retry: idempotent for identical decisions on the same run.
Gap: the backend does not return who resolved.

### `POST /api/tasks/{id}/apply` — mutates
The **server-side gate**. Verifies contract validity, no unplanned edits, policy hash, plan hash, verdicts, resolutions. Result in `run.apply_result` `{status, reason, spawned}` and `stage`:
- `BLOCKED` — gate reason text (unresolved REVIEW/DENY, evaluation error, expired contract, hash mismatch, or `AWS apply disabled: configure and verify an isolated emulator first`).
- `APPLIED` / `FAILED` — only reachable for a genuine local-resource Terraform apply in tests; real AWS apply is disabled.
Returns the full Task (`200`) even when blocked; a block is data, not an HTTP error. Errors: 409 `Run already applied`, `Unplanned edits exist…`, `Policies changed…`, `Pipeline incomplete: evaluate first`. May be long when it spawns Terraform. Not idempotent after `APPLIED`.
The frontend must display `apply_result`; it must not compute its own gate.

### `GET /api/tasks/{id}/audit`
`200 [{id, timestamp, kind, data}, …]` — persistent SQLite audit, in stored order. Kinds seen: `draft`, `human_confirmation`, `apply_result`, and others for each stage. Read-only.

## Supported Phase 1 operations (boundaries)

Only two infrastructure edits are supported:

| Operation | Resource | Attribute | Constraint |
|---|---|---|---|
| `update_memory` | `aws_lambda_function.dev_api` | `memory_size` | integer 128–10240 MB (1 MB increments) |
| `update_tags` | `aws_s3_bucket.assets` | `tags.Team` | non-security `Team` tag only |

Anything else (RDS, IAM, security groups, networking, deletes, compound requests) returns `UNSUPPORTED_OPERATION` or `AMBIGUOUS_REQUEST`. Replay-mode fixtures (`poisoned`, `review`, …) exist to demonstrate ALLOW/REVIEW/DENY on real Terraform plans and are not new capabilities.

## Recommended real workflow

1. `POST /tasks` → inspect `intent` and `contract` (draft).
2. `POST /tasks/{id}/confirm` with the (possibly edited) contract.
3. `POST /tasks/{id}/agent` → `POST …/plan` → `POST …/canonicalize` → `POST …/evaluate`. Stop at the first failure; do not skip stages.
4. Inspect `runs[-1].verdicts`. `EVALUATION_ERROR` → stop; repair and re-plan.
5. `POST …/resolve` for `REVIEW` items.
6. `POST …/apply` → read `apply_result`.
7. `GET …/audit`.

## Frontend client rules (`web/src/api.js`)

- Every failure throws `ApiError {code, message, details, status}`. Backend codes pass through; client codes: `NETWORK_ERROR`, `BACKEND_UNAVAILABLE` (empty-body 500/502/503/504 from the Vite proxy), `TIMEOUT`, `ABORTED`, `INVALID_RESPONSE` (non-JSON 2xx), `VALIDATION_ERROR`, `INVALID_STATE` (409), `FORBIDDEN`, `NOT_FOUND`, `PIPELINE_INCOMPLETE` (legacy 503), `HTTP_ERROR`.
- No automatic retries. Timeouts/aborts on mutating calls state that the backend may still be running the operation; the client never claims Terraform or the agent was cancelled.
- Timeouts: 30 s default; 15 min for create/agent/plan.

## Gaps for the Phase 3 UI (documented, not implemented)

- `Task not found` is 409, and mutation-error codes are mostly free-text legacy strings; no stable code for stage errors.
- Task responses expose absolute filesystem paths (`workspace`, `plan_path`, `raw_path`) and full `plan_stdout`; no summary/diff-only endpoint.
- `GET /tasks` returns full objects with no pagination or summary view.
- No per-stage progress or cancellation endpoint; long operations are a single blocking request.
- No endpoint to read Cedar policy text or per-policy explanations beyond `determining_policies` ids and `reason`.
- No resolver identity on `resolutions`; no evidence export endpoint (audit list only).
- No endpoint listing supported operations (the capability registry is only visible through errors).

## Observed examples

Unsupported request (`POST /api/tasks`, HTTP 400):

```json
{"detail":{"error":"UNSUPPORTED_OPERATION","message":"The requested operation or service is outside genuinely supported capabilities. Matched unsupported pattern: \brds\b. Genuine supported operations: update_memory, update_tags.","details":{"task":"Delete the production RDS database and open port 22 to the world","pattern":"\brds\b"}}}
```

Live-model proposal rejected by the deterministic validator (`mode:"ollama"`, HTTP 400). The model returned a free-text resource name; the capability registry accepts only the canonical address:

```json
{"detail":{"error":"UNSUPPORTED_OPERATION","message":"Resource 'dev-api-Lambda' is not supported for operation 'update_memory'. Permitted resource: 'aws_lambda_function.dev_api'.","details":{"proposal":{"operation":"update_memory","resource_address":"dev-api-Lambda","attribute":"memory_size","requested_value":512}}}}
```

Empty task (HTTP 422): `{"detail":[{"type":"string_too_short","loc":["body","task"],"msg":"String should have at least 1 character"}]}`

Apply blocked by the gate (HTTP 200; `run.apply_result`): `{"status":"BLOCKED","reason":"2 unresolved DENY; edit configuration and create a new plan","spawned":false}`

Model unavailable and evaluation-error bodies follow the structured/`verdict:"EVALUATION_ERROR"` shapes above; they are exercised by mocked tests in `tests/test_phase1.py`, not captured from a live run.
