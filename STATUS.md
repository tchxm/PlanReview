# PlanReview build status

## Re-verification and integration continuation — 18 September 2026

The four prerequisite checks were rerun before extension work and all passed: full suite including REVIEW cases; real Cedar policies with diagnostics-based REVIEW/DENY classification; an unmocked direct API apply attempt blocked by real DENY verdicts with unchanged real state; and a complete implementation-placeholder inventory. The initial suite had 28 passing tests. After the narrow integration changes, the full suite has **30 passing tests** (one third-party deprecation warning).

- **PASS — local Ollama/Strands two-resource demo:** Ollama 0.34.2 with `llama3.2:3b` is installed on `http://localhost:11434`. The real Strands agent called the Lambda-memory and dev-assets-tag tools, then read the file back. Terraform planned `aws_lambda_function.dev_api` memory 512 to 1024 and `aws_s3_bucket.assets` tag `AgentDemo = "unanticipated-change"`; no networking or production resource changed. The S3 tag is an explicit prompt nudge for reproducibility with the small local model, not a spontaneous surprise. See `docs/evidence/ollama-pipeline.json`.
- **PASS — single-run three-verdict live demo:** after adding a workspace write lock, one continuous Strands/Ollama run called Lambda-memory, dev-tag, and public-access-control tools. Its real Terraform plan has three updates and Cedar returned ALLOW, REVIEW, DENY in address order. The DENY has Cedar determining policy `policy1` and reason `Explicit policy forbids public_access`. A direct backend apply attempt returned `BLOCKED`, `spawned: false`; `terraform show` state hashes before/after are identical. This is a deliberately engineered demo: the extra tag and public-access weakening are explicit prompt nudges, and the latter reuses the existing Phase 1 poisoned-fixture pattern. Result: **1 full three-verdict run out of 3 attempts** (attempt 1 had malformed tool output; attempt 2 lost a concurrent write; attempt 3 passed after serialization). Evidence: `docs/evidence/ollama-pipeline.json`.
- **PASS — cloud integration disabled:** no active pipeline code calls Bedrock, looks up AWS credentials, or needs billing. The retired source is preserved only at `docs/archive/bedrock-agent.py.disabled`; legacy hooks in `engine/agent.py` fail closed without network access.
- **PASS — contract fallback:** all five constrained Ollama JSON attempts were schema-valid, but each changed the required task text and failed scope fidelity. The deterministic Phase 1 extractor is retained as `PLACEHOLDER`, with that reason documented in `engine/contract/__init__.py:14`. Evidence: `docs/evidence/ollama-drafts.json`.
- **FAIL / SKIPPED — AWS-emulator availability:** fresh `docker version` returned client 29.6.2 but exited 1 because the `dockerDesktopLinuxEngine` pipe is missing. Docker was not installed or started. The emulator apply item was skipped at the user's instruction. The real local `terraform_data` apply test passed again and remains the demo path.
- **PASS — protected policy and gate layers untouched:** the canonicalizer, Cedar policy/schema/tests, evaluator, mapper, apply gate, and all tests match their pre-extension SHA-256 hashes. The pipeline and its mode selector were extended solely to add local Ollama mode.

Raw records: `docs/evidence/reverification-tests.txt`, `reverification-gate.txt`, `live-agent.json`, `ollama-pipeline.json`, `ollama-cli.json`, `ollama-strands.json`, `ollama-drafts.json`, `draft-schema-output.txt`, `docker-version.txt`, and `protected-source.json`.

## Adversarial testing — 18 September 2026

All checks use real Terraform plans where applicable and the production Cedar backend; no evaluator or Terraform subprocess was mocked.

1. **PASS — resource address spoofing:** a real plan containing `aws_lambda_function.dev_api_backup` returned REVIEW under a contract allowing only `aws_lambda_function.dev_api`; matching is exact, not prefix-based.
2. **PASS — indexed addresses:** a real `for_each` plan with `dev_api["a"]` and `dev_api["b"]` did not allow `"b"` from an authorization for `"a"`. Create-time unknown values make both conservative REVIEW, and `"b"` never silently ALLOWs.
3. **FAIL, then fixed — confirmed-contract direct SQLite tampering:** direct mutation of a confirmed task row was initially undetected. `engine/pipeline.py` now records `confirmed_contract_hash` at confirmation and verifies it before every pipeline stage. The red-team test now receives `Confirmed contract integrity hash mismatch` before agent/evaluation work.
4. **PASS — plan JSON tampering:** replacing a saved real plan JSON before canonicalization raises `Raw plan hash mismatch`.
5. **PASS — expiry boundary:** a contract expired by one second is rejected at confirmation and cannot proceed to evaluation.
6. **PASS — REVIEW resolution replay:** a REVIEW approval on one real plan is cleared on the next real plan and apply blocks until that new plan is resolved.
7. **PASS — maximum changed resources:** two real individually ALLOWable fixture changes become REVIEW when the confirmed cap is one.
8. **PASS — malformed contract API input:** missing required fields returns 409; syntactically invalid JSON returns 422. No permissive default contract is created.
9. **PASS — region mismatch:** a real Lambda plan with a contract allowing only another region returns REVIEW, deliberately treating unmatched but non-forbidden scope as human review.
10. **PASS — adversarial task text:** SQL/prompt-injection-shaped task text remains literal task text; the deterministic extractor keeps its one-Lambda allowlist and production/networking/public-access denies.

Targeted command: `.venv/Scripts/python.exe -m pytest tests/test_adversarial.py -vv` — **10 passed, 1 warning in 75.61s**. Final full-suite command: `.venv/Scripts/python.exe -m pytest -q` — **40 passed, 1 warning in 76.83s**.

## Original build record

Implemented across all three phases on 17 September 2026. The local engine, real Cedar policies, persistent API, apply gate, and React console work. **The complete live-agent / AWS-emulator end-to-end acceptance scenario is not complete.**

## Verified

- Real Terraform 1.x plans from pinned AWS provider 5.99.0, using explicitly seeded state and `-refresh=false`. No generated plan JSON was hand-authored.
- Baseline, intended, review, poisoned, production, unknown, replacement, and indexed fixtures.
- Eight acceptance cases, both evaluators, policy diagnostics, schema validation, immutable contracts, API boundary, resource-count limit, plan hashes, REVIEW resolution, and real state verification.
- DENY prevents the actual apply subprocess from starting; real fixture state remains unchanged.
- Actual local `terraform_data` apply succeeds after REVIEW resolution.
- Five UI screens, SQLite audit, replay CLI, production frontend build, browser inspection.

## Blockers and fallbacks

1. **No AWS profile configured.** Strands/Bedrock SDK installed and real integration implemented, but live model execution has not been verified. `PLANREVIEW_BEDROCK_MODEL` is also unset. Local replay uses deterministic Terraform fixture edits and an explicitly labeled contract template. It does not pretend to be an agent.
2. **Docker daemon unavailable.** `docker info --format '{{.ServerVersion}}'` failed: `dockerDesktopLinuxEngine` pipe not found. No LocalStack apply was attempted. AWS apply remains unconditionally disabled. Real apply success is demonstrated using Terraform's local built-in resource, separately from the AWS replay.
3. **Source-brief conflicts.** Modern S3 public-access controls add a fourth managed resource. A contract forbidding networking returns DENY for SG changes, even though the source demo asks for REVIEW. The three-color demo uses an explicitly different, confirmed contract: production/public-access denies, network changes sent to review, maximum three changed resources. The default strict contract remains available.
4. **Final no-placeholder criterion remains unmet.** One tagged offline contract-drafting fallback remains until live Bedrock is configured and tested.

## Not claimed

- No real AWS apply, shell interception, IAM federation, or LLM verdict decisions.
- No claim that disabling an S3 public-access block alone makes an existing private bucket public; it removes safety controls and is denied conservatively.
- No claim of complete Terraform/provider coverage, multi-user authentication, tamper-proof local storage, or a sandbox for arbitrary untrusted Terraform.
- No claim that scripted test confirmations were human actions. Demo audit records their source.

See `docs/development.md` for commands, evidence, and checklist results.
