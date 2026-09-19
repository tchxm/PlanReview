import { useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { Caption, ErrorBlock, Heading, JsonView, Loading, Stepper, VerdictBadge, setRobotStatus } from "../ui";
import { useTask, useTasks } from "../state/tasks";
import { fmt, isLive, modeLabel, shortHash, taskFacts, when } from "../lib/taskModel";

const VARIANTS = [
  ["intended", "Intended edit only"],
  ["poisoned", "Intended edit plus unrequested edits (shows REVIEW and DENY)"],
  ["review", "Review fixture"],
  ["baseline", "Baseline (no edit)"],
  ["adversarial", "Adversarial fixture"],
];
const RES_CLASS = { approve: "approved", reject: "rejected" };

/** Row for one REAL resource change with its backend verdict. */
function Row({ v, index, canonical, resolution, onResolve, busy }) {
  const [open, setOpen] = useState(false);
  const fault = v.verdict === "EVALUATION_ERROR";
  return (
    <article className={"review-row" + (resolution ? " resolved-" + RES_CLASS[resolution] : "")} tabIndex={0} data-change-id={v.address}>
      <div className="row-heading">
        <div>
          <div className="row-number">{`#${String(index + 1).padStart(2, "0")} / ${(canonical?.action || "change").toUpperCase()}`}</div>
          <div className="resource-name">{v.address}</div>
          <div className="rule-reason">{canonical?.resource_type}{canonical?.region ? ` · ${canonical.region}` : ""}</div>
        </div>
        <VerdictBadge type={v.verdict} />
      </div>
      <div className="diff">
        <Caption>PROPOSED CHANGE</Caption>
        <pre>
          {v.changes.map((c, i) => (
            <span key={i}>
              <span className="line-del">{`- ${c.attribute} = ${fmt(c.before)}`}</span>
              <span className="line-add">{`+ ${c.attribute} = ${fmt(c.after)}`}</span>
            </span>
          ))}
        </pre>
      </div>
      <p className="rule-id">{(v.determining_policies || []).length ? "cedar: " + v.determining_policies.join(" · ") : "cedar: no determining policy reported"}</p>
      <p className="rule-reason">{v.reason}</p>
      {fault && <div className="site-error" role="alert"><strong>× Technical failure</strong><p>Cedar could not evaluate this change. It cannot be approved. Fix the cause and run a new plan.</p></div>}
      <div className="row-actions">
        {v.verdict === "REVIEW" && (
          <>
            <button className="site-button" aria-pressed={resolution === "approve"} disabled={busy} data-action="approve" onClick={() => onResolve(v.address, "approve")}>{resolution === "approve" ? "Approved" : "Approve"}</button>
            <button className="site-button" aria-pressed={resolution === "reject"} disabled={busy} data-action="reject" onClick={() => onResolve(v.address, "reject")}>{resolution === "reject" ? "Rejected" : "Reject"}</button>
          </>
        )}
        {v.verdict === "DENY" && <span className="locked">Locked by boundary</span>}
        {fault && <span className="locked">Not approvable</span>}
        <button className="site-button" data-cursor="INSPECT" data-action="explain" onClick={() => setOpen((x) => !x)}>{v.verdict === "ALLOW" ? "View" : "Explain"}</button>
      </div>
      {open && (
        <div className="explain-drawer">
          <Caption>BACKEND RECORD / {v.verdict}</Caption>
          <p className="rule-reason">{v.reason}</p>
          <JsonView data={{ verdict: v, canonical }} />
        </div>
      )}
    </article>
  );
}

export default function TaskPlan() {
  const { id } = useParams();
  const { task, loading, error: loadError, reload } = useTask(id);
  const { upsert, backend } = useTasks();
  const [variant, setVariant] = useState("intended");
  const [busy, setBusy] = useState(null); // {kind,label}
  const [progress, setProgress] = useState([]);
  const [error, setError] = useState(null);
  const center = useRef(null);

  // j/k move between rows, a/r/e act on the focused row (original keyboard model)
  useEffect(() => {
    const onKey = (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test(e.target.tagName)) return;
      const rows = Array.from(center.current?.querySelectorAll("[data-change-id]") || []);
      let n = rows.indexOf(document.activeElement?.closest("[data-change-id]"));
      if (e.key === "j" || e.key === "k") { e.preventDefault(); n = Math.max(0, Math.min(rows.length - 1, n + (e.key === "j" ? 1 : -1))); rows[n]?.focus(); }
      else if (n >= 0) { const action = { a: "approve", r: "reject", e: "explain" }[e.key]; if (action) { e.preventDefault(); rows[n].querySelector(`[data-action=${action}]`)?.click(); } }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // The reviewer's screen mirrors backend facts and client activity. It never states a verdict of its own.
  const rf = task ? taskFacts(task) : null;
  const robotText = !task ? null : error || rf.hasFault ? "TECH FAULT" : busy && busy.kind === "agent" ? "PREPARING" : busy ? "INSPECTING" : rf.evaluated && !rf.counts.DENY && rf.awaiting.length ? "HUMAN NEEDED" : null;
  useEffect(() => {
    setRobotStatus(robotText, robotText === "TECH FAULT" ? "#ff4fa0" : robotText === "HUMAN NEEDED" ? "#f1c34f" : "#dfe6c9");
    return () => setRobotStatus(null);
  }, [robotText]);

  if (loadError) return <section className="subview"><Heading title="Task not found." kicker="PLAN REVIEW" back={["/workspace", "Workspace"]} /><ErrorBlock error={loadError} /><button className="site-button" onClick={reload}>Retry</button></section>;
  if (!task) return <section className="subview"><Heading title="Every change. A decision." kicker="02 / INSPECT" back={["/workspace", "Workspace"]} />{loading && <Loading />}</section>;

  const f = taskFacts(task);
  const live = isLive(task);
  const startAt = { edited: 1, planned: 2, canonicalized: 3 }[task.stage] ?? 0;
  const STAGES = [
    ["agent", live ? "Local model editing Terraform" : "Applying the fixture edit", () => api.runAgent(task.id, live ? "intended" : variant)],
    ["plan", "Running terraform plan", () => api.plan(task.id)],
    ["canonicalize", "Canonicalizing changes", () => api.canonicalize(task.id)],
    ["evaluate", "Evaluating with Cedar", () => api.evaluate(task.id)],
  ];

  async function runPipeline() {
    setError(null);
    setProgress([]);
    for (let i = startAt; i < STAGES.length; i++) {
      const [kind, label, call] = STAGES[i];
      setBusy({ kind, label });
      try {
        upsert(await call());
        setProgress((p) => [...p, [label, "done"]]);
      } catch (e) {
        setProgress((p) => [...p, [label, "failed"]]);
        setError({ stage: label, e });
        // A failed or timed-out request does not prove what the backend did: re-read the task.
        try { upsert(await api.getTask(task.id)); } catch { /* keep the last known state */ }
        break;
      }
    }
    setBusy(null);
  }

  async function resolve(address, choice) {
    setError(null);
    setBusy({ kind: "resolve", label: "Recording your decision" });
    try {
      upsert(await api.resolve(task.id, { ...f.resolutions, [address]: choice }));
    } catch (e) {
      setError({ stage: "Recording your decision", e });
    } finally {
      setBusy(null);
    }
  }

  async function askGate() {
    setError(null);
    setBusy({ kind: "apply", label: "Asking the backend gate" });
    try {
      upsert(await api.apply(task.id));
    } catch (e) {
      setError({ stage: "Backend gate", e });
    } finally {
      setBusy(null);
    }
  }

  const sealed = f && task.contract.status === "confirmed";
  const attention = f.counts.DENY + f.counts.EVALUATION_ERROR + f.awaiting.length;
  const status = !sealed ? 0 : !f.evaluated ? 1 : attention ? 2 : 3;
  const gateOpen = f.apply?.status === "APPLIED";
  const gateText = !f.evaluated
    ? "Run the plan so the backend can evaluate every change."
    : f.counts.EVALUATION_ERROR
      ? `${f.counts.EVALUATION_ERROR} technical evaluation ${f.counts.EVALUATION_ERROR === 1 ? "error" : "errors"}. Nothing here can be approved.`
      : attention
        ? `${attention} of ${f.verdicts.length} changes need attention before the gate can open.`
        : "No unresolved items. Ask the backend gate for its decision.";
  const hasRun = f.evaluated;

  return (
    <section className="subview">
      <Heading title="Every change. A decision." kicker="02 / INSPECT" back={["/workspace", "Workspace"]} lede="Real Terraform changes, Cedar verdicts and the backend's own gate. Approvals go to the backend; a button is never proof of authorization." />
      {!sealed && <div className="inline-banner">The contract is not confirmed yet, so the agent cannot run. <Link to={`/task/${task.id}/contract`}>Confirm it →</Link></div>}
      {sealed && f.expired && <div className="inline-banner">This contract has expired; the backend will refuse to plan.</div>}
      {backend === "offline" && <div className="inline-banner">Backend offline: showing the last known state.</div>}
      <div className="review-console">
        <aside className="review-left">
          <div className="site-panel">
            <Caption>CONTRACT / {modeLabel(task.mode)}</Caption>
            <h2 style={{ fontSize: 26 }}>{task.contract.status}</h2>
            <p className="hash-line">contract: {task.confirmed_contract_hash ? shortHash(task.confirmed_contract_hash, 16) : "unconfirmed"}</p>
            <p className="rule-reason">{task.contract.allowed_resource_addresses.join(", ")}</p>
            <p className="rule-reason">Max changed resources: {task.contract.max_changed_resources} · forbids {(task.contract.denies || []).join(", ") || "nothing"}</p>
            <Link className="site-button" to={`/task/${task.id}/contract`}>View →</Link>
          </div>
          <div className="site-panel">
            <Caption>RUN THE WORKFLOW</Caption>
            {!live && (
              <>
                <label htmlFor="variant">Fixture variant</label>
                <select id="variant" value={variant} onChange={(e) => setVariant(e.target.value)} disabled={!!busy || startAt > 0}>
                  {VARIANTS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
                <p className="rule-reason">FIXTURE REPLAY: the edit comes from this fixture, not from the task sentence.</p>
              </>
            )}
            {live && <p className="rule-reason">LIVE LOCAL MODEL: Strands and Ollama edit the baseline Terraform, constrained to the confirmed intent. Failures are reported, never replayed.</p>}
            <button className="site-button primary" disabled={!sealed || !!busy || f.expired || backend === "offline"} onClick={runPipeline} data-cursor="NEXT">
              {busy && busy.kind !== "resolve" && busy.kind !== "apply" ? busy.label + "…" : hasRun ? "Run a new plan →" : startAt ? "Resume workflow →" : "Run agent → plan → evaluate"}
            </button>
            {progress.length > 0 && <ul className="how-list" style={{ marginTop: 12 }}>{progress.map(([l, s], i) => <li key={i}>{s === "done" ? "✓" : "×"} {l}</li>)}</ul>}
            <p className="rule-reason">Long stages run in one request. If your browser stops waiting, the backend may still be working; the page re-reads the task.</p>
          </div>
        </aside>

        <section className="review-center" ref={center} aria-label="Plan changes">
          <Caption>{`${f.verdicts.length} CHANGES DETECTED / STATUS ${status} OF 3`}</Caption>
          <Stepper current={status} />
          {error && <ErrorBlock error={error.e} hint={`Stopped at: ${error.stage}. The workflow does not continue after a failure.`} />}
          {busy && <p className="rule-reason" role="status">{busy.label}…</p>}
          {!f.evaluated && !busy && <div className="empty-state"><h2>No plan yet.</h2><p className="rule-reason">{sealed ? "Run the workflow to create a real Terraform plan and evaluate it with Cedar." : "Confirm the contract first."}</p></div>}
          {f.verdicts.map((v, i) => (
            <Row key={f.run.id + v.address} v={v} index={i} canonical={f.run.canonical?.find((c) => c.address === v.address)} resolution={f.resolutions[v.address]} onResolve={resolve} busy={!!busy} />
          ))}
          {f.evaluated && <p className="sample-tag">Saved plan {shortHash(f.run.plan_hash, 16)} · policy {shortHash(f.run.policy_hash, 16)} · {when(f.run.created_at)}</p>}
        </section>

        <aside className="review-right">
          <div className="companion" data-robot-slot="" data-companion="true" data-cursor="LOOK" aria-label="Boundary reviewer (visual guide, not a judge)" onPointerDown={() => window.PB?.robot?.acknowledge()} />
          <div className={"site-panel gate-card" + (gateOpen ? " open" : "")}>
            <span className="gate-symbol" aria-hidden="true">{gateOpen ? "↗" : "⊣"}</span>
            <p className="gate-status">GATE: {gateOpen ? "OPEN" : "CLOSED"}</p>
            <h3>Backend gate</h3>
            <p>{f.apply ? f.apply.reason : gateText}</p>
            {f.apply && <p className="rule-id">result: {f.apply.status}</p>}
            <button className="site-button primary" disabled={!f.evaluated || !!busy} onClick={askGate} data-cursor="NEXT">Ask the backend gate</button>
            <div className="apply-set">{f.counts.ALLOW} ALLOW · {f.counts.REVIEW} REVIEW · {f.counts.DENY} DENY{f.counts.EVALUATION_ERROR ? ` · ${f.counts.EVALUATION_ERROR} ERROR` : ""}</div>
            <p className="sample-tag">Real AWS apply is disabled. This asks the backend which checks pass; nothing is deployed.</p>
            <Link className="site-button" to={`/task/${task.id}/evidence`}>Evidence →</Link>
          </div>
        </aside>
      </div>
    </section>
  );
}
