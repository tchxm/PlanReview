import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { useTasks } from "../state/tasks";
import { taskFacts } from "../lib/taskModel";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const COLORS = { DENY: "#ff6f72", REVIEW: "#f1c34f", ALLOW: "#72e6a1", TRACE: "#9eaa83" };
const CAPTION = { DENY: "A firm stop.", REVIEW: "A human decision.", ALLOW: "Within the boundary.", TRACE: "Follow the evidence." };

/** The original signal animation (site-ui.js `signal`): 2D canvas, <= 30 fps, only while visible. */
function SignalCanvas({ type }) {
  const ref = useRef(null);
  useEffect(() => {
    const canvas = ref.current, c = canvas.getContext("2d");
    let visible = false, raf = 0, last = 0, stopped = false;
    const rd = reduced();
    const io = new IntersectionObserver((es) => { visible = es[0].isIntersecting; }, { threshold: 0 });
    io.observe(canvas);
    function draw(t) {
      c.clearRect(0, 0, 320, 100);
      const color = COLORS[type];
      c.strokeStyle = "#2a2c27"; c.lineWidth = 1; c.beginPath(); c.moveTo(28, 50); c.lineTo(290, 50); c.stroke();
      c.fillStyle = color; c.strokeStyle = color;
      if (type === "DENY") { const x = rd ? 230 : 28 + Math.min(1, (t % 2) / 1.4) * 200; c.fillRect(x, 46, 25, 8); c.fillRect(255, 25, 2, 50); }
      else if (type === "REVIEW") { c.globalAlpha = rd ? 1 : 0.55 + 0.45 * Math.sin(t * 3); c.beginPath(); c.arc(160, 50, 9, 0, Math.PI * 2); c.fill(); c.globalAlpha = 1; }
      else if (type === "ALLOW") { c.beginPath(); c.moveTo(28, 50); c.lineTo(290, 50); c.stroke(); }
      else { for (const x of [35, 160, 285]) { c.beginPath(); c.arc(x, 50, 4, 0, Math.PI * 2); c.fill(); } c.beginPath(); c.arc(rd ? 160 : 35 + ((t * 0.15) % 1) * 250, 50, 6, 0, Math.PI * 2); c.fill(); }
    }
    function loop(now) {
      if (stopped) return;
      raf = requestAnimationFrame(loop);
      if (!visible || document.hidden || now - last < 33) return;
      last = now; draw(now / 1000);
    }
    draw(0); raf = requestAnimationFrame(loop);
    return () => { stopped = true; cancelAnimationFrame(raf); io.disconnect(); };
  }, [type]);
  return <canvas ref={ref} width="320" height="100" aria-hidden="true" className="signal-canvas" />;
}

function Counter({ value }) {
  const ref = useRef(null);
  useEffect(() => {
    const el = ref.current;
    if (reduced()) { el.textContent = value; return undefined; }
    let raf = 0, start = 0;
    const io = new IntersectionObserver((es) => {
      if (!es[0].isIntersecting) return;
      io.disconnect();
      const tick = (now) => { start ||= now; const p = Math.min(1, (now - start) / 800); el.textContent = Math.round(value * (1 - Math.pow(1 - p, 3))).toLocaleString(); if (p < 1) raf = requestAnimationFrame(tick); };
      raf = requestAnimationFrame(tick);
    });
    io.observe(el);
    return () => { io.disconnect(); cancelAnimationFrame(raf); };
  }, [value]);
  return <strong ref={ref}>0</strong>;
}

/** Home's lower sections in the approved site's layout, with REAL counts from the backend. */
export default function HomeBelow({ root }) {
  const { tasks } = useTasks();
  const evaluated = tasks.filter((t) => taskFacts(t).evaluated);
  const changes = evaluated.reduce((n, t) => n + taskFacts(t).verdicts.length, 0);
  const decisions = evaluated.reduce((n, t) => n + Object.keys(taskFacts(t).resolutions).length, 0);
  return createPortal(
    <>
      <section className="paths reveal home-paths visible" id="paths">
        {[
          ["01 / DEFINE", "Set the boundary.", "Create a task and confirm its contract. Supported today: Lambda memory on dev-api and the Team tag on the assets bucket.", "/new"],
          ["02 / INSPECT", "Read the decisions.", "Inspect every change and the rule behind its verdict. Resolve the uncovered work.", "/workspace"],
          ["03 / APPLY", "Respect the gate.", "Only the resolved set may proceed. The gate is enforced by the backend, and real AWS apply is disabled.", "/how-it-works"],
        ].map(([step, title, body, to]) => (
          <article className="path" key={step}>
            <span className="caption">{step}</span>
            <h2>{title}</h2>
            <p>{body}</p>
            <Link className="site-button" to={to}>Explore →</Link>
          </article>
        ))}
      </section>
      <p className="demo-caption" style={{ padding: "0 5vw" }}>ILLUSTRATIVE · the four kinds of signal, not task data</p>
      <section className="home-signals" aria-label="Decision signals">
        {[["DENY", "/workspace"], ["REVIEW", "/workspace"], ["ALLOW", "/new"], ["TRACE", "/evidence"]].map(([type, to]) => (
          <Link className="signal-tile" to={to} data-cursor="OPEN" key={type}>
            <span className="caption">SIGNAL / {type}</span>
            <SignalCanvas type={type} />
            <h3>{type}</h3>
            <p className="rule-reason">{CAPTION[type]}</p>
          </Link>
        ))}
      </section>
      <section className="home-counts">
        {[["PLANS EVALUATED", evaluated.length], ["CHANGES GATED", changes], ["HUMAN DECISIONS", decisions]].map(([label, n]) => (
          <div key={label}><span className="caption">LIVE · FROM THE BACKEND</span><Counter value={n} /><span className="caption">{label}</span></div>
        ))}
      </section>
      <section className="cta-band site-below">
        <span className="caption">BEGIN</span>
        <h2>Set the boundary. Then let the agent run.</h2>
        <div className="site-actions">
          <Link className="site-button primary" to="/new">Define a boundary →</Link>
          <Link className="site-button" to="/workspace">Inspect a plan →</Link>
        </div>
      </section>
    </>,
    root,
  );
}
