# PlanReview

A local security checkpoint for Terraform changes. Confirm an immutable contract, inspect a real plan, evaluate each resource with Cedar, resolve REVIEW items, and enforce the result at the apply subprocess boundary.

**Working locally:** real Terraform fixtures, deterministic and Cedar evaluation, FastAPI, SQLite audit, React/Tailwind console, local Ollama/Strands Terraform editing, blocked AWS apply proof, and successful local-resource apply proof. Docker-based emulator apply remains unavailable. See [STATUS.md](STATUS.md).

## Start on Windows

Requirements: Python 3.11+, Node 20+, Terraform on PATH. Fixture planning uses dummy AWS credentials and performs no AWS refresh or apply.

```powershell

```

Open [the console](http://localhost:8000) or [the API documentation](http://localhost:8000/docs). The server listens only on loopback. Run the frontend build before starting the backend so it can mount the compiled console.

On Linux/macOS use `.venv/bin/python`, `npm`, and `python -m uvicorn engine.api:app --host 127.0.0.1 --port 8000`. Python requirements were executed on Windows 3.12; platform-specific lock output is in `requirements.lock.txt`.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\run-demo.ps1
# Reproducible automation; approvals are marked as scripted demo actions:
.\run-demo.ps1 -Scripted
# Leave a three-color run available in the console:
.\run-demo.ps1 -Scripted -KeepDeny
```

`./run-demo.sh` provides the same interactive pipeline on Bash. It asks for two demo actions: confirm the scope, then resolve/re-plan. The final AWS apply stays blocked because no emulator is configured. `tests/test_gate.py::test_real_local_apply` separately executes a genuine local Terraform apply.

## Contract semantics

ALLOW requires an exact address, resource type, operation, and region match. Unknown, sensitive, unsupported, or uncovered changes require REVIEW. Explicit production/public-access policies and any confirmed networking prohibition return DENY. A proven forbidden change takes precedence over uncertainty. An expired or unconfirmed contract is unusable.

The default contract forbids networking and allows one changed resource. For the source brief's three-color example, use **Use three-color demo scope** before confirming: remove networking from explicit denies and allow three changed resources. This means the SG change is uncovered and requires review. The original wording “do not change networking” cannot honestly produce REVIEW under a networking forbid.

REVIEW approval is tied to one saved plan. A new plan or re-evaluation clears resolutions. DENY cannot be waived; edits must be reverted and a fresh plan evaluated. Plan and policy hashes are checked before execution.

## Local model integration

Install Ollama and pull `llama3.2:3b`, then select **Live Strands / Ollama** in Create Task. Strands connects only to `http://localhost:11434` and can request the narrowly authorized Lambda-memory edit; it cannot invoke Terraform or decide verdicts. The deterministic contract extractor remains authoritative because repeated constrained local-model JSON outputs did not preserve the complete task text. Read and edit the contract before confirmation.

## Structure

```text
engine/              Canonicalizer, contract, evaluators, gate, storage, API
cedar/               Real policies, schema, policy tests
terraform/fixtures/  Reproducible AWS configuration variants
terraform/scripts/   Seed-state and real-plan generator
tests/fixtures/      Actual terraform show -json output
web/                 React + Tailwind console
docs/evidence/       State and execution proof
data/                Local SQLite and saved per-task plans (gitignored)
```

Read [architecture](docs/architecture.md), [threat model](docs/threat-model.md), [development evidence](docs/development.md), and [demo script](docs/demo-script.md).
