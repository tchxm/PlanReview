// Pure presentation helpers over a BACKEND task object. Nothing here decides
// authorization: verdicts, resolutions and the gate come from the backend.

export const PIPELINE = [
  { id: "intent", label: "Intent", api: "POST /api/tasks" },
  { id: "contract", label: "Contract", api: "POST /api/tasks/{id}/confirm" },
  { id: "agent", label: "Agent", api: "POST /api/tasks/{id}/agent" },
  { id: "plan", label: "Terraform plan", api: "POST /api/tasks/{id}/plan" },
  { id: "cedar", label: "Cedar decisions", api: "POST …/canonicalize · …/evaluate" },
  { id: "review", label: "Human REVIEW", api: "POST /api/tasks/{id}/resolve" },
  { id: "gate", label: "Apply gate", api: "POST /api/tasks/{id}/apply" },
  { id: "evidence", label: "Evidence", api: "GET /api/tasks/{id}/audit" },
];

export const latestRun = (task) => (task?.runs?.length ? task.runs[task.runs.length - 1] : null);
export const isLive = (task) => task?.mode === "ollama" || task?.mode === "live";
export const modeLabel = (mode) => (mode === "ollama" || mode === "live" ? "LIVE LOCAL MODEL" : mode === "adversarial" ? "ADVERSARIAL FIXTURE" : "FIXTURE REPLAY");

export function taskFacts(task) {
  const run = latestRun(task);
  const verdicts = run?.verdicts || [];
  const counts = { ALLOW: 0, REVIEW: 0, DENY: 0, EVALUATION_ERROR: 0 };
  for (const v of verdicts) if (v.verdict in counts) counts[v.verdict]++;
  const resolutions = run?.resolutions || {};
  return {
    run,
    verdicts,
    counts,
    resolutions,
    awaiting: verdicts.filter((v) => v.verdict === "REVIEW" && !resolutions[v.address]),
    apply: run?.apply_result || null,
    expired: task?.contract?.expires_at ? new Date(task.contract.expires_at) <= new Date() : false,
    hasPlan: !!run?.plan_hash,
    evaluated: !!run?.verdicts,
    sealed: task?.contract?.status === "confirmed",
    hasFault: counts.EVALUATION_ERROR > 0,
  };
}

/** Short status chip wording (backend facts only). */
export function statusChip(task) {
  if (!task) return { label: "—", tone: "" };
  const f = taskFacts(task);
  if (f.hasFault) return { label: "Evaluation error", tone: "deny" };
  if (f.apply?.status === "APPLIED") return { label: "Applied (local)", tone: "allow" };
  if (f.apply?.status === "FAILED") return { label: "Apply failed", tone: "deny" };
  if (f.evaluated) {
    if (f.counts.DENY) return { label: `${f.counts.DENY} denied`, tone: "deny" };
    if (f.awaiting.length) return { label: `${f.awaiting.length} awaiting review`, tone: "review-b" };
    if (f.apply?.status === "BLOCKED") return { label: "Gate blocked", tone: "deny" };
    return { label: "Evaluated", tone: "allow" };
  }
  const m = { draft: "Contract draft", confirmed: "Contract sealed", edited: "Edits prepared", planned: "Planned", canonicalized: "Canonicalized" };
  return { label: m[task.stage] || task.stage || "—", tone: "" };
}

/** Index into PIPELINE of the current step. */
export function currentStep(task) {
  if (!task) return 0;
  const f = taskFacts(task);
  if (f.apply) return 7;
  if (f.evaluated) return f.awaiting.length || f.counts.DENY || f.hasFault ? 5 : 6;
  return { draft: 1, confirmed: 2, edited: 3, planned: 4, canonicalized: 4 }[task.stage] ?? 4;
}

/** Reviewer robot state: mirrors backend facts and client activity, never judges. */
export function robotStateOf(task, { busy = null, error = null } = {}) {
  if (error) return "fault";
  const f = taskFacts(task);
  if (f.hasFault) return "fault";
  if (busy) return busy.kind === "agent" || busy.kind === "create" ? "preparing" : "inspecting";
  if (!task) return "idle";
  if (f.apply?.status === "APPLIED") return "clear";
  if (f.apply?.status === "FAILED") return "fault";
  if (f.evaluated) {
    if (f.counts.DENY) return "blocked";
    if (f.awaiting.length) return "waiting";
    if (f.apply?.status === "BLOCKED") return "blocked";
    return "idle";
  }
  if (task.stage === "edited") return "preparing";
  if (task.stage === "planned" || task.stage === "canonicalized") return "inspecting";
  return "idle";
}

export const when = (iso) => {
  try { return new Date(iso).toLocaleString(); } catch { return String(iso ?? ""); }
};
export const shortHash = (h, n = 12) => (h ? h.slice(0, n) : "—");
export const fmt = (v) => (v === null || v === undefined ? "null" : typeof v === "object" ? JSON.stringify(v) : String(v));
