# Phase 3 migration map: PlanBound design → real PlanReview backend

Status: **planning document only.** Phase 2 does not migrate any visuals. `design/` is unchanged.

Sources read: `design/SITE_README.md`, `design/SITE_SELF_REVIEW.md`, `design/planbound/{site-app,site-engine,site-views,build_site}` and the module list in `design/planbound/` (`core, boot, globe-end, tree, robot, cursor, audio, perf, site-support, site-ui, site.css`). Backend reference: [api_contract.md](api_contract.md).

## Ground rules (binding for Phase 3)

The standalone site (`design/planbound-site.html`) is a **browser-only prototype**. Its `site-engine.js` holds a sample rules engine, sample plans A/B/C, a browser contract with a browser-generated hash, a session evidence store and a simulated apply. None of that is authority or evidence.

1. **Do not carry `site-engine.js` (sample rules, sample plans, `PB.store` authorization, simulated apply) into the live product.** The React app must never compute ALLOW/REVIEW/DENY, gate state or apply eligibility. It renders `run.verdicts`, `run.apply_result` and `audit` returned by the backend.
2. The live product uses only: backend-confirmed contracts (`confirmed_contract_hash`), real saved Terraform plans (`run.plan_hash`), backend canonical changes (`run.canonical`), actual Cedar verdicts (`run.verdicts`), backend-authorized REVIEW decisions (`/resolve`), backend-enforced gate results (`/apply` → `apply_result`), persisted audit (`/audit`).
3. Sample A/B/C must not appear as product features and must not imply IAM, RDS or security-group **editing** support. Supported edits are only `update_memory` (dev_api Lambda) and `update_tags` (assets S3 `Team`). Replay fixtures may be labeled "fixture replay", never "sample" that suggests generality.
4. Browser-generated contract hashes (12-char) are not backend evidence; show `confirmed_contract_hash` from the backend.
5. Pasted JSON is not an authenticated Terraform plan. Remove the paste-plan feature or keep it strictly as a labeled offline explainer that never touches gate state.
6. "Applied (simulated)" is not an infrastructure apply. Real AWS apply is disabled; the live UI shows the backend's `BLOCKED` reason.
7. Remove/replace the "SAMPLE DATA" badges only where the underlying data becomes real; anything still fake stays labeled.
8. A visually enabled button never proves authorization; the backend decides. UI disabling is a convenience only.
9. Frontend HTTP goes through `web/src/api.js` only. `EVALUATION_ERROR` is a technical failure, never REVIEW.
10. Original 3D components, shaders, camera descent and interaction sequence are preserved, not redesigned.

## Target frontend architecture

- `web/` (React/Vite) stays the app. The design is ported into React modules (routes as React Router or hash-router views, `site.css` as CSS modules or scoped stylesheet). No iframe. No single giant component. Design sources stay in `design/` as the visual reference.
- Server state lives in one store/hook layer wrapping `api.js` (task list, current task, latest run, audit). Requests carry an `AbortSignal` from the owning component; an abort only stops the browser wait, so the UI says the backend may still be running and re-fetches `GET /tasks/{id}`.
- Stale state rule for every view: after any failed or timed-out mutation, re-read the task; never assume the stage.

## WebGL / 3D lifecycle (safe React integration)

The 3D code (`core.js, boot.js, globe-end.js, tree.js, robot.js, cursor.js, audio.js, perf.js`) is written as global IIFEs on `window.PB`, creating renderers/canvases, `requestAnimationFrame` loops and listeners at load. Porting risks: duplicate renderers on remount, React StrictMode double-invocation, leaked listeners, two loops.

Approach:
1. Wrap the scene in a single **`SceneHost`** mounted once at the app root, above the router. It owns one canvas per scene (globe/tree, robot), one shared `THREE.WebGLRenderer` each, and one `requestAnimationFrame` loop driven from a single scheduler (`PB.perf` sampling stays).
2. Convert each IIFE into `init(container) → { dispose() }` factories. `dispose()` cancels the rAF, removes every listener it added (keep the list of `[target,event,fn]`), disposes geometries/materials/textures, calls `renderer.dispose()` and `forceContextLoss()`, and stops audio nodes.
3. Use an idempotent singleton guard (`if (scene) return scene`) so StrictMode's double effect cannot create two renderers; cleanup runs on real unmount only.
4. Route changes do not unmount `SceneHost`. Landing route shows the canvas; other routes pause the loop (`visible=false`) rather than destroy it. Pause on `document.hidden` and when off-screen (IntersectionObserver), as `PB.globe.visible` already models.
5. Scene ↔ React data through a tiny event bus/store with scoped subscriptions returning unsubscribe functions (`site-support.js` `PB.bus.on` already returns an `off`). The tree's gate and leaf colors are driven by backend verdict data (props), not `PB.store`.
6. Preserve `prefers-reduced-motion`, touch/coarse-pointer fallbacks, `PB.webgl=false` fallback, and (new in Phase 3; the design has no `webglcontextlost` handler today) `webglcontextlost/restored` handling. Keep the boot gate ("CLICK TO START") since it also unlocks audio.
7. Tests: mount/unmount ×N leaves 1 canvas, 0 stray listeners, 0 running loops (assert via counters), and no console errors.

## Component map

Phase key: **P3a** foundation + read-only views, **P3b** workflow (create → confirm → plan → resolve), **P3c** evidence/polish/QA, **P4+** needs new backend work.

| # | Component | 1. Design source | 2. Browser-only/sample data | 3. Real backend info needed | 4. Existing endpoint | 5. Missing | 6. Loading / empty / error / stale | Phase |
|---|---|---|---|---|---|---|---|---|
| 1 | Landing page + globe | `core.js`, `boot.js`, `globe-end.js`, `#home-view` in `planbound-site.html` | Session counters "PLANS EVALUATED / CHANGES GATED / HUMAN DECISIONS" (`PB.store.metrics`) | Optional real counts from task list | `GET /tasks`, `GET /health` | No summary/metrics endpoint | Boot progress gate; counters show "—" until loaded; on error show badge "backend unreachable" (globe still renders); refetch on focus | P3a |
| 2 | Camera descent | `core.js` (progress `P`, `targetProgress`, travel), `globe-end.js` | none | none (pure visual) | — | — | No data dependency; degrade to static frame if WebGL unavailable | P3a |
| 3 | Tree + gate visualization | `tree.js`, `site-app.js` `homeState` | Gate open/closed and 3 verdict leaves read `PB.store` sample verdicts | Latest task's `runs[-1].verdicts`, `apply_result` | `GET /tasks` (latest), `GET /tasks/{id}` | Needs a "current task" concept (latest by `created_at`) | No task: neutral/idle tree with copy "No plan yet"; loading: dim; error: neutral + banner; stale: refetch after any mutation. Gate is closed unless backend says otherwise; it is never open (real apply disabled) except as data from `apply_result` | P3a |
| 4 | Robot reviewer | `robot.js`, `#unit` section | Robot status text/steps (canned) | Latest run state (stage, verdict counts) to animate status | `GET /tasks/{id}` | none required | Idle animation when no data; status text from `stage`; error state shows neutral | P3a |
| 5 | Task creation | Not in the new site (uses Contract wizard); existing `web/` console "Create task" screen | Boundary wizard pre-fills environment/classes/blast radius | Natural-language request + `mode` | `POST /tasks` | none | Submit disabled while busy; long in Ollama mode → show progress copy; errors: `UNSUPPORTED_OPERATION`, `AMBIGUOUS_REQUEST`, `MODEL_UNAVAILABLE` rendered with the message (no replay fallback); failed create never yields a task | P3b |
| 6 | Contract wizard | `site-views.js` `#/contract`, `site-engine.js` blank contract | Environment ∈ dev/prod, resource classes incl. `db_instance`, IAM; `maxBlast`; consent checkbox; 12-char hash | Backend `contract` fields: `allowed_resource_addresses/types`, `allowed_operations`, `allowed_regions`, `max_changed_resources`, `denies`, `expires_at`, `status`, `confirmed_contract_hash` | `POST /tasks` (draft), `POST /tasks/{id}/confirm` | Environment/class choices beyond Phase 1 scope are not supported: wizard must edit the backend contract, not the sample model; no endpoint listing supported operations | Draft vs sealed states from `contract.status`; immutable after confirm (409 shown); expiry countdown from `expires_at`; error surfaces raw 409 text | P3b |
| 7 | Plan Review | `#/plan-review`, `site-views.js`, sample plans A/B/C | Sample plans, pasted normalized JSON, plan picker | `runs[-1]`: `canonical`, `verdicts`, `plan_hash`, `policy_hash` | `POST /agent`→`/plan`→`/canonicalize`→`/evaluate` | Fixture `variant` picker only in replay mode; no progress events for long stages | Empty: "Pipeline incomplete" with next stage; loading: per-stage labels; stop at first failed stage; stale: re-read task after error/timeout | P3b |
| 8 | Resource changes + before/after diffs | `site-views.js` change rows | Sample change objects | `verdicts[].changes[{attribute,before,after}]`, `canonical[].action` | via task/run | none | Empty verdict list state; unknown values (`unknown:true`) rendered as "known after apply" | P3b |
| 9 | Cedar verdict explanations | rule/"why" text in `site-engine.js` (`rule-reason`) | Sample rule ids and reasons | `verdicts[].reason`, `determining_policies` | via run | No policy text/explanation endpoint (policy ids only) | Show backend `reason` verbatim; policy ids as chips; `EVALUATION_ERROR` shown as technical failure (distinct style/alert) | P3b (text), P4 for policy source |
| 10 | REVIEW resolution | approve/reject/explain buttons, `j/k/a/r/e` keys | Browser-side resolutions in sessionStorage | `run.resolutions`, per-address `REVIEW` verdicts | `POST /resolve` | Resolver identity not returned; reject semantics ("excluded from apply set") are design-only | Only REVIEW rows show controls; DENY / `EVALUATION_ERROR` have none; error toast on 409; resolutions cleared on new plan → refetch | P3b |
| 11 | Apply / gate | "Apply Changes" + gate panel | Simulated apply, gate computed in browser (`PB.gateText`) | `apply_result{status,reason,spawned}`, `stage` | `POST /apply` | Real apply disabled; gate has no pre-flight "explain" endpoint | Button labeled as a gate check ("Verify with server gate"); result is backend `BLOCKED` reason; never show "Applied" unless `apply_result.status=="APPLIED"` | P3b |
| 12 | Evidence explorer | `#/evidence` filters, search, detail, Copy/Download JSON | Session-only evidence records | Audit log entries `{id,timestamp,kind,data}` per task | `GET /tasks/{id}/audit` | No cross-task audit endpoint; no server-side filter/search; audit `data` includes absolute paths | Empty: "No audit yet"; error banner; client-side filter over fetched records; export = the fetched JSON, labeled as a client export | P3c |
| 13 | Shared status + navigation | `site-app.js` router, header, `sound-toggle`, sample notice | "SAMPLE DATA" notice; session metrics | Backend reachability, `cloud_apply:false` | `GET /health` | none | Status pill: connecting / online / offline; `cloud_apply:false` shown as "AWS apply disabled" | P3a |
| 14 | How It Works | `#/how-it-works` | Static copy | none | — | Copy must not claim unsupported capabilities | Static | P3a |
| 15 | About | `#/about` | Static copy/FAQ | none | — | Copy review vs Phase 1 limits | Static | P3a |
| 16 | Legal placeholders | `#/legal` | Static placeholder, sample-data notice | none | — | Legal text is placeholder; must stay labeled pre-launch | Static | P3a |
| 17 | Responsive + keyboard | `site_keyboard.py`, `g`+letters, `?`, `M`, `j/k/a/r/e`, cursor | none | none | — | Shortcuts must not fire while typing in inputs (already so); mutating shortcuts (`a`,`r`) must call `/resolve`, not local state | Keyboard help overlay; focus management on route change; coarse-pointer disables custom cursor | P3c |
| 18 | WebGL lifecycle | see section above | none | none | — | — | Context-loss fallback (new); pause when hidden | P3a |
| 19 | Existing functional console (`web/`) | `web/src/main.jsx` | none | full workflow | all | — | Kept working through Phase 3 as the behavior reference; retired only after PlanBound views reach parity with tests | P3b→P3c |

## What each sample-only concept becomes

| Design/sample concept | Live replacement |
|---|---|
| Sample A/B/C plans | Real saved plan from `/plan`; replay fixtures labeled as fixtures |
| Browser sample rules → verdicts | `run.verdicts` from Cedar |
| Contract "hash" (12 char) | `confirmed_contract_hash` |
| Pasted JSON plan | Removed (or offline explainer, no gate influence) |
| Simulated apply / "Applied (simulated)" | `apply_result` from `/apply` (currently `BLOCKED`) |
| Session evidence | Persistent `/audit` |
| Session metrics counters | Derived from `GET /tasks`, or removed |

## Backend gaps to close before or during Phase 3 (from api_contract.md)

Stable machine codes for stage errors and a real 404 for unknown tasks; a task summary endpoint without absolute paths / full stdout; supported-operations endpoint; policy explanation endpoint; resolver identity; cross-task audit query. Each must be backward-compatible and must not change Cedar semantics.

## Explicitly out of scope until requested

Expanding infrastructure-editing capabilities; enabling real AWS apply; deploying; authentication/multi-user.
