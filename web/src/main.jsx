import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import {
  Shield,
  ArrowUpRight,
  ArrowRight,
  Plus,
  Lock,
  FileCode2,
  Activity,
  History,
  Check,
  ChevronRight,
  Terminal,
  Layers,
  RefreshCw,
  OctagonX,
  Copy,
  ExternalLink,
} from "lucide-react";
import "./styles.css";

const steps = [
  "Create task",
  "Confirm contract",
  "Plan review",
  "Resolution",
  "Audit",
];
const icons = [Plus, Lock, Layers, Check, History];
const short = (v) =>
  v === null ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v);
async function api(path, body) {
  const r = await fetch("/api" + path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await r.json();
  if (!r.ok) throw Error(data.detail || "Request failed");
  return data;
}
function Badge({ value }) {
  return (
    <span className={"badge " + value.toLowerCase()}>
      <span />
      {value}
    </span>
  );
}
function App() {
  const [tasks, setTasks] = useState([]),
    [task, setTask] = useState(null),
    [screen, setScreen] = useState(0),
    [busy, setBusy] = useState(""),
    [error, setError] = useState(""),
    [text, setText] = useState(
      "Increase memory for dev-api Lambda. Do not change networking or production.",
    ),
    [mode, setMode] = useState("replay"),
    [editor, setEditor] = useState(""),
    [audit, setAudit] = useState([]),
    [decisions, setDecisions] = useState({});
  const run = task?.runs.at(-1),
    verdicts = run?.verdicts || [],
    counts = ["ALLOW", "REVIEW", "DENY"].map(
      (v) => verdicts.filter((x) => x.verdict === v).length,
    );
  const unresolved = verdicts.filter(
    (v) => v.verdict === "REVIEW" && run.resolutions?.[v.address] !== "approve",
  ).length;
  const expired = task && new Date(task.contract.expires_at) <= new Date();
  const blocked = expired
    ? "Contract expired"
    : counts[2]
      ? `${counts[2]} explicit ${counts[2] === 1 ? "DENY" : "DENYs"} must be removed from the plan`
      : unresolved
        ? `${unresolved} REVIEW ${unresolved === 1 ? "requires" : "require"} a decision`
        : "AWS apply is disabled in this local environment";
  const update = (t) => {
    setTask(t);
    setTasks((ts) => [t, ...ts.filter((x) => x.id !== t.id)]);
    return t;
  };
  async function work(label, fn) {
    setBusy(label);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy("");
    }
  }
  useEffect(() => {
    api("/tasks")
      .then((ts) => {
        setTasks(ts);
        if (ts[0]) {
          setTask(ts[0]);
          setScreen(
            ts[0].runs.at(-1)?.verdicts
              ? 2
              : ts[0].contract.status === "draft"
                ? 1
                : 2,
          );
          setEditor(JSON.stringify(ts[0].contract, null, 2));
        }
      })
      .catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    if (screen === 4 && task)
      api(`/tasks/${task.id}/audit`)
        .then(setAudit)
        .catch((e) => setError(e.message));
  }, [screen, task]);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "instant" });
  }, [screen]);
  const go = (i) => {
    setScreen(i);
    if (i === 1 && task) setEditor(JSON.stringify(task.contract, null, 2));
  };
  async function generate() {
    await work("Drafting contract", async () => {
      let t = update(await api("/tasks", { task: text, mode }));
      setEditor(JSON.stringify(t.contract, null, 2));
      setScreen(1);
    });
  }
  async function evaluate(variant = "poisoned") {
    await work("Preparing Terraform edits", async () => {
      let id = task.id;
      update(await api(`/tasks/${id}/agent?variant=${variant}`, {}));
      setBusy("Running Terraform plan");
      update(await api(`/tasks/${id}/plan`, {}));
      setBusy("Canonicalizing changes");
      update(await api(`/tasks/${id}/canonicalize`, {}));
      setBusy("Evaluating Cedar policies");
      update(await api(`/tasks/${id}/evaluate`, {}));
      setScreen(2);
      setDecisions({});
    });
  }
  const select = (t) => {
    setTask(t);
    setDecisions({});
    setEditor(JSON.stringify(t.contract, null, 2));
    setScreen(t.contract.status === "draft" ? 1 : 2);
  };
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="/">
          <span className="brand-icon">
            <Shield size={22} />
          </span>
          PlanReview<span className="version">/ 01</span>
        </a>
        <div className="workspace">
          <span className="workspace-avatar">P</span>
          <div>
            Local workspace<small>Development environment</small>
          </div>
          <ChevronRight size={15} />
        </div>
        <div className="nav-label">CHANGE AUTHORITY</div>
        <nav>
          {steps.map((s, i) => {
            const Icon = icons[i];
            return (
              <button
                key={s}
                onClick={() => go(i)}
                className={screen === i ? "active" : ""}
              >
                <Icon size={18} />
                {s}
                <span className="nav-index">0{i + 1}</span>
              </button>
            );
          })}
        </nav>
        <div className="task-heading">
          <span className="nav-label">RECENT TASKS</span>
          <button aria-label="Create new task" onClick={() => go(0)}>
            <Plus size={16} />
          </button>
        </div>
        <div className="recent">
          {tasks.slice(0, 7).map((t) => (
            <button
              key={t.id}
              onClick={() => select(t)}
              className={task?.id === t.id ? "selected" : ""}
            >
              <FileCode2 size={16} />
              <span>{t.contract.task}</span>
            </button>
          ))}
          {!tasks.length && <p>No tasks yet.</p>}
        </div>
        <div className="sidebar-bottom">
          <div>
            <span className="neutral-dot" />
            LOCAL ENGINE<span className="mono">v0.1</span>
          </div>
          <p>Cedar policies. Human authority.</p>
          <a href="/docs" target="_blank" rel="noreferrer">
            API reference <ArrowUpRight size={14} />
          </a>
        </div>
      </aside>
      <main>
        <header className="topbar">
          <div className="breadcrumb">
            Workspace <ChevronRight size={13} /> {steps[screen]}
          </div>
          <div className="engine-tag">
            <span className="neutral-dot" />
            CEDAR ENGINE <span className="divider">/</span> LOCAL
          </div>
        </header>
        <div className="content">
          <div className="page-heading">
            <div>
              <div className="eyebrow">
                SECURITY CHECKPOINT <span>/ 0{screen + 1}</span>
              </div>
              <h1>
                {screen === 0
                  ? "Intent becomes a boundary."
                  : screen === 1
                    ? "Define the authority."
                    : screen === 2
                      ? "Every change. Accounted for."
                      : screen === 3
                        ? "Your decision, on record."
                        : "Nothing lost in the handoff."}
              </h1>
              <p>
                {
                  [
                    "Describe the work. Review the contract before any plan is evaluated.",
                    "A confirmed contract becomes immutable for this task.",
                    "Compare what was requested with what Terraform will actually change.",
                    "Resolve the exceptions. Explicit policy denials cannot be approved.",
                    "A persistent record of intent, evidence, decisions, and execution.",
                  ][screen]
                }
              </p>
            </div>
            {screen !== 0 && (
              <button className="button subtle" onClick={() => go(0)}>
                <Plus size={16} /> New task
              </button>
            )}
          </div>
          {error && (
            <div role="alert" className="notice">
              <OctagonX size={18} />
              <span>{error}</span>
              <button onClick={() => setError("")}>Dismiss</button>
            </div>
          )}
          {busy && (
            <div role="status" className="notice">
              <RefreshCw className="spin" size={16} />
              {busy}…
            </div>
          )}
          {screen === 0 && (
            <section className="create-layout">
              <div className="panel">
                <div className="panel-heading">
                  <span className="section-number">01</span>
                  <h2>The task</h2>
                  <span className="muted mono">NATURAL LANGUAGE</span>
                </div>
                <label htmlFor="task-input">
                  What should the agent change?
                </label>
                <textarea
                  id="task-input"
                  className="task-input"
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  maxLength={4000}
                />
                <div className="input-foot">
                  <span>Be specific about scope and exclusions.</span>
                  <span>{text.length} / 4000</span>
                </div>
                <label htmlFor="mode">Execution source</label>
                <select
                  id="mode"
                  value={mode}
                  onChange={(e) => setMode(e.target.value)}
                >
                  <option value="replay">Local fixture replay</option>
                  <option value="ollama">Live Strands / Ollama</option>
                </select>
                <p className="help">
                  {mode === "replay"
                    ? "Uses real Terraform plans from reproducible fixture edits. Contract drafting uses a local template; no LLM is invoked."
                    : "Runs a local Ollama model. The agent can edit Terraform but cannot authorize changes."}
                </p>
                <button
                  className="button primary"
                  disabled={!!busy || !text.trim()}
                  onClick={generate}
                >
                  Generate contract <ArrowRight size={17} />
                </button>
              </div>
              <div className="principle">
                <div className="orbit">
                  <Shield size={46} />
                </div>
                <div className="eyebrow">INTENT IS NOT PERMISSION</div>
                <h2>
                  Give the agent a task.
                  <br />
                  Keep the authority.
                </h2>
                <p>
                  PlanReview inspects the plan before infrastructure changes.
                  Every resource receives an independent, policy-backed verdict.
                </p>
                <div className="legend">
                  <Badge value="ALLOW" />
                  <span>Inside the confirmed boundary</span>
                  <Badge value="REVIEW" />
                  <span>Needs a human decision</span>
                  <Badge value="DENY" />
                  <span>Explicitly prohibited</span>
                </div>
              </div>
            </section>
          )}
          {screen !== 0 && !task && (
            <div className="empty panel">
              <Layers size={32} />
              <h2>Pipeline incomplete</h2>
              <p>Create a task to start a review.</p>
              <button className="button primary" onClick={() => go(0)}>
                Create task <ArrowRight size={16} />
              </button>
            </div>
          )}
          {screen === 1 && task && (
            <div className="contract-layout">
              <section
                className={
                  "panel " +
                  (task.contract.status === "confirmed" ? "sealed" : "")
                }
              >
                <div className="panel-heading">
                  <Lock size={18} />
                  <h2>Authority contract</h2>
                  <span className="mono muted">
                    {task.contract.status.toUpperCase()} · V
                    {task.contract.version}
                  </span>
                </div>
                <p className="help">
                  Concrete deny categories: production, networking,
                  public_access. Removing networking permits REVIEW for
                  uncovered network changes; it does not authorize them.
                </p>
                <label htmlFor="contract">Contract JSON</label>
                <textarea
                  id="contract"
                  className="code-editor"
                  value={editor}
                  readOnly={task.contract.status === "confirmed"}
                  onChange={(e) => setEditor(e.target.value)}
                  spellCheck="false"
                />
                <div className="panel-footer">
                  {task.contract.status === "draft" ? (
                    <button
                      className="button primary"
                      disabled={!!busy}
                      onClick={() =>
                        work("Confirming", async () => {
                          update(
                            await api(
                              `/tasks/${task.id}/confirm`,
                              JSON.parse(editor),
                            ),
                          );
                          setEditor(
                            JSON.stringify(
                              { ...JSON.parse(editor), status: "confirmed" },
                              null,
                              2,
                            ),
                          );
                        })
                      }
                    >
                      <Lock size={16} /> CONFIRM contract
                    </button>
                  ) : (
                    <>
                      <span className="mono">
                        <Lock size={14} /> Sealed · read only
                      </span>
                      <button className="button primary" onClick={() => go(2)}>
                        Continue to plan review <ArrowRight size={16} />
                      </button>
                    </>
                  )}
                </div>
              </section>
              <aside className="panel contract-note">
                <span className="eyebrow">CONFIRMATION MATTERS</span>
                <h2>A contract is a boundary.</h2>
                <p>
                  Review allowed addresses, operations, region, resource limit,
                  and expiry. The agent cannot renegotiate them.
                </p>
                <hr />
                <p>
                  Default contracts explicitly forbid networking. The
                  three-color demo requires a different confirmed scope with
                  networking sent to review and a resource limit of three.
                </p>
                <button
                  className="button subtle"
                  disabled={!!busy || task.contract.status !== "draft"}
                  onClick={() => {
                    const c = JSON.parse(editor);
                    c.denies = ["production", "public_access"];
                    c.max_changed_resources = 3;
                    setEditor(JSON.stringify(c, null, 2));
                  }}
                >
                  Use three-color demo scope <ArrowUpRight size={16} />
                </button>
              </aside>
            </div>
          )}
          {screen === 2 && task && (
            <>
              <div className="task-strip">
                <FileCode2 size={20} />
                <div>
                  <span className="eyebrow">ACTIVE TASK</span>
                  <h2>{task.contract.task}</h2>
                </div>
                <span className="source-chip">
                  {task.mode === "replay" ? "FIXTURE REPLAY" : "LIVE AGENT"}
                </span>
              </div>
              <div className="review-summary">
                <div className="summary-total">
                  <span className="eyebrow">PLAN OVERVIEW</span>
                  <div>
                    <strong>
                      {verdicts.length.toString().padStart(2, "0")}
                    </strong>
                    <span>resource changes</span>
                  </div>
                </div>
                {["ALLOW", "REVIEW", "DENY"].map((v, i) => (
                  <div className="summary-verdict" key={v}>
                    <Badge value={v} />
                    <strong>{counts[i].toString().padStart(2, "0")}</strong>
                    <p>
                      {
                        [
                          "Within contract scope",
                          "Human decision required",
                          "Policy prohibits change",
                        ][i]
                      }
                    </p>
                  </div>
                ))}
              </div>
              <div className="review-toolbar">
                <div>
                  <h2>
                    Resource changes{" "}
                    <span className="count">{verdicts.length}</span>
                  </h2>
                  <span className="mono muted">
                    {run
                      ? `RUN ${run.id.slice(0, 8)} · ${new Date(run.created_at).toLocaleTimeString()}`
                      : "AWAITING PLAN"}
                  </span>
                </div>
                <button
                  className="button subtle"
                  disabled={!!busy || task.contract.status !== "confirmed"}
                  onClick={() => evaluate()}
                >
                  <RefreshCw size={16} />
                  {run ? "Re-run poisoned fixture" : "Run & evaluate plan"}
                </button>
              </div>
              {!run?.verdicts ? (
                <div className="empty panel">
                  <Terminal size={30} />
                  <h2>Pipeline incomplete</h2>
                  <p>
                    {task.contract.status === "draft"
                      ? "Confirm the contract before running Terraform."
                      : "Run the plan to inspect real resource changes."}
                  </p>
                </div>
              ) : (
                <div className="verdict-list">
                  {verdicts.map((v, i) => (
                    <article
                      key={run.id + v.address}
                      className={"verdict-row " + v.verdict.toLowerCase()}
                      style={{ "--delay": `${i * 40}ms` }}
                    >
                      <div className="resource-top">
                        <div className="resource-label">
                          <span className="row-number">0{i + 1}</span>
                          <FileCode2 size={17} />
                          <code>{v.address}</code>
                        </div>
                        <div className="resource-tags">
                          <span className="operation">
                            {
                              run.canonical.find((c) => c.address === v.address)
                                ?.action
                            }
                          </span>
                          <Badge value={v.verdict} />
                        </div>
                      </div>
                      <div className="diffs">
                        {v.changes.map((d, j) => (
                          <div className="diff" key={j}>
                            <code className="attribute">{d.attribute}</code>
                            <code className="before">{short(d.before)}</code>
                            <ArrowRight size={15} />
                            <code className="after">{short(d.after)}</code>
                          </div>
                        ))}
                      </div>
                      <div className="reason">
                        <span className="reason-dot" />
                        {v.reason}
                        {run.resolutions?.[v.address] && (
                          <span className="resolution-chip">
                            Human: {run.resolutions[v.address]}
                          </span>
                        )}
                      </div>
                    </article>
                  ))}
                </div>
              )}
              <div className="apply-panel">
                <div>
                  <div className="apply-title">
                    <Lock size={18} />
                    <h2>Execution gate</h2>
                    <span className="mono muted">SERVER ENFORCED</span>
                  </div>
                  <p>{blocked}</p>
                  {run?.apply_result && (
                    <p className="mono">
                      Last attempt: {run.apply_result.status} ·{" "}
                      {run.apply_result.reason}
                    </p>
                  )}
                </div>
                <div className="apply-actions">
                  <button
                    className="button subtle"
                    disabled={!verdicts.length || !!busy}
                    onClick={() => go(3)}
                  >
                    Resolve changes <ArrowUpRight size={15} />
                  </button>
                  <button
                    className="button refused"
                    disabled
                    aria-label={"Apply blocked: " + blocked}
                  >
                    <OctagonX size={17} /> Apply blocked
                  </button>
                  <button
                    className="text-button"
                    disabled={!verdicts.length || !!busy}
                    onClick={() =>
                      work("Checking server gate", async () =>
                        update(await api(`/tasks/${task.id}/apply`, {})),
                      )
                    }
                  >
                    Verify block via API
                  </button>
                </div>
              </div>
            </>
          )}
          {screen === 3 && task && (
            <>
              <div className="panel">
                <div className="panel-heading">
                  <Check size={18} />
                  <h2>Review decisions</h2>
                  <span className="mono muted">BOUND TO THIS PLAN</span>
                </div>
                {verdicts
                  .filter((v) => v.verdict === "REVIEW")
                  .map((v) => (
                    <div className="resolution-row" key={v.address}>
                      <div>
                        <code>{v.address}</code>
                        <p>{v.reason}</p>
                      </div>
                      <select
                        aria-label={"Decision for " + v.address}
                        value={
                          decisions[v.address] ||
                          run.resolutions?.[v.address] ||
                          ""
                        }
                        onChange={(e) =>
                          setDecisions({
                            ...decisions,
                            [v.address]: e.target.value,
                          })
                        }
                      >
                        <option value="">Choose a decision</option>
                        <option value="approve">Approve</option>
                        <option value="reject">Reject</option>
                      </select>
                    </div>
                  ))}
                {!counts[1] && (
                  <div className="empty">
                    <p>No REVIEW items in this run.</p>
                  </div>
                )}
                <div className="panel-footer">
                  <span className="help">
                    Approval applies only to this exact saved plan.
                  </span>
                  <button
                    className="button primary"
                    disabled={!!busy || !Object.keys(decisions).length}
                    onClick={() =>
                      work("Recording decisions", async () => {
                        update(
                          await api(`/tasks/${task.id}/resolve`, decisions),
                        );
                        setDecisions({});
                      })
                    }
                  >
                    Record decisions <Check size={17} />
                  </button>
                </div>
              </div>
              <div className="panel deny-remediation">
                <div>
                  <h2>Remove prohibited changes</h2>
                  <p>
                    DENY cannot be approved. Revert the offending edits, then
                    generate a fresh plan. Previous resolutions do not carry
                    forward.
                  </p>
                </div>
                <button
                  className="button subtle"
                  disabled={!!busy || task.contract.status !== "confirmed"}
                  onClick={() => evaluate("review")}
                >
                  Re-plan without S3 change <RefreshCw size={16} />
                </button>
                <button
                  className="button subtle"
                  disabled={!!busy || task.contract.status !== "confirmed"}
                  onClick={() => evaluate("intended")}
                >
                  Re-plan Lambda only <RefreshCw size={16} />
                </button>
              </div>
            </>
          )}
          {screen === 4 && task && (
            <>
              <div className="audit-heading">
                <div>
                  <span className="eyebrow">PERSISTED EVIDENCE</span>
                  <p>
                    {audit.length} events · Task{" "}
                    <code>{task.id.slice(0, 8)}</code>
                  </p>
                </div>
                <button
                  className="button subtle"
                  onClick={() => {
                    const a = document.createElement("a");
                    const url = URL.createObjectURL(
                      new Blob([JSON.stringify(audit, null, 2)], {
                        type: "application/json",
                      }),
                    );
                    a.href = url;
                    a.download = `planreview-${task.id}.json`;
                    a.click();
                    URL.revokeObjectURL(url);
                  }}
                >
                  Export audit <ArrowUpRight size={16} />
                </button>
              </div>
              <div className="timeline">
                {audit.map((e, i) => (
                  <article className="audit-event" key={e.id}>
                    <div className="timeline-marker">
                      {String(i + 1).padStart(2, "0")}
                    </div>
                    <div className="panel">
                      <div className="audit-title">
                        <h2>{e.kind.replaceAll("_", " ")}</h2>
                        <time className="mono muted">
                          {new Date(e.timestamp).toLocaleString()}
                        </time>
                      </div>
                      <details>
                        <summary>Inspect stored record</summary>
                        <pre>{JSON.stringify(e.data, null, 2)}</pre>
                      </details>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
          <footer>
            <span>
              <Shield size={13} /> The plan is evidence. The contract is
              authority.
            </span>
            <span className="mono">PLANREVIEW / LOCAL-FIRST</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
createRoot(document.getElementById("root")).render(<App />);
