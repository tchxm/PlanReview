# Backend hardening: status

Branch `backend-hardening`, from `58e3aaa`. Real AWS apply is still disabled; nothing here contacted AWS. No frontend or `design/` files were changed.

Statuses use exactly: **FIXED AND TESTED**, **IMPLEMENTED BUT NOT FULLY VERIFIED**, **BLOCKED BY ENVIRONMENT**, **NOT IMPLEMENTED**.

| Item | Status | Evidence and limits |
|---|---|---|
| **A. Authentication** | FIXED AND TESTED | Signed, expiring, scoped bearer tokens on every route except `/api/health`; missing, malformed, forged, tampered-scope, expired and wrong-scope credentials tested on every endpoint (`tests/test_auth.py`). Origin and Host checks kept. Secret from env or an ignored file, never committed; tokens never echoed. **Limit:** another process running as the same OS user can read the secret file, the DB and the workspaces. A frontend built before this change must send a token (or use the dev-only opt-out). |
| **B. Structured errors** | FIXED AND TESTED | One envelope with stable codes and statuses 404/422/409/400/502/503/504/500; per-endpoint 404 and per-family contract tests (`tests/test_error_contract.py`); untyped failures become 500, never client errors; raw diagnostics kept in the log with a request id. |
| **C. Data exposure** | FIXED AND TESTED | API responses carry no paths, full Terraform stdout, raw plan JSON or edited `.tf` text (`tests/test_exposure.py`); raw evidence only via the `evidence` scope. **Encrypted at rest** (`engine/vault.py`, `tests/test_vault.py`): the saved plan, the raw plan JSON and the raw plan copy in the audit log; plaintext exists only while a step needs it (the saved plan is restored for the duration of an apply, then deleted). **Not encrypted:** `terraform.tfstate`, `main.tf` (Terraform reads them in place) and the server log; use an encrypted volume and keep the secret in the environment, not in `data/api_secret`. |
| **D. Idempotency** | FIXED AND TESTED for every mutating endpoint | `Idempotency-Key` on task creation, every stage and job submission: a retry returns the original response (`X-Idempotent-Replay: true`), a different request under the same key is 422, failed attempts do not consume the key, keys are scoped per stage and task (`tests/test_limits.py`, `tests/test_concurrency.py`). Replay lookup is serialized in-process; across processes the version check and state machine still prevent double execution. |
| **E. Per-task concurrency** | FIXED AND TESTED for one process | Per-task locks replace the global lock; reads never wait; independent tasks run in parallel; racing confirm/edit/resolve/replan attempts tested. Audit and task writes are transactional (`BEGIN IMMEDIATE`). Cross-process: every task save is a compare-and-set on a `version` column (`CONCURRENT_MODIFICATION`, 409, nothing written), proven with 3 OS processes doing 45 read-modify-writes with zero lost updates (`tests/test_jobs.py`). |
| **F. Durable jobs** | FIXED AND TESTED | `POST /api/tasks/{id}/jobs` `{op: agent\|plan\|apply}` returns 202; poll `GET /api/jobs/{id}` (status, progress, error code); `POST /api/jobs/{id}/cancel`. Persisted in SQLite, one active job per task, atomic claiming, 1s heartbeats; a job whose worker died becomes `interrupted` and queued jobs run after a restart. Timeout and cancel kill Terraform's whole process tree (`engine/proc.py`). The synchronous endpoints still work but return `JOB_IN_PROGRESS` (409) while a job is active. Ollama calls inside `agent` cannot be interrupted mid-request (only Terraform is killed); cancel takes effect when the call returns. |
| **F. Ollama reliability** | FIXED AND TESTED | Host, model and timeouts configurable (loopback-only unless allowed); real closed port, missing model, malformed model list, malformed answers, HTTP 500, timeout and recovery tested against real sockets (`tests/test_ollama_reliability.py`); deterministic allowlist maps known informal names and never guesses ambiguous ones; capability validation unchanged; no fallback to replay. The pre-existing live-model tests against a real local Ollama (`test_phase1.py`) also ran in the suite. |
| **G. Audit integrity** | FIXED AND TESTED as tamper **detection**, plus an optional external mirror | Keyed HMAC hash chain, transactional appends, local anchor, verify endpoint and CLI; edits, deletions, insertions, reordering, tail truncation, task-row deletion and contract-hash rewrites detected. With `PLANREVIEW_AUDIT_MIRROR` pointing outside the writer's reach, a key-holding attacker who rewrites the database, the chain AND the local anchor is still caught (`tests/test_audit_integrity.py`). **Still not tamper resistance on one machine:** without a mirror, or if the attacker can write the mirror, a rewrite goes undetected. See `docs/audit-integrity.md`. Pre-existing rows are unprotected. |
| **H. Portability** | Windows and Linux: FIXED AND TESTED. macOS: **NOT VERIFIED** | Windows 11 / Python 3.13 / Terraform 1.16: full suite passes. Ubuntu (WSL2) / Python 3.12 / Terraform 1.16: fixtures generated as CI does, full suite passes (326 tests plus 2 live-Ollama tests skipped, none available there) and `tools/load_test.py` passes. That Linux run found and fixed a real portability bug: `test_chaos_10` silently required a live Ollama and would have failed on every CI runner. macOS was not available; the CI matrix (`.github/workflows/backend.yml`) covers it and **has not been run on GitHub**. |
| **H. Load** | IMPLEMENTED AND RUN (bounded, Windows and Linux) | `tools/load_test.py` against a real uvicorn: see the results below. A regression tripwire, not a capacity claim. The reported RSS is of the launcher process and is not meaningful. |
| **I. Operations** | FIXED AND TESTED | Six operations instead of two, defined once in `engine/capabilities.py` (Lambda memory, timeout, one environment variable; S3 Team tag, any one tag, versioning). Each is locked to one resource and attribute; the guard requires the workspace to equal baseline plus exactly that edit; each runs the full pipeline against real Terraform to ALLOW on exactly one resource (`tests/test_scope.py`) and applies in the emulator (`tests/test_emulator_apply.py`). `GET /api/capabilities` lists them. Anything outside this list (new resource types, IAM, networking, RDS) is deliberately still refused. |
| **M4. Emulator apply** | FIXED AND TESTED (moto emulator; no Docker, no AWS) | `tools/emulator.py` runs moto on 127.0.0.1. The baseline is applied to it, then changes go through the full pipeline and the emulator's own API is read back: the permitted change applies (`APPLIED`, `emulated: true`) and every other attribute of Lambda, S3, public-access block and security group is identical afterwards; DENY and unresolved-REVIEW plans never spawn Terraform and leave the emulator unchanged; without emulator mode apply stays blocked (`tests/test_emulator_apply.py`). Safety rails: only a loopback `PLANREVIEW_EMULATOR_ENDPOINT` is accepted, dummy credentials are forced and real AWS credential variables are stripped from the child process. **Emulator fidelity is not AWS fidelity**: moto validates less than AWS, so this proves the pipeline and gate end to end, not AWS behaviour. Real cloud apply remains disabled. |
| **J. Limits** | FIXED AND TESTED | Request body cap (413), per-credential and per-address token-bucket rate limits (429 with `Retry-After`), pagination on the task list and audit endpoints with `X-Total-Count` (`tests/test_limits.py`). Limits are per process. |
| **K. Identity and revocation** | FIXED AND TESTED | v2 tokens carry an accountable `sub` and a `jti`; approvals and applies record who acted and when (audit event and run record); tokens can be revoked immediately (`POST /api/auth/revoke`, `python -m engine.auth --revoke JTI`) with revocations persisted, without touching the audit key (`tests/test_auth.py`). Accountability is only as strong as whoever mints tokens; there is no login system. |
| **L. Terraform guard** | FIXED AND TESTED | `main.tf` is parsed as real HCL (`python-hcl2`): only terraform/provider/resource blocks, only `required_providers` in `terraform`, no provisioners or connections, resource allowlist; the byte-exact baseline-plus-edit comparison stays as the primary control (`tests/test_scope.py`, `tests/test_phase1.py`). Not a general HCL sandbox. |

## Non-negotiable regressions (all in the passing suite)

| Rule | Test |
|---|---|
| Unconfirmed or expired contract cannot authorize | `test_adversarial::test_05_expired_contract_is_rejected_at_evaluation`, `test_chaos::test_chaos_04_expired_contract_blocks_apply`, `test_error_contract` (`CONTRACT_NOT_ACTIVE`) |
| Confirmed-contract tampering detected | `test_adversarial::test_03_direct_sqlite_contract_tampering_is_detected`, `test_chaos::test_chaos_06_…`, `test_audit_integrity::test_rewriting_the_confirmed_contract_…` |
| Saved-plan tampering detected | `test_adversarial::test_04_raw_plan_tampering_…`, `test_chaos::test_chaos_05_modified_saved_plan_blocks_apply`, `test_gate::test_hash_tampering` |
| Policy change invalidates stale evaluation | pipeline `POLICY_CHANGED` path in `apply`/`resolve` (existing gate tests) |
| DENY cannot be approved | `test_chaos::test_chaos_03_…`, `test_api` and my API check earlier (409 `RESOLUTION_NOT_ALLOWED`) |
| EVALUATION_ERROR not approvable | `test_phase1::test_cedar_failure_cannot_be_approved_in_resolve_or_apply`, `test_chaos::test_chaos_08_…` |
| New plan invalidates REVIEW approvals | `test_adversarial::test_06_review_resolution_cannot_replay_to_new_real_plan`, `test_chaos::test_chaos_07_…` |
| Gate not bypassable by direct API call | `test_chaos::test_chaos_01_direct_api_apply_with_deny_blocks_and_never_spawns`, `test_gate::test_direct_deny_never_starts_terraform_apply` |
| Unsupported / ambiguous blocked | `test_phase1` capability tests, `test_error_contract::test_unsupported_operation_keeps_its_code`, `test_ollama_reliability::test_allowlist_does_not_bypass_capability_validation` |
| Unavailable model never becomes replay | `test_phase1::test_model_unavailable_live_mode_never_switches_to_replay`, `test_ollama_reliability` (real sockets) |

## Compatibility

This is an incompatible API change, versioned by `X-PlanReview-API: 2`: routes now need a token; error bodies always use the structured envelope (legacy string `detail` values are gone); some statuses moved (missing task 409→404, invalid contract 409→422); paths and raw output left the default responses. The previous console and the React `api.js` client (which already understands structured errors) need to send the token. No migration is provided for clients that depend on removed fields; raw values remain reachable through the evidence endpoint. Tests that asserted the old statuses were updated deliberately (`test_api`, `test_adversarial`).

## Bounded load test (Windows 11, Python 3.13, one uvicorn worker)

```
health (public)              n=400  workers=16    591.4 req/s  p50=  21.1ms p95=  39.7ms max= 152.8ms  codes={200: 400}
unauthenticated -> 401       n=200  workers=8     682.9 req/s  p50=   8.0ms p95=  27.6ms max=  32.4ms  codes={401: 200}
create task (write)          n=60   workers=8      63.8 req/s  p50=  57.8ms p95= 801.5ms max= 938.4ms  codes={200: 60}
list tasks (read)            n=200  workers=16    155.5 req/s  p50= 100.9ms p95= 131.5ms max= 144.4ms  codes={200: 200}
```

`GET /api/tasks` returns every task (no pagination), so read latency grows with the task count.

## Reproduce

```powershell
.\.venv\Scripts\python.exe -m pytest -q                       # full backend suite (about 10 minutes, real Terraform)
.\.venv\Scripts\python.exe -m pytest tests/test_auth.py tests/test_error_contract.py tests/test_exposure.py tests/test_concurrency.py tests/test_ollama_reliability.py tests/test_audit_integrity.py -q
.\.venv\Scripts\python.exe tools\load_test.py                 # needs: pip install psutil (optional)
.\.venv\Scripts\python.exe -m engine.audit_verify             # verify the audit chain
```
