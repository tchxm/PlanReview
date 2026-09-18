# Architecture

The pipeline has discrete API calls: create/draft → confirm → edit → plan → canonicalize → evaluate → resolve → apply. `GET /api/tasks/{id}/audit` reads persisted events without running the pipeline.

## Data boundaries

1. **Contract:** a frozen Pydantic model with immutable tuple collections. Draft contracts are inert. Confirmation validates concrete deny categories and expiry. The server refuses subsequent changes.
2. **Edits:** offline fixture replay or optional live Strands file tools in a task-specific workspace. The contract is never supplied to the editing agent as negotiable authority. Provider changes and executable Terraform constructs are rejected before planning; this is a limited fixture guard, not a general sandbox.
3. **Terraform:** subprocesses with timeouts and captured output. Fixture state is constructed explicitly; all plan JSON comes from `terraform show -json`. Every task keeps a saved binary plan, raw JSON, hashes, and command output.
4. **Canonicalizer:** filters no-ops, pairs replacement actions, preserves exact indexed addresses, recursively compares attributes, redacts sensitive values, retains unknown flags, extracts region and environment evidence. Unsupported resources and malformed inputs become unknown REVIEW items.
5. **Mapper:** converts canonical changes into Cedar context facts. It identifies supported public-access-control weakening, production tags, and networking categories. It does not assign verdicts.
6. **Evaluator:** policies live in `.cedar` files. Cedar Allow becomes ALLOW; Deny with determining forbid policies becomes DENY; Deny with empty determining policies becomes REVIEW. Diagnostics errors also become REVIEW. The deterministic implementation remains available explicitly for regression tests. There is no silent Cedar-to-ALLOW fallback.
7. **Run limits:** aggregate resource count and unverifiable cost caps turn otherwise allowed items into REVIEW. Explicit DENY remains DENY.
8. **Apply:** checks active contract, DENY, unresolved/rejected REVIEW, policy hash, and saved-plan hash before subprocess creation. Only local `terraform_data` execution is enabled in this build. Terraform itself rejects stale state on saved-plan apply.
9. **Persistence:** SQLite stores task snapshots and append-only application events transactionally. Raw plan files are retained locally and raw plan content is also included in new plan audit events. The filesystem/SQLite owner remains trusted.

## Processes

FastAPI serves the production React bundle and JSON API. Terraform and Cedar's native binding execute on the backend; Cedar does not require a daemon. Vite is optional for frontend development. A process-local lock serializes API mutations; run a single Uvicorn worker.

## Supported limits

This release targets the supplied Lambda, SG, bucket, and S3 public-access-block fixtures. It is not a complete classification system for every AWS resource or embedded policy document. New types fail toward REVIEW. Region expressions that cannot be proven statically also require review. Sensitive values are redacted in canonical views; raw Terraform evidence remains sensitive local data.
