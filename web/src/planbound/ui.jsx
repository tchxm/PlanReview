import { Link } from "react-router-dom";
import { describeError, ApiError } from "../api";

// React versions of the original site-ui helpers, emitting the original markup and classes.

export const Caption = ({ children }) => <p className="site-caption">{children}</p>;

export function Heading({ title, kicker, lede, back = ["/", "Home"] }) {
  return (
    <header className="view-heading">
      <Link className="return-link" to={back[0]} data-cursor="BACK">← Return to {back[1]}</Link>
      <Caption>{kicker}</Caption>
      <h1>{title}</h1>
      {lede ? <p className="view-lede">{lede}</p> : null}
    </header>
  );
}

const BADGE_CLASS = { ALLOW: "allow", REVIEW: "review-b", DENY: "deny", EVALUATION_ERROR: "deny", APPLIED: "allow", BLOCKED: "deny" };
const BADGE_ICON = { ALLOW: "✓", REVIEW: "◇", DENY: "×", EVALUATION_ERROR: "!", APPLIED: "✓", BLOCKED: "⊣" };
const BUS = { ALLOW: "allow", REVIEW: "review", DENY: "deny", EVALUATION_ERROR: "deny", APPLIED: "allow", BLOCKED: "deny" };

/** Verdict pill. Also tells the reviewer robot which verdict is hovered (original behaviour). */
export function VerdictBadge({ type }) {
  const emit = () => window.PB?.bus.emit("verdict", BUS[type] || "deny");
  return (
    <button type="button" className={"badge " + (BADGE_CLASS[type] || "")} data-verdict={(BUS[type] || "").toLowerCase()} data-cursor="INSPECT" onPointerEnter={emit} onFocus={emit} onClick={emit}>
      {(BADGE_ICON[type] || "·") + " " + (type === "EVALUATION_ERROR" ? "EVALUATION ERROR" : type)}
    </button>
  );
}

export function Stepper({ current, labels = ["Intent confirmed", "Plan evaluated", "Human resolved"] }) {
  return (
    <div className="site-stepper">
      <Caption>{`STEP — ${String(current).padStart(2, "0")} / ${String(labels.length).padStart(2, "0")}`}</Caption>
      <div className="step-chips">
        {labels.map((l, i) => <span key={l} className={i < current ? "complete" : ""}>{String(i + 1).padStart(2, "0")} {l}</span>)}
      </div>
    </div>
  );
}

/** Original error block. `error` may be an ApiError, an Error or a string. */
export function ErrorBlock({ error, hint }) {
  if (!error) return null;
  const code = error instanceof ApiError ? error.code : null;
  const msg = typeof error === "string" ? error : error instanceof ApiError ? error.message : describeError(error);
  return (
    <div className="site-error" role="alert">
      <strong>× Error Detected{code ? ` · ${code}` : ""}</strong>
      <p>{msg}</p>
      {hint ? <p className="rule-reason">{hint}</p> : null}
    </div>
  );
}

function jsonNode(value, key, depth = 0) {
  if (value && typeof value === "object" && depth < 8) {
    const entries = Object.entries(value);
    return (
      <details className="json-node" open={depth < 2} key={key}>
        <summary><span className="json-key">{key || "record"}</span>{Array.isArray(value) ? ` [${entries.length}]` : ` {${entries.length}}`}</summary>
        {entries.map(([k, v]) => jsonNode(v, k, depth + 1))}
      </details>
    );
  }
  return (
    <div className="json-value" key={key}>
      <span className="json-key">{key + ": "}</span>
      <span className={typeof value === "string" ? "json-string" : "json-number"}>{JSON.stringify(value)}</span>
    </div>
  );
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch { return false; }
}

export function JsonView({ data }) {
  return (
    <div className="site-json">
      <button type="button" className="site-button" data-cursor="INSPECT" onClick={() => copyText(JSON.stringify(data, null, 2))}>Copy JSON</button>
      {jsonNode(data, "record")}
    </div>
  );
}

export function Loading({ children = "Loading from the backend…" }) {
  return <p className="rule-reason" role="status">{children}</p>;
}

export function BackendOffline({ error, onRetry }) {
  return (
    <div className="inline-banner">
      <strong>The PlanReview backend is not reachable.</strong>{" "}
      <span>{error?.message || "Start it with .\\start.ps1 (FastAPI on 127.0.0.1:8000)."}</span>{" "}
      {onRetry ? <button className="site-button" onClick={onRetry}>Retry</button> : null}
    </div>
  );
}

/** Show a factual status on the reviewer's CRT (backend-derived text only). Clears when text is null. */
export function setRobotStatus(text, color) {
  const PB = window.PB;
  if (!PB?.store) return;
  const S = PB.store.get();
  S.robotText = text || null;
  S.robotColor = color || null;
  PB.bus.emit("gate", S.gateOpen);
}
