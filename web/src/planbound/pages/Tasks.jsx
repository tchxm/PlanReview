import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../../api";
import { Caption, ErrorBlock, Heading, Loading, BackendOffline } from "../ui";
import { useTasks } from "../state/tasks";
import { modeLabel, statusChip, when, shortHash, taskFacts } from "../lib/taskModel";

export function Workspace() {
  const { tasks, loaded, error, backend, refresh } = useTasks();
  return (
    <section className="subview">
      <Heading title="Your tasks." kicker="WORKSPACE" lede="Every task below was saved by the PlanReview backend. Open one to continue where it left off, or start a new one." />
      <div className="site-actions" style={{ marginBottom: 28 }}>
        <Link className="site-button primary" to="/new" data-cursor="NEXT">New task →</Link>
        <button className="site-button" onClick={refresh}>Refresh</button>
      </div>
      {backend === "offline" && <BackendOffline error={error} onRetry={refresh} />}
      {!loaded && <Loading />}
      {loaded && backend !== "offline" && !tasks.length && (
        <div className="empty-state"><h2>No saved tasks yet.</h2><p className="rule-reason">Describe a supported change to create the first one.</p><Link className="site-button primary" to="/new">Create a task</Link></div>
      )}
      <div className="evidence-grid">
        {tasks.map((t, i) => {
          const chip = statusChip(t);
          const f = taskFacts(t);
          const to = t.contract?.status === "draft" ? `/task/${t.id}/contract` : `/task/${t.id}/plan`;
          return (
            <article className="evidence-tile" key={t.id}>
              <Caption>{`#${String(tasks.length - i).padStart(4, "0")} / ${modeLabel(t.mode)}`}</Caption>
              <h3 style={{ fontSize: 22 }}>{t.contract?.task?.slice(0, 70) || t.id}</h3>
              <span className={"badge " + chip.tone}>{chip.label}</span>
              <div className="evidence-meta">
                {t.intent ? `${t.intent.operation} · ${t.intent.resource_address}` : "no interpreted intent"}<br />
                contract: {t.confirmed_contract_hash ? shortHash(t.confirmed_contract_hash, 12) : "draft"}<br />
                {f.evaluated ? `${f.verdicts.length} change${f.verdicts.length === 1 ? "" : "s"} evaluated` : "not planned yet"} · {when(t.created_at)}
              </div>
              <Link className="site-button" to={to} data-cursor="INSPECT">Open ↗</Link>
            </article>
          );
        })}
      </div>
    </section>
  );
}

const EXAMPLES = ["Increase memory for dev-api Lambda", "Set dev-api Lambda memory to 700", "Set the Team tag on the assets bucket to platform"];

export function NewTask() {
  const nav = useNavigate();
  const { upsert, backend } = useTasks();
  const [text, setText] = useState(EXAMPLES[0]);
  const [mode, setMode] = useState("replay");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      const t = await api.createTask(text, mode);
      upsert(t);
      nav(`/task/${t.id}/contract`);
    } catch (e) {
      // Honest error: a failed model interpretation is shown as-is, never replaced by replay.
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="subview">
      <Heading title="State the task." kicker="01 / DEFINE" back={["/workspace", "Workspace"]} lede="A human request is interpreted by the backend and checked against a deterministic capability registry before a draft contract exists." />
      <div className="wizard-grid">
        <div className="wizard-panel">
          <div className="field">
            <label htmlFor="task-text">What should change?</label>
            <textarea id="task-text" className="site-input" rows={3} maxLength={4000} value={text} onChange={(e) => setText(e.target.value)} />
            <small>{text.length} / 4000</small>
            <div className="toggle-group" style={{ marginTop: 10 }}>
              {EXAMPLES.map((x) => <button key={x} type="button" className="chip" onClick={() => setText(x)}>{x}</button>)}
            </div>
          </div>
          <fieldset className="field">
            <legend>Execution mode</legend>
            <div className="toggle-group">
              <button type="button" className={"chip " + (mode === "replay" ? "selected" : "")} aria-pressed={mode === "replay"} onClick={() => setMode("replay")}>Fixture replay</button>
              <button type="button" className={"chip " + (mode === "ollama" ? "selected" : "")} aria-pressed={mode === "ollama"} onClick={() => setMode("ollama")}>Live local model (Ollama)</button>
            </div>
            <p className="rule-reason">
              {mode === "replay"
                ? "FIXTURE REPLAY: contract drafting uses a local template and the Terraform edit comes from a reproducible fixture. No language model is invoked."
                : "LIVE LOCAL MODEL: a local Ollama model interprets the request and edits Terraform through Strands. If the model is unavailable or its answer fails validation you get an error. The system never switches to replay on its own."}
            </p>
          </fieldset>
          <ErrorBlock error={error} hint={error?.code === "UNSUPPORTED_OPERATION" ? "Only the two supported operations can be edited: dev-api Lambda memory and the assets bucket's Team tag." : undefined} />
          <div className="site-actions">
            <button className="site-button primary" onClick={submit} disabled={busy || !text.trim() || backend === "offline"} data-cursor="NEXT">{busy ? "Interpreting…" : "Draft contract →"}</button>
          </div>
          {backend === "offline" && <BackendOffline />}
        </div>
        <aside className="wizard-side">
          <Caption>SUPPORTED SCOPE</Caption>
          <p className="contract-summary">PlanReview is not a general AWS editor.</p>
          <p className="rule-reason"><b>update_memory</b> · <code>aws_lambda_function.dev_api</code> · <code>memory_size</code>, 128–10240 MB.</p>
          <p className="rule-reason"><b>update_tags</b> · <code>aws_s3_bucket.assets</code> · the <code>Team</code> tag only.</p>
          <p className="rule-reason">IAM, RDS, security groups, networking and deletions are refused with <code>UNSUPPORTED_OPERATION</code>. Real AWS apply is disabled.</p>
        </aside>
      </div>
    </section>
  );
}
