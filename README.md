# PlanReview

A local security checkpoint for Terraform changes. Confirm an immutable contract, inspect a real plan, evaluate each resource with Cedar, resolve REVIEW items, and enforce the result at the apply subprocess boundary.

**Working locally:** real Terraform fixtures, deterministic and Cedar evaluation, FastAPI, SQLite audit, React/Tailwind console, local Ollama/Strands Terraform editing, blocked AWS apply proof, and successful local-resource apply proof. Docker-based emulator apply remains unavailable. See [STATUS.md](STATUS.md).

## Backend hardening (API v2)

The API now requires a bearer token (except `GET /api/health`). The signing secret comes from `PLANREVIEW_API_SECRET` or a generated file `data/api_secret` (gitignored; never commit it).

```powershell
.\.venv\Scripts\python.exe -m engine.auth mint --scopes read,write --ttl 8h          # prints a token once
curl.exe -H "Authorization: Bearer <token>" http://127.0.0.1:8000/api/tasks
.\.venv\Scripts\python.exe -m engine.audit_verify                                   # verify the audit hash chain
```

Scopes: `read`, `write`, `evidence` (raw evidence and audit verification). For local frontend development only, `PLANREVIEW_INSECURE_NO_AUTH=1` disables authentication (logged loudly). A frontend built before this change must be updated to send the token. Run a **single** Uvicorn worker. Read [docs/backend-hardening-audit.md](docs/backend-hardening-audit.md), [docs/backend-hardening-status.md](docs/backend-hardening-status.md) and [docs/audit-integrity.md](docs/audit-integrity.md) for exactly what is and is not claimed.

## PlanBound frontend (Phase 3)

`web/src/planbound/` is the original PlanBound experience (boot gate, globe, neural network, camera descent, tree, CRT reviewer) running against the real backend. The 3D engine in `engine/` is generated from `design/planbound-site.html` by `tools/port_planbound_engine.py` (bodies unchanged apart from marked `// PORT:` hooks) on three r128; the original CSS and markup are reused. Pages under `pages/` are backend-driven: Workspace, New task, Contract, Plan Review, Evidence, How it works, About. See [docs/phase3_visual_contract.md](docs/phase3_visual_contract.md). Cinematic sections are illustrations and are labelled; task data, verdicts, hashes, the gate and the audit come only from the backend. Real AWS apply is disabled.

## Architecture (Phase 2)

```text
Browser -> React/Vite (127.0.0.1:5173) -> relative /api -> FastAPI (127.0.0.1:8000)
                                                            -> Strands/Ollama, Terraform, Cedar, SQLite
```

FastAPI serves the API (`/api/*`, `/docs`, `/openapi.json`) and the PlanBound site at `/`; it starts with or without `web/dist` (the Vite console in `web/` is separate). Vite serves the UI and proxies `/api`, `/docs` and `/openapi.json` to FastAPI. All frontend HTTP goes through `web/src/api.js`. See [API contract](docs/api_contract.md) and the [Phase 3 migration map](docs/phase3_migration_map.md). The PlanBound visual site in `design/planbound-site.html` runs two ways (see [PlanBound site](#planbound-site-server-and-offline-modes)).

## PlanBound site (server and offline modes)

One command serves the API and the PlanBound site on a single origin (no CORS):

```powershell
.\start.ps1            # then open http://127.0.0.1:8000/
```

The nav shows **LIVE · server** and every verdict, hash and evidence record comes from `/api/site/*`, computed by `engine/site.py` (a port of the in-browser engine: same 8 rules in the same order, same contract hash and plan hash). Evidence is an HMAC-chained log per browser session; **Verify integrity** recomputes the chain on the server. The site API needs no token because it holds no real data or capability: it never touches Terraform, cloud accounts or the task pipeline, and "Apply" only records a simulated event. It is same-origin only, rate limited, size limited and bounded (sessions, records, plan size).

If the server is unreachable, or you open `design/planbound-site.html` directly (`file://`), the page runs the same engine in the browser: **OFFLINE · browser demo**, sample data, state kept in `sessionStorage`, and Verify integrity is a browser-only consistency check (not a chain). If the server drops mid-session the page says so, keeps your boundary and plan, and offers **Retry** or **Continue offline**; clicking the indicator reconnects and replays offline decisions to the server.

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

There is no single-command launcher. Open <http://127.0.0.1:5173> for the PlanBound interface (hash routes such as `/#/workspace`). The earlier functional console is kept as a fallback at <http://127.0.0.1:5173/console.html>. Check it works:

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
.\.venv\Scripts\python.exe tools\test_phase2_smoke.py   # real FastAPI + Vite processes and /api proxy (ports 8000/5173 must be free)
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
