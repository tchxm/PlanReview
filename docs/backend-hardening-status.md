# Backend hardening: status

Branch `backend-hardening`, from `58e3aaa`. Real AWS apply is still disabled; nothing here contacted AWS. No frontend or `design/` files were changed.

Statuses use exactly: **FIXED AND TESTED**, **IMPLEMENTED BUT NOT FULLY VERIFIED**, **BLOCKED BY ENVIRONMENT**, **NOT IMPLEMENTED**.

| Item | Status | Evidence and limits |
|---|---|---|
| **A. Authentication** | FIXED AND TESTED | Signed, expiring, scoped bearer tokens on every route except `/api/health`; missing, malformed, forged, tampered-scope, expired and wrong-scope credentials tested on every endpoint (`tests/test_auth.py`). Origin and Host checks kept. Secret from env or an ignored file, never committed; tokens never echoed. **Limit:** another process running as the same OS user can read the secret file, the DB and the workspaces. A frontend built before this change must send a token (or use the dev-only opt-out). |
| **B. Structured errors** | FIXED AND TESTED | One envelope with stable codes and statuses 404/422/409/400/502/503/504/500; per-endpoint 404 and per-family contract tests (`tests/test_error_contract.py`); untyped failures become 500, never client errors; raw diagnostics kept in the log with a request id. |
| **C. Data exposure** | FIXED AND TESTED for API responses | Task and audit responses no longer carry paths, full Terraform stdout, raw plan JSON or edited `.tf` text (recursive key and path scans, `tests/test_exposure.py`); raw evidence only via the `evidence` scope. **Limits:** the SQLite file, workspaces and the **server log** still contain raw Terraform output (on failure) by design, and are unencrypted. Sensitive-value masking still relies on the Phase 1 canonicalizer. |
| **D. Durable jobs and truthful cancellation** | **NOT IMPLEMENTED** | Long Terraform and Ollama stages are still single blocking requests. A browser timeout is not a cancellation, and there is no job table, progress, restart recovery or process termination. Not attempted rather than half-built. |
| **D. Idempotency** | FIXED AND TESTED for task creation only | `Idempotency-Key` on `POST /api/tasks`: simultaneous retries yield one task, key reuse with a different body is 422, failed creations don't consume the key (`tests/test_concurrency.py`). Stage operations are protected by per-task locks plus the state machine (racing edits/confirms yield exactly one success), not by keys. |
| **E. Per-task concurrency** | FIXED AND TESTED for one process | Per-task locks replace the global lock; reads never wait; independent tasks run in parallel; racing confirm/edit/resolve/replan attempts tested. Audit and task writes are transactional (`BEGIN IMMEDIATE`). **Not proven across processes:** run a single Uvicorn worker. |
| **F. Ollama reliability** | FIXED AND TESTED | Host, model and timeouts configurable (loopback-only unless allowed); real closed port, missing model, malformed model list, malformed answers, HTTP 500, timeout and recovery tested against real sockets (`tests/test_ollama_reliability.py`); deterministic allowlist maps known informal names and never guesses ambiguous ones; capability validation unchanged; no fallback to replay. The pre-existing live-model tests against a real local Ollama (`test_phase1.py`) also ran in the suite. |
| **G. Audit integrity** | FIXED AND TESTED as tamper **detection** | Keyed HMAC hash chain, transactional appends, local anchor, external anchor export, verify endpoint and CLI; edits, deletions, insertions, reordering, tail truncation, task-row deletion and contract-hash rewrites detected (`tests/test_audit_integrity.py`). **Not tamper resistance and not protection against a compromised machine owner** (a test demonstrates a key-holding rewrite fooling local verification). See `docs/audit-integrity.md`. Pre-existing rows are unprotected. |
| **H. Portability** | Windows: FIXED AND TESTED. Linux and macOS: **BLOCKED BY ENVIRONMENT** | Full suite runs on Windows 11 / Python 3.13 / Terraform 1.16. WSL Ubuntu here lacks `python3-venv` and Terraform (installing needs sudo, not done); no macOS available. A CI matrix (`.github/workflows/backend.yml`) is prepared but **has not been run**: IMPLEMENTED BUT NOT VERIFIED. Process-termination behaviour was not tested because cancellation is not implemented. |
| **H. Load** | IMPLEMENTED AND RUN (bounded, Windows only) | `tools/load_test.py` against a real uvicorn: see the results below. A regression tripwire, not a capacity claim. The reported RSS is of the launcher process and is not meaningful. |
| **I. New operations** | **NOT IMPLEMENTED** | No new capability was added. Adding operations safely needs, per operation, a schema, strict validation, Cedar policy coverage, real-plan fixtures and adversarial tests; that work was not started. |
| **M4. Isolated emulator apply** | **BLOCKED BY ENVIRONMENT (UNVERIFIED)** | The Docker CLI is installed but the daemon is not running (`open //./pipe/dockerDesktopLinuxEngine: The system cannot find the file specified`), and no emulator image is present. Nothing was simulated. The existing local-resource apply proof (`tests/test_gate.py::test_real_local_apply`) and DENY-never-spawns tests ran with real local Terraform; that is not emulator evidence. |

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
