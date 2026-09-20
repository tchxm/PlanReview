import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api";
import { Caption, ErrorBlock, Heading, JsonView, Loading, Stepper, VerdictBadge, copyText } from "../ui";
import { SignalCanvas } from "./HomeBelow";
import { useTask } from "../state/tasks";
import { shortHash, taskFacts, when } from "../lib/taskModel";

const KIND_LABEL = {
  draft: "Draft contract", human_confirmation: "Human confirmation", agent_edits: "Agent edits", plan: "Terraform plan",
  canonical: "Canonical changes", verdicts: "Cedar verdicts", human_resolution: "Human resolution", apply_result: "Backend gate",
};

/** One-line factual summary of a persisted audit record (no interpretation). */
function summarize(e) {
  const d = e.data || {};
  switch (e.kind) {
    case "draft": return [d.contract?.task, `mode ${d.mode}`, d.intent ? `${d.intent.operation} → ${d.intent.resource_address}` : "no interpreted intent"];
    case "human_confirmation": return [`contract ${shortHash(d.confirmed_contract_hash, 16)}`, `status ${d.contract?.status}`];
    case "agent_edits": return [`variant ${d.variant ?? "—"}`, `mode ${d.mode}`];
    case "plan": return [`plan ${shortHash(d.plan_hash, 16)}`, `raw ${shortHash(d.raw_hash, 12)}`];
    case "canonical": return [`${(d.canonical || []).length} canonical change(s)`, `plan ${shortHash(d.plan_hash, 12)}`];
    case "verdicts": return [(d.verdicts || []).map((v) => `${v.verdict}`).join(" · ") || "no verdicts", `policy ${shortHash(d.policy_hash, 16)}`];
    case "human_resolution": return [Object.entries(d.resolutions || {}).map(([a, r]) => `${a.split(".").pop()}: ${r}`).join(" · ") || "no decisions"];
    case "apply_result": return [d.status, d.reason];
    default: return [];
  }
}
const verdictOf = (e) => (e.kind === "apply_result" ? e.data?.status : null);

export default function TaskEvidence() {
  const { id } = useParams();
  const { task, loading, error: loadError } = useTask(id);
  const [audit, setAudit] = useState(null);
  const [error, setError] = useState(null);
  const [filter, setFilter] = useState("ALL");
  const [selected, setSelected] = useState(null);

  const load = useCallback(async () => {
    setError(null);
    try { setAudit(await api.getAudit(id)); } catch (e) { setError(e); }
  }, [id]);
  useEffect(() => { load(); }, [load, task?.stage, task?.runs?.length]);

  const kinds = useMemo(() => ["ALL", ...Array.from(new Set((audit || []).map((e) => e.kind)))], [audit]);
  if (loadError) return <section className="subview"><Heading title="Task not found." kicker="EVIDENCE" back={["/workspace", "Workspace"]} /><ErrorBlock error={loadError} /></section>;
  if (!task) return <section className="subview"><Heading title="The record behind the view." kicker="EVIDENCE" back={["/workspace", "Workspace"]} />{loading && <Loading />}</section>;

  const f = taskFacts(task);
  const list = (audit || []).filter((e) => filter === "ALL" || e.kind === filter);
  const chosen = audit?.find((e) => e.id === selected);
  const chain = [
    ["01 INTENT", task.intent ? `${task.intent.operation} · ${task.intent.resource_address}` : "—"],
    ["02 CONTRACT", task.confirmed_contract_hash ? shortHash(task.confirmed_contract_hash, 20) : "unconfirmed"],
    ["03 PLAN", f.run?.plan_hash ? shortHash(f.run.plan_hash, 20) : "no saved plan"],
    ["04 CEDAR", f.evaluated ? `${f.counts.ALLOW} allow · ${f.counts.REVIEW} review · ${f.counts.DENY} deny${f.counts.EVALUATION_ERROR ? ` · ${f.counts.EVALUATION_ERROR} error` : ""}` : "not evaluated"],
    ["05 HUMAN", Object.keys(f.resolutions).length ? `${Object.keys(f.resolutions).length} decision(s) recorded` : "none recorded"],
    ["06 GATE", f.apply ? `${f.apply.status}: ${f.apply.reason}` : "not requested"],
  ];
  const done = [!!task.intent, !!task.confirmed_contract_hash, !!f.run?.plan_hash, f.evaluated, Object.keys(f.resolutions).length > 0 || (f.evaluated && !f.awaiting.length), !!f.apply].filter(Boolean).length;

  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(list, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url; a.download = `planreview-audit-${task.id.slice(0, 8)}.json`; a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return (
    <section className="subview">
      <Heading title="The record behind the view." kicker="EVIDENCE" back={[`/task/${task.id}/plan`, "Plan Review"]} lede="Follow the chain from confirmed intent to the plan, Cedar's decisions, the human's resolutions and the backend gate. Every value below is read from the persisted audit log." />
      <div className="evidence-detail">
        <div className="chain-diagram">
          <Caption>INTENT → PLAN → VERDICT → GATE</Caption>
          <SignalCanvas type="TRACE" />
          {chain.map(([k, v]) => <p className="chain-label" key={k}><b>{k}</b> / {v}</p>)}
          {f.verdicts.map((v) => <div key={v.address} style={{ marginTop: 6 }}><VerdictBadge type={v.verdict} /> <span className="rule-reason">{v.address}</span></div>)}
        </div>
        <div>
          <Caption>{`TASK ${task.id.slice(0, 8)} / ${audit ? audit.length : "…"} PERSISTED RECORDS`}</Caption>
          <Stepper current={Math.min(3, (task.confirmed_contract_hash ? 1 : 0) + (f.evaluated ? 1 : 0) + (f.evaluated && !f.awaiting.length && !f.counts.DENY ? 1 : 0))} />
          <p className="rule-reason">{done} of 6 links in the chain exist for this task.</p>
        </div>
      </div>

      {error && <ErrorBlock error={error} />}
      {!audit && !error && <Loading />}
      {audit && !chosen && (
        <>
          <Caption>{`TOTAL RECORDS ${audit.length} / ${list.length} MATCHING`}</Caption>
          <div className="filter-bar">
            {kinds.map((k) => <button key={k} type="button" className={"chip " + (filter === k ? "selected" : "")} aria-pressed={filter === k} onClick={() => setFilter(k)}>{k === "ALL" ? "ALL" : KIND_LABEL[k] || k}</button>)}
            <button className="site-button" onClick={download} data-download="">Download JSON</button>
          </div>
          {!list.length && <div className="empty-state"><h2>Nothing crossed this line.</h2><button className="site-button" onClick={() => setFilter("ALL")}>Clear filters</button></div>}
          <div className="evidence-grid">
            {list.map((e) => {
              const lines = summarize(e);
              return (
                <article className="evidence-tile" key={e.id}>
                  <Caption>{`#${String(e.id).padStart(4, "0")} / ${KIND_LABEL[e.kind] || e.kind}`}</Caption>
                  <h3 style={{ fontSize: 20 }}>{lines[0] || KIND_LABEL[e.kind]}</h3>
                  {verdictOf(e) && <VerdictBadge type={verdictOf(e)} />}
                  <div className="evidence-meta">{lines.slice(1).map((l, i) => <span key={i}>{l}<br /></span>)}{when(e.timestamp)}</div>
                  <button className="site-button" data-cursor="INSPECT" onClick={() => setSelected(e.id)}>Inspect record ↗</button>
                </article>
              );
            })}
          </div>
        </>
      )}
      {chosen && (
        <div style={{ marginTop: 24 }}>
          <button className="site-button" data-cursor="BACK" onClick={() => setSelected(null)}>← Return to records</button>
          <Caption>{`RECORD #${String(chosen.id).padStart(4, "0")} / ${KIND_LABEL[chosen.kind] || chosen.kind} / ${when(chosen.timestamp)}`}</Caption>
          <p className="rule-reason">{summarize(chosen).filter(Boolean).join(" · ")}</p>
          <p className="rule-reason">Raw persisted payload (may include local file paths and the full plan output):</p>
          <JsonView data={chosen} />
          <div className="site-actions"><button className="site-button" onClick={() => copyText(JSON.stringify(chosen, null, 2))}>Copy JSON</button><Link className="site-button" to={`/task/${task.id}/plan`}>Back to plan →</Link></div>
        </div>
      )}
    </section>
  );
}
