import { useEffect, useRef, useState } from "react";
import { Link, Navigate } from "react-router-dom";
import { Caption, Heading, Loading } from "../ui";
import { PIPELINE } from "../lib/taskModel";
import { useTasks } from "../state/tasks";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

const STEPS = [
  ["01 / INTENT", "A person says what should change.", "The request goes to the backend, which interprets it and checks it against a deterministic registry of supported operations. If the request is unsupported or ambiguous you get an error, never a guess.", ["Fixture replay or a live local model", "Supported: Lambda memory, S3 Team tag", "A failed interpretation stays an error"]],
  ["02 / CONTRACT", "Intent becomes a boundary.", "The backend drafts a contract: allowed resource, operation, region, a limit on changed resources and forbidden categories. A human confirms it and the backend seals it with a hash. It cannot change afterwards.", ["Human confirmation is explicit", "The hash is computed by the backend", "Sealed contracts are immutable"]],
  ["03 / AGENT", "The agent edits Terraform.", "In fixture replay a reproducible edit is applied. In live mode a local Ollama model, driven by Strands, edits the baseline under the confirmed intent. The agent can propose; it cannot authorize.", ["Pre-plan guard rejects unexpected files", "Live output is validated, not trusted", "No fallback from live to replay"]],
  ["04 / TERRAFORM", "A real plan is saved.", "The backend runs a real terraform plan (no AWS calls, dummy credentials), saves it and hashes it. The plan, not a summary of it, is the evidence.", ["Plan and raw JSON hashes", "Canonical resource changes", "Before and after for each attribute"]],
  ["05 / CEDAR", "Every change gets one verdict.", "Cedar evaluates each canonical change against the contract: ALLOW, REVIEW or DENY, with the policy that decided it. If evaluation itself fails, that is EVALUATION_ERROR, a technical failure that nobody can approve.", ["ALLOW inside the contract", "REVIEW needs a human", "DENY is a firm stop"]],
  ["06 / HUMAN REVIEW", "People decide only what needs deciding.", "A REVIEW item can be approved or rejected, and the backend records it against that exact plan. DENY and EVALUATION_ERROR items offer no approval control, and the backend refuses one if you try.", ["Approvals bound to one saved plan", "A new plan clears resolutions", "The robot guides; it does not judge"]],
  ["07 / GATE", "The backend decides whether anything may proceed.", "The gate re-checks the contract, plan hash, policy hash and verdicts. Real AWS apply is disabled, so the answer is a reasoned BLOCKED. The interface displays it; it never computes its own.", ["Server-enforced", "A visible button proves nothing", "AWS apply stays disabled"]],
  ["08 / EVIDENCE", "Everything is written down.", "Each stage is persisted in an audit log. The Evidence page follows the chain from contract to plan, verdicts, resolutions and gate, with the raw record one click away.", ["Persistent SQLite audit", "One auditable chain per task", "Raw JSON on demand"]],
];

function drawDiagram(c, phase, t, rd) {
  c.clearRect(0, 0, 600, 400);
  c.strokeStyle = "#9eaa83"; c.lineWidth = 2; c.beginPath();
  const pts = [[180, 70], [420, 70], [500, 200], [420, 330], [180, 330], [100, 200], [180, 70]];
  const prog = phase === 0 && !rd ? Math.min(1, 0.55 + (t % 4) / 4) : 1;
  c.moveTo(...pts[0]);
  for (let i = 1; i < pts.length; i++) {
    const a = Math.max(0, Math.min(1, prog * 6 - (i - 1)));
    if (a > 0) c.lineTo(pts[i - 1][0] + (pts[i][0] - pts[i - 1][0]) * a, pts[i - 1][1] + (pts[i][1] - pts[i - 1][1]) * a);
  }
  c.stroke();
  c.font = "12px monospace"; c.textAlign = "center"; c.fillStyle = "#aaa99f"; c.fillText("CONFIRMED CONTRACT", 300, 48);
  if (phase >= 1) {
    const colors = ["#72e6a1", "#f1c34f", "#ff6f72"];
    for (let i = 0; i < 3; i++) {
      const x = rd ? 200 + i * 90 : 80 + ((t * 0.12 + i * 0.28) % 1) * 400;
      c.fillStyle = x < 110 ? "#aaa99f" : colors[i]; c.beginPath(); c.arc(x, 155 + i * 45, 8, 0, Math.PI * 2); c.fill();
    }
    c.fillStyle = "#77776d"; c.fillText("ILLUSTRATION · the three verdict kinds", 300, 385);
  }
  if (phase === 2) {
    c.strokeStyle = "#ff6f72"; c.lineWidth = 5; c.beginPath(); c.moveTo(500, 160); c.lineTo(500, 240); c.stroke();
    c.fillStyle = "#ff6f72"; c.fillText("GATE: CLOSED UNTIL THE BACKEND SAYS OTHERWISE", 300, 370);
  }
}

export function HowItWorks() {
  const [k, setK] = useState(0);
  const scroll = useRef(null), canvas = useRef(null), state = useRef({ k: 0 });
  useEffect(() => {
    const rd = reduced();
    const measure = () => {
      const r = scroll.current.getBoundingClientRect();
      const ratio = Math.max(0, Math.min(1, -r.top / Math.max(1, scroll.current.offsetHeight - innerHeight)));
      const next = Math.min(STEPS.length - 1, Math.floor(ratio * STEPS.length));
      if (!rd && next !== state.current.k) { state.current.k = next; setK(next); }
    };
    let raf = 0, last = 0;
    const c = canvas.current.getContext("2d");
    const loop = (now) => {
      raf = requestAnimationFrame(loop);
      if (document.hidden || now - last < 33) return;
      last = now;
      const kk = state.current.k;
      drawDiagram(c, kk < 2 ? 0 : kk < 5 ? 1 : 2, now / 1000, rd);
    };
    raf = requestAnimationFrame(loop);
    window.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure, { passive: true });
    measure();
    return () => { cancelAnimationFrame(raf); window.removeEventListener("scroll", measure); window.removeEventListener("resize", measure); };
  }, []);
  const go = (i) => {
    if (reduced()) { state.current.k = i; setK(i); return; }
    const el = scroll.current;
    window.scrollTo({ top: el.getBoundingClientRect().top + scrollY + ((el.offsetHeight - innerHeight) * (i + 0.45)) / STEPS.length, behavior: "smooth" });
  };
  const s = STEPS[k];
  return (
    <section className="subview">
      <Heading title="One boundary. Eight stages." kicker="HOW IT WORKS" lede="The agent proposes a change. The confirmed boundary, Cedar and a human decide what may proceed. This is the real PlanReview workflow, endpoint by endpoint." />
      <section className="how-scroll" ref={scroll} style={{ height: `${STEPS.length * 60}vh` }}>
        <div className="how-sticky">
          <div className="how-layout">
            <div className="how-copy" aria-live="polite">
              <Caption>{s[0]}</Caption>
              <h2>{s[1]}</h2>
              <p>{s[2]}</p>
              <ul className="how-list">{s[3].map((x) => <li key={x}>— {x}</li>)}</ul>
              <p className="rule-id">{PIPELINE[k].api}</p>
            </div>
            <canvas ref={canvas} width="600" height="400" className="how-diagram" aria-hidden="true" />
          </div>
          <div className="how-steps">
            {STEPS.map((x, i) => <button key={x[0]} className={"site-button " + (k === i ? "primary" : "")} aria-current={k === i} onClick={() => go(i)}>{x[0].split(" / ")[0]}</button>)}
          </div>
        </div>
      </section>
      <section className="agent-table">
        <div><Caption>THE AGENT MAY PROPOSE</Caption><h3>Possibilities.</h3><p>An edit to Terraform inside the confirmed scope, produced by a fixture or a local model.</p></div>
        <div><Caption>THE BOUNDARY DECIDES</Caption><h3>Permission.</h3><p>Cedar classifies each change, people resolve REVIEW, and the backend keeps the gate closed until the record allows otherwise.</p></div>
      </section>
      <div className="site-actions"><Link className="site-button primary" to="/new">Try it →</Link></div>
    </section>
  );
}

export function About() {
  return (
    <section className="subview">
      <Heading title="Why the boundary matters." kicker="ABOUT" />
      <div className="editorial">
        <div className="editorial-copy">
          <p>AI coding agents can change infrastructure quickly, but speed changes the review problem. The question is no longer only whether Terraform is valid. It is whether the proposed change still matches the job a human actually authorized.</p>
          <p>PlanReview treats that human intent as a first-class boundary. The task is confirmed before execution, the resulting Terraform plan is evaluated change by change, and the apply gate stays closed while a prohibited or unresolved change remains.</p>
          <div className="pull">“The agent can propose. The boundary decides what may proceed.”</div>
          <p>The goal is not to replace the reviewer with another layer of AI. It is to make the relationship between intent and infrastructure explicit enough that a reviewer can understand the decision and audit it later.</p>
        </div>
        <div className="editorial-copy">
          <Caption>WHAT IT IS, TODAY</Caption>
          <p>A local-first checkpoint: React interface, FastAPI backend, real Terraform plans, Cedar policies, a local Ollama model through Strands, and SQLite audit. Nothing leaves your machine.</p>
          <Caption>SUPPORTED SCOPE</Caption>
          <p>Two operations are supported: the memory of the dev-api Lambda function (128–10240 MB) and the <code>Team</code> tag on the assets S3 bucket. Requests for anything else are refused. Fixture replay demonstrates ALLOW, REVIEW and DENY on real plans; it is not a wider capability.</p>
          <Caption>WHAT IT IS NOT</Caption>
          <p>It is not a general AWS editor, not a replacement for a human reviewer, and not an apply engine: real AWS apply is disabled. The 3D reviewer is a visual guide that mirrors task status; Cedar decides verdicts.</p>
        </div>
      </div>
      <div className="site-actions"><Link className="site-button primary" to="/new">Create a task →</Link><Link className="site-button" to="/how-it-works">How it works</Link></div>
    </section>
  );
}

export function Legal() {
  return (
    <section className="subview">
      <Heading title="Legal." kicker="LEGAL" />
      <div className="legal-copy">
        <p className="sample-tag">PLACEHOLDER — replace before any public launch.</p>
        <h3>Terms</h3><p>This is a local development build. It is provided as is, with no warranty. Real AWS apply is disabled.</p>
        <h3>Privacy</h3><p>The application talks only to a backend on your own machine and, in live mode, a local Ollama model. It sets no cookies. A graphics preference may be kept in local storage.</p>
        <h3>Illustrations</h3><p>Sections labelled ILLUSTRATIVE (for example the signal tiles and the verdict dots in How it works) are drawings, not task data.</p>
      </div>
    </section>
  );
}

export function NotFound() {
  return (
    <section className="subview not-found">
      <Heading title="Outside the boundary." kicker="404" />
      <p className="rule-reason">ROUTE NOT FOUND</p>
      <div className="site-actions"><Link className="site-button primary" to="/">Return home</Link></div>
    </section>
  );
}

/** /plan-review and /evidence in the original nav: jump to the newest task's page. */
export function LatestTaskRedirect({ page }) {
  const { tasks, loaded } = useTasks();
  if (!loaded) return <section className="subview"><Loading /></section>;
  const t = tasks[0];
  return <Navigate replace to={t ? `/task/${t.id}/${page}` : "/workspace"} />;
}
