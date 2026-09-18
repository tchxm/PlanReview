# PlanReview — Final Presentation Guide & Runbook

This guide is written for presenters and evaluators. It assumes zero prior knowledge of Terraform, Cedar policies, or the internal PlanReview codebase.

---

## 1. What PlanReview Solves (The 30-Second Pitch)

When an AI coding agent is tasked with updating cloud infrastructure (Terraform files), who verifies what it actually did?
If the AI hallucinates, ignores prompt instructions, opens a security group port to `0.0.0.0/0`, or weakens S3 bucket public access controls, conventional LLM wrappers will happily execute the code.

**PlanReview establishes an unbypassable security boundary:**

1. A human states a task and **confirms an authority contract** (authorizing specific resources, regions, operations, and strict prohibitions).
2. The agent edits Terraform code (or reproducible fixtures replay changes).
3. A real `terraform plan` is computed and parsed by a deterministic canonicalizer.
4. AWS's open-source **Cedar policy engine** evaluates every changed resource independently:
   - **ALLOW**: Matches the confirmed contract scope.
   - **REVIEW**: Uncovered, uncertain, or unexpected changes requiring explicit human sign-off.
   - **DENY**: Explicitly forbidden by an immutable security policy.
5. An enforceable backend **Execution Gate** strictly prevents `terraform apply` from spawning if any DENY, unapproved REVIEW, expired contract, or tampered plan exists.

> [!IMPORTANT]
> **Core Architecture Invariant:** The LLM never decides authorization. An LLM's explanation of what it changed is not evidence. The real computed Terraform plan is the evidence; Cedar is the judge; and the backend gate enforces the verdict before any process can spawn.

---

## 2. Windows Startup Instructions

Open a PowerShell terminal in `c:\Users\kario\OneDrive\Documents\PlanReview`:

### Step A: Verify Environment

```powershell
# 1. Verify virtual environment and full 52-test test suite
.\.venv\Scripts\python.exe -m pytest -q

# 2. Verify Terraform is installed (v1.16+)
terraform version

# 3. Verify local Ollama is active (for live agent demo)
curl.exe -s http://localhost:11434/api/tags
```

### Step B: Start the Server

```powershell
.\start.ps1
```

_(Or directly: `.\.venv\Scripts\python.exe -m uvicorn engine.api:app --host 127.0.0.1 --port 8000`)_

Open your browser to: **[http://localhost:8000](http://localhost:8000)**

---

## 3. Demo Path A: The 2-Minute Guaranteed Replay (Recommended for Pitch)

_Zero dependency on AI latency, rate limits, or network connectivity. Uses real Terraform planning and live Cedar policy evaluation._

### Screen 01: Create Task

1. **What to enter in "What should the agent change?":**
   ```text
   Increase memory for dev-api Lambda; send unanticipated networking changes to human review. Production and public access are forbidden.
   ```
2. **Execution source:** Select **Local fixture replay**.
3. **What to say:**
   > "We start by giving the system a task. But notice: intent is not authority. Entering text here does not grant permission to change anything yet. We choose 'Local fixture replay' for a guaranteed, deterministic reproduction of real infrastructure changes."
4. **Click:** **"Generate contract →"**
   - _What executes:_ `POST /api/tasks` creates a draft task with a 24-hour expiry and initial safety boundaries in SQLite.

---

### Screen 02: Confirm Contract

1. **Action:** On the right-hand panel, click **"Use three-color demo scope ↗"**.
   - _What happens:_ Updates the JSON draft contract to explicitly forbid `production` and `public_access`, leaves networking uncovered so it will require human review, and sets `max_changed_resources = 3`.
2. **What to say:**
   > "This is the human authorization contract. It is a sealed boundary. We explicitly define what resources, actions, and regions are permitted, and what is strictly forbidden. The AI agent cannot renegotiate or expand this contract."
3. **Click:** **"🔒 CONFIRM contract"**
   - _What executes:_ `POST /api/tasks/{id}/confirm` computes a SHA-256 integrity hash (`confirmed_contract_hash`), commits the contract to SQLite, and permanently locks it. Any direct database tampering will be detected and aborted.

---

### Screen 03: Plan Review (ALLOW / REVIEW / DENY)

1. **Click:** **"Run & evaluate plan"** (or **"Re-run poisoned fixture"**)
   - _What executes:_
     - Staged edits are applied to `main.tf`.
     - Backend executes real `terraform plan` and `terraform show -json`.
     - Deterministic canonicalizer normalizes the diff.
     - AWS Cedar engine evaluates each change against `cedar/policies/security.cedar`.
2. **What to say:**
   > "Notice what happened. The agent attempted three changes. PlanReview did not ask an LLM if this was okay. Real Terraform computed the exact resource changes, and Cedar evaluated them independently:
   >
   > 1. **ALLOW (Green)**: The Lambda function memory update from 512 MB to 1024 MB exactly matches the confirmed contract.
   > 2. **REVIEW (Yellow)**: An ingress rule was added to the security group. It wasn't forbidden, but it wasn't pre-authorized either. It requires human discretion.
   > 3. **DENY (Red)**: The dev assets S3 bucket had its public-access block flags set to false. Cedar's explicit `@id('public_access') forbid` rule fired immediately.
   >
   > Look at the bottom Execution Gate: Apply is blocked."
3. **Click:** **"Verify block via API"**
   - _What executes:_ `POST /api/tasks/{id}/apply` calls the backend gate directly.
   - _What displays:_
     ```json
     {
       "status": "BLOCKED",
       "reason": "1 unresolved DENY; edit configuration and create a new plan",
       "spawned": false
     }
     ```
   - _What to say:_
     > "Even if an attacker or a buggy UI bypassed the disabled button, the backend gate enforces policy before any Terraform process can start. The subprocess was never spawned."

---

### Screen 04: Resolution

1. **Click:** **"Resolve changes ↗"** (navigates to Screen 04: Resolution).
2. **What to point out & say:**
   > "Notice something critical: only the REVIEW item has an approval selector. There is NO option to approve a DENY. A policy violation cannot be waived by human click. To fix a DENY, the code must be remediated and re-planned."
3. **Click:** **"Re-plan without S3 change ↻"**
   - _What executes:_ Re-plans using clean edits where the S3 public access change is removed.
4. **Action:** In the dropdown for `aws_security_group.api`, select **"Approve"**, then click **"Record decisions ✓"**.
   - _What to say:_
     > "We approve the security group change. This approval is cryptographically bound to this exact plan hash. If the Terraform plan changes even by one byte, this approval is instantly invalidated."

---

### Screen 05: Audit Trail

1. **Click:** **"Audit"** (05) in the left sidebar.
2. **What to say:**
   > "PlanReview maintains an append-only, tamper-checked audit log in SQLite. Every contract confirmation, agent edit, raw Terraform plan output, Cedar verdict with determining policy ID, and human decision is recorded. We can export this complete audit package as JSON at any time."
3. **Click:** **"Export audit ↗"** (downloads the audit JSON file).

---

## 4. Demo Path B: Live Ollama AI Agent Demonstration

_For judges who specifically want to see a live local LLM (`llama3.2:3b`) making tool calls._

1. Navigate to **Create task** (01).
2. Enter:
   ```text
   increase dev-api Lambda memory, don't touch networking or production
   ```
3. Under **Execution source**, select **Live Strands / Ollama**.
4. Click **"Generate contract →"**.
5. On the Confirm screen, click **"Use three-color demo scope ↗"**, then **"🔒 CONFIRM contract"**.
6. On the Plan Review screen, click **"Run & evaluate plan"**.
7. **What to say while the spinner runs (~15-20 seconds):**
   > "The backend is currently running a real local Ollama model (`llama3.2:3b`) via the Strands agent framework. The model inspects the Terraform file using read tools and invokes atomic Python file tools. Notice that the model has no bash shell access and cannot write arbitrary files."
8. Once the plan renders, show the three real verdicts (**ALLOW**, **REVIEW**, **DENY**).
9. Click **"Verify block via API"** to prove the gate blocks execution.

### Empirical Ollama Reliability Results

In 5 consecutive, independent test runs across unique workspaces:

- **Responded:** 5/5 (100%)
- **Tools called:** `set_dev_api_memory`, `add_dev_assets_demo_tag`, `weaken_assets_public_access_controls` (5/5)
- **Terraform planned successfully:** 5/5 (100%)
- **Cedar verdicts ALLOW / REVIEW / DENY:** 5/5 (100%)
- **Gate blocked with spawned=False:** 5/5 (100%)
- **Observed duration:** 12s – 53s per run.

---

## 5. What Uses AI vs. What Uses Deterministic Controls

| Pipeline Stage             | Implementation                        | Why It's Built This Way                                                                      |
| -------------------------- | ------------------------------------- | -------------------------------------------------------------------------------------------- |
| Contract Drafting          | Deterministic rule-based extractor    | Prevents prompt injection attacks in the user task prompt from widening authorization scope. |
| Terraform Editing (Replay) | Pinned Terraform fixture files        | 100% deterministic, instant presentation reliability.                                        |
| Terraform Editing (Live)   | Local `llama3.2:3b` via Strands       | Exercises genuine model tool calling in an isolated workspace.                               |
| Terraform Planning         | **Real `terraform plan` subprocess**  | Proves the real Terraform CLI evaluates the HCL changes.                                     |
| Canonicalization           | Deterministic Python diff engine      | Flattens nested unknown/sensitive masks into exact attribute diffs.                          |
| Policy Authorization       | **Real AWS Cedar engine (`cedarpy`)** | Deterministic, auditable, mathematical policy evaluation; never an LLM.                      |
| Execution Gate             | Enforceable backend process check     | Guarantees `subprocess.run(["terraform", "apply", ...])` cannot be called on DENY.           |

---

## 6. Ten Difficult Judge Questions & Grounded Answers

#### Q1: "Why use Cedar instead of just asking an LLM if the plan looks safe?"

> **Answer:** "LLMs are non-deterministic, susceptible to prompt injection, hallucinate compliance, and have no formal proof semantics. Cedar is a formally verified policy language developed by AWS. In Cedar, explicit prohibitions strictly override permissions, evaluation is deterministic and sub-millisecond, and the engine returns the exact determining policy IDs that caused a decision."

#### Q2: "Can an attacker bypass the frontend and call the API directly to run apply?"

> **Answer:** "No. The frontend is just a viewer. The apply gate is enforced strictly on the backend inside `engine/gate.py`. When `POST /api/tasks/{id}/apply` is called, the server checks the active contract expiry, verifies that 0 DENYs exist, checks that all REVIEWs have recorded approvals, verifies the SHA-256 hash of the saved plan file, and checks that cloud apply is disabled. If any check fails, it returns `spawned: false` before any subprocess is created."

#### Q3: "What if someone tampers with the `.tfplan` file on disk before apply?"

> **Answer:** "When `terraform plan -out=plan.tfplan` runs, PlanReview computes and saves `digest(plan.tfplan)` in the database. At the apply gate, the server re-computes `digest(path)` and compares it against `run['plan_hash']`. If a single byte was altered, apply immediately blocks with `'Saved plan missing or hash mismatch'`."

#### Q4: "What if someone edits the SQLite database directly to grant more permissions?"

> **Answer:** "At contract confirmation, PlanReview computes a SHA-256 digest of the canonical JSON contract representation and saves `confirmed_contract_hash`. Every subsequent stage (agent, plan, canonicalize, evaluate, resolve, apply) calls `assert_contract_integrity()`. If the SQLite row was altered, it raises `ValueError('Confirmed contract integrity hash mismatch')`."

#### Q5: "What if the model generates an unexpected edit to another resource?"

> **Answer:** "Because Cedar evaluates on exact resource addresses and types, any resource not explicitly listed in `allowed_resource_addresses` defaults to REVIEW (if safe) or DENY (if it violates policy). It can never silently become ALLOW."

#### Q6: "Why not use OPA / Rego or Terraform Sentinel?"

> **Answer:** "Cedar was designed specifically for application authorization with clear separation of permit and forbid rules, explicit diagnostics returning determining policies, and formal verification proofs via the Lean theorem prover. Unlike Rego, Cedar does not require complex Turing-complete language semantics, making policies simpler to write, audit, and reason about."

#### Q7: "Does this system deploy real infrastructure to AWS?"

> **Answer:** "No, and that is an intentional safety boundary for this MVP. In `engine/gate.py`, any plan containing resources other than `terraform_data` is blocked with `'AWS apply disabled: configure and verify an isolated emulator first'`. Real execution of the apply subprocess is demonstrated safely using Terraform's built-in `terraform_data` resource in `tests/test_gate.py::test_real_local_apply`."

#### Q8: "What happens if a contract expires while the agent is working?"

> **Answer:** "Contract expiry is validated at confirmation, evaluation, and inside `gate_reason` at apply. If `expires_at <= now()`, all verdicts are distrusted and apply returns `BLOCKED: 'Contract expired or unconfirmed'`."

#### Q9: "Can a user approve a DENY verdict in the UI?"

> **Answer:** "No. In `pipeline.resolve()`, the server explicitly validates that only addresses with a verdict of `REVIEW` are accepted. Sending an approval for a DENY address raises a `ValueError(409)`. A DENY can only be resolved by editing the configuration to remove the offending change and generating a fresh plan."

#### Q10: "If I approve a REVIEW on one plan, can that approval apply to future plans?"

> **Answer:** "No. Approvals are strictly bound to the specific run ID and plan hash. When a new plan is generated, `run['resolutions']` is reset to empty `{}`. Reused approvals are strictly blocked, as proven in `test_chaos_07`."

---

## 7. Troubleshooting & Presentation Recovery

| Failure Scenario                             | Immediate Recovery Step                                                                                                                                                                        |
| -------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Port 8000 already in use**                 | In PowerShell: `Get-Process -Id (Get-NetTCPConnection -LocalPort 8000).OwningProcess \| Stop-Process -Force` then run `.\start.ps1`.                                                           |
| **Ollama is slow, hangs, or disconnected**   | **Immediately switch to "Local fixture replay" mode.** The replay mode executes real `terraform plan`, canonicalization, Cedar evaluation, and gate enforcement without needing any AI daemon. |
| **Accidentally left with unapproved REVIEW** | Navigate to Screen 04 (Resolution), choose "Approve", click "Record decisions", then return to Plan Review.                                                                                    |
| **Want to reset workspace clean**            | Delete `data/workspaces/*` or create a new task with a new name.                                                                                                                               |

---

## 8. Explicit List of What Is NOT Supported (Do Not Overpromise)

1. **Not an arbitrary Terraform coding assistant:** The agent has strictly defined tools (`set_dev_api_memory`, `add_dev_assets_demo_tag`, `weaken_assets_public_access_controls`). It cannot write arbitrary HCL modules, provisioners, or backends.
2. **Not connected to live AWS accounts:** Real AWS apply is disabled by design.
3. **Not a multi-tenant cloud service:** Single-user local tool bound to `127.0.0.1`.
4. **Not a sandbox for malicious HCL providers:** We guard executable constructs (`provisioner`, `data`, `module`), but we do not claim kernel-level provider sandboxing.

---

## 9. Final Pitch Readiness Recommendation

**VERDICT: READY FOR PRESENTATION.**

- **52/52 tests pass.**
- Apply gate is verified unmocked with real state hashing.
- Both 2-minute guaranteed replay and live Ollama agent paths are verified.
- All edge cases (tampering, expiry, missing data) fail closed with `spawned: false`.
