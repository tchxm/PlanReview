import { useEffect } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { taskFacts } from "../lib/taskModel";
import { useTasks } from "../state/tasks";

const BADGE = { ALLOW: "allow", REVIEW: "review-b", DENY: "deny", EVALUATION_ERROR: "deny" };

/** Home's "plan at a glance": the newest REAL evaluated plan, or an honest empty state. */
export function HomeLive({ root }) {
  const { tasks, backend } = useTasks();
  const t = tasks.find((x) => taskFacts(x).evaluated);
  const f = t ? taskFacts(t) : null;
  return createPortal(
    <>
      <p className="demo-caption">{t ? "LIVE · YOUR LATEST SAVED PLAN (BACKEND DATA)" : backend === "offline" ? "BACKEND OFFLINE" : "NO SAVED PLAN YET"}</p>
      <div className="review-head">
        <div>
          <h2>Plan Review</h2>
          <div className="review-sub">{t ? "Changes from the newest Terraform plan the backend has evaluated." : "Create a task and run it to see real Terraform changes and Cedar verdicts here."}</div>
        </div>
        <div className="count">{f ? `${f.verdicts.length} ${f.verdicts.length === 1 ? "change" : "changes"} evaluated` : "—"}</div>
      </div>
      {f && f.verdicts.map((v, i) => (
        <article className="change" key={v.address}>
          <div className="meta"><div className="num">#{i + 1}</div><div className="resource">{v.address}</div></div>
          <div className="diff">
            <div className="diff-title">Terraform Diff</div>
            <pre>{v.changes.map((c, k) => (
              <span key={k}>
                <span className="line-del">{`- ${c.attribute} = ${JSON.stringify(c.before)}`}</span>
                <span className="line-add">{`+ ${c.attribute} = ${JSON.stringify(c.after)}`}</span>
              </span>
            ))}</pre>
          </div>
          <div className="verdict"><div className={"badge " + (BADGE[v.verdict] || "deny")}>{v.verdict}</div><div className="why">{v.reason}</div></div>
        </article>
      ))}
      <div className="site-actions" style={{ marginTop: 24 }}>
        <Link className="site-button primary" to={t ? `/task/${t.id}/plan` : "/new"}>{t ? "Open this plan →" : "Create a task →"}</Link>
        <Link className="site-button" to="/workspace">Workspace</Link>
      </div>
    </>,
    root,
  );
}

/** The Home "record behind the view" is filled from the backend, never from the sample record. */
export function HomeRecord({ pre, engine, tasks }) {
  useEffect(() => {
    const PB = engine.current?.PB;
    if (!PB) return;
    const t = tasks.find((x) => taskFacts(x).evaluated) || tasks[0];
    const f = t ? taskFacts(t) : null;
    PB.record = t
      ? {
          source: "PlanReview backend",
          task_id: t.id,
          mode: t.mode,
          stage: t.stage,
          contract: { status: t.contract.status, hash: t.confirmed_contract_hash || null },
          changes: f.verdicts.map((v) => ({ resource: v.address, verdict: v.verdict, reason: v.reason })),
          apply_gate: f.apply ? f.apply.status : "not requested",
        }
      : { source: "PlanReview backend", status: "no saved task yet" };
    PB.renderJSON(pre, PB.record);
  }, [tasks, engine, pre]);
  return null;
}
