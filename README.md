# PlanReview

A local security checkpoint for Terraform changes. Confirm an immutable contract, inspect a real plan, evaluate each resource with Cedar, resolve REVIEW items, and enforce the result at the apply subprocess boundary.

**Working locally:** real Terraform fixtures, deterministic and Cedar evaluation, FastAPI, SQLite audit, React/Tailwind console, local Ollama/Strands Terraform editing, blocked AWS apply proof, and successful local-resource apply proof. Docker-based emulator apply remains unavailable. See [STATUS.md](STATUS.md).

## Architecture (Phase 2)

```text
Browser -> React/Vite (127.0.0.1:5173) -> relative /api -> FastAPI (127.0.0.1:8000)
                                                            -> Strands/Ollama, Terraform, Cedar, SQLite
```

FastAPI serves **only** the API (`/api/*`, `/docs`, `/openapi.json`); it does not host the frontend and starts with or without `web/dist`. Vite serves the UI and proxies `/api`, `/docs` and `/openapi.json` to FastAPI. All frontend HTTP goes through `web/src/api.js`. See [API contract](docs/api_contract.md) and the [Phase 3 migration map](docs/phase3_migration_map.md). The PlanBound visual site in `design/` is a standalone prototype with sample data; it is not connected to the backend.

## Start on Windows (development)

Requirements: Python 3.11+ (3.12/3.13 tested), Node 20+, Terraform on PATH. Fixture planning uses dummy AWS credentials and performs no AWS refresh or apply. No AWS credentials are needed.

One-time setup, from the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe terraform\scripts\generate.py   # creates local Terraform state/plans for fixtures (needs network for the AWS provider on first run)
cd web; npm ci; cd ..
```

`generate.py` rewrites the tracked fixture files under `terraform/fixtures/` and `tests/fixtures/`; review `git status` afterwards and do not commit incidental changes.

Run each service in its own terminal:

```powershell
.\start.ps1            # FastAPI  -> http://127.0.0.1:8000  (docs: /docs)
.\start-frontend.ps1   # Vite     -> http://127.0.0.1:5173
```

There is no single-command launcher. Open <http://127.0.0.1:5173>. Check it works:

```powershell
curl.exe http://127.0.0.1:8000/api/health   # direct
curl.exe http://127.0.0.1:5173/api/health   # through the Vite proxy
```

Both return `{"status":"ok","evaluator":"cedar","cloud_apply":false}`. The **API reference** link in the console opens `/docs` via the proxy. Stop each service with Ctrl+C in its terminal.

Production build of the UI (does not need FastAPI running): `cd web; npm run build`. The build output is not served by FastAPI.

Common failures:

| Symptom | Fix |
|---|---|
| Console shows `BACKEND_UNAVAILABLE` / "backend is not reachable" | Start `.\start.ps1`; check port 8000 is free. |
| `Missing .venv` | Run the one-time setup above. |
| `409 Pipeline incomplete: run fixture generator first` | Run `terraform\scripts\generate.py`. |
| `MODEL_UNAVAILABLE` in Live mode | Start Ollama and `ollama pull llama3.2:3b`. The backend never falls back to replay silently. |
| Vite: port 5173 in use | Stop the other process (Vite is set to `strictPort`, so the Origin allow-list stays valid). |
| `403 Cross-origin mutation blocked` | Open the UI on `127.0.0.1:5173` or `localhost:5173`; other origins are refused by design. |
| `Invalid host header` | Only `localhost` / `127.0.0.1` Host headers are accepted. |

Set `PLANREVIEW_API_URL` to point Vite at a different local backend URL (development only).

On Linux/macOS use `.venv/bin/python -m uvicorn engine.api:app --host 127.0.0.1 --port 8000` and `cd web && npm run dev`. Platform-specific lock output is in `requirements.lock.txt`.

## Verify

```powershell
.\.venv\Scripts\python.exe -m pytest -q   # backend (slow: real Terraform)
cd web; npm test                              # frontend API-client tests (mocked fetch)
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
