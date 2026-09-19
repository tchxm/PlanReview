import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { Caption, ErrorBlock, Heading, JsonView, Loading, Stepper, copyText } from "../ui";
import { useTask, useTasks } from "../state/tasks";
import { modeLabel, when } from "../lib/taskModel";

const DENY_KINDS = [
  ["production", "production resources"],
  ["networking", "networking changes"],
  ["public_access", "public access"],
];

/** Draft contract, exactly as the backend produced it. Confirmation seals it and returns the backend hash. */
export default function TaskContract() {
  const { id } = useParams();
  const { task, loading, error: loadError, reload } = useTask(id);
  const { upsert } = useTasks();
  const [max, setMax] = useState(1);
  const [denies, setDenies] = useState([]);
  const [consent, setConsent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (task?.contract) {
      setMax(task.contract.max_changed_resources);
      setDenies(task.contract.denies || []);
    }
  }, [task?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (loadError) return <section className="subview"><Heading title="Task not found." kicker="CONTRACT" back={["/workspace", "Workspace"]} /><ErrorBlock error={loadError} /><button className="site-button" onClick={reload}>Retry</button></section>;
  if (!task) return <section className="subview"><Heading title="Define the boundary." kicker="01 / DEFINE" back={["/workspace", "Workspace"]} />{loading && <Loading />}</section>;

  const c = task.contract, sealed = c.status === "confirmed", intent = task.intent;
  const step = sealed ? 3 : consent ? 2 : 1;

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      upsert(await api.confirm(task.id, { ...c, max_changed_resources: Number(max), denies }));
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const toggle = (k) => setDenies((d) => (d.includes(k) ? d.filter((x) => x !== k) : [...d, k]));
  const shown = sealed ? c : { ...c, max_changed_resources: Number(max), denies };

  return (
    <section className="subview">
      <Heading title="Define the boundary." kicker="01 / DEFINE" back={["/workspace", "Workspace"]} lede="This contract came from the backend. Confirm it to make it immutable; the agent cannot change the boundary afterwards." />
      <Stepper current={step} labels={["Define", "Confirm", "Submit"]} />
      <div className="wizard-grid">
        <div className="wizard-panel">
          <Caption>{modeLabel(task.mode)}</Caption>
          <p className="contract-summary">“{c.task}”</p>
          {intent ? (
            <div className="site-panel">
              <Caption>INTERPRETED INTENT / {intent.status}</Caption>
              <p className="rule-reason"><b>{intent.operation}</b> on <code>{intent.resource_address}</code>, attribute <code>{intent.attribute}</code>, requested value <code>{JSON.stringify(intent.requested_value)}</code>.</p>
              <p className="rule-reason">{intent.reason}</p>
              {task.mode === "replay" && <p className="rule-reason">In fixture replay the Terraform edit is chosen by the fixture variant you pick in Plan Review, not by this sentence.</p>}
            </div>
          ) : null}
          <div className="site-panel">
            <Caption>PERMITTED SCOPE / IN PLAIN LANGUAGE</Caption>
            <p className="contract-summary">
              The agent may <b>{c.allowed_operations.join(", ")}</b> {c.allowed_resource_addresses.map((a) => <code key={a}>{a}</code>)} ({c.allowed_resource_types.join(", ")}) in {c.allowed_regions.join(", ")}, changing at most <b>{shown.max_changed_resources}</b> resource{shown.max_changed_resources === 1 ? "" : "s"}.
            </p>
            <p className="rule-reason">Explicitly forbidden: {shown.denies.length ? shown.denies.join(", ") : "nothing"}. Anything outside this scope is REVIEW or DENY. Expires {when(c.expires_at)}.</p>
          </div>
          {!sealed && (
            <>
              <div className="field">
                <label htmlFor="max">Maximum changed resources · <output>{max}</output></label>
                <input id="max" type="range" min="1" max="5" value={max} onChange={(e) => { setMax(e.target.value); setConsent(false); }} />
              </div>
              <fieldset className="field">
                <legend>Forbidden categories</legend>
                <div className="toggle-group">
                  {DENY_KINDS.map(([k, label]) => <button key={k} type="button" className={"chip " + (denies.includes(k) ? "selected" : "")} aria-pressed={denies.includes(k)} onClick={() => { toggle(k); setConsent(false); }}>{label}</button>)}
                </div>
                <p className="rule-reason">Removing a category does not authorize it: uncovered changes become REVIEW for a human, and Cedar still evaluates every change.</p>
              </fieldset>
              <label className="confirm-line">
                <input type="checkbox" id="consent" checked={consent} onChange={(e) => setConsent(e.target.checked)} />
                <span>I confirm this boundary describes what the agent is allowed to change.</span>
              </label>
              <ErrorBlock error={error} />
              <div className="site-actions">
                <button className="site-button primary" disabled={!consent || busy} onClick={confirm} data-cursor="NEXT">{busy ? "Confirming…" : "Submit confirmed boundary"}</button>
              </div>
            </>
          )}
          {sealed && (
            <>
              <div className="stamp">✓ BOUNDARY CONFIRMED / {task.confirmed_contract_hash}</div>
              <p className="contract-summary">Intent is now explicit and immutable.</p>
              <p className="rule-reason">Hash computed by the backend. Editing requires a new task.</p>
              <div className="site-actions">
                <button className="site-button" onClick={() => copyText(JSON.stringify(c, null, 2))}>Copy JSON</button>
                <Link className="site-button primary" to={`/task/${task.id}/plan`} data-cursor="NEXT">Review the plan →</Link>
              </div>
            </>
          )}
        </div>
        <aside className="wizard-side">
          <Caption>{sealed ? "CONFIRMED RECORD" : "DRAFT CONTRACT (BACKEND)"}</Caption>
          <p className="hash-line">{sealed ? "contract: " + task.confirmed_contract_hash : "draft · not yet hashed by the backend"}</p>
          <JsonView data={shown} />
        </aside>
      </div>
    </section>
  );
}
