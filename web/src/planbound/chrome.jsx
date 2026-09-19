import { useRef } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTasks } from "./state/tasks";
import { taskFacts } from "./lib/taskModel";

const LINKS = [["How it works", "/how-it-works"], ["Workspace", "/workspace"], ["Plan Review", "/plan-review"], ["Evidence", "/evidence"], ["About", "/about"]];

/** Backend-derived boundary chip: the newest task's contract status and its backend hash. */
export function useBoundary() {
  const { tasks, backend } = useTasks();
  const task = tasks[0];
  const f = task ? taskFacts(task) : null;
  return { task, confirmed: !!task?.confirmed_contract_hash, hash: task?.confirmed_contract_hash, gateOpen: f?.apply?.status === "APPLIED", backend };
}

export function Nav() {
  const loc = useLocation();
  const b = useBoundary();
  return (
    <>
      <nav className="site-nav">
        <Link className="brand" to="/"><i />PlanBound</Link>
        <div className="navlinks">
          {LINKS.map(([name, path]) => (
            <Link key={path} to={path} aria-current={loc.pathname.startsWith(path) ? "page" : undefined}>{name}</Link>
          ))}
        </div>
        <div className="nav-tools">
          <Link className="navcta magnetic" to="/new">New task</Link>
          <button className="site-button" onClick={() => document.getElementById("pb-menu")?.showModal()} aria-haspopup="dialog" aria-label="Open site menu">Menu</button>
        </div>
      </nav>
      <Link className="nav-status" to={b.task ? `/task/${b.task.id}/${b.confirmed ? "plan" : "contract"}` : "/workspace"} aria-label="Boundary status">
        <span className={"gate-dot" + (b.gateOpen ? " open" : "")} />
        {b.backend === "offline" ? "BACKEND: OFFLINE" : "BOUNDARY: " + (b.confirmed ? "CONFIRMED · " + b.hash.slice(0, 6) : "NONE")}
      </Link>
    </>
  );
}

export function MenuDialog() {
  const ref = useRef(null);
  return (
    <dialog id="pb-menu" ref={ref} className="menu-dialog" aria-label="Site menu">
      <div className="menu-top">
        <span className="caption">PLANBOUND / SITE MAP</span>
        <button onClick={() => ref.current.close()}>Close ×</button>
      </div>
      <div className="menu-links">
        {[["Home", "/"], ...LINKS, ["New task", "/new"], ["Legal", "/legal"]].map(([t, p]) => (
          <Link key={p} to={p} onClick={() => ref.current.close()}>{t}</Link>
        ))}
      </div>
    </dialog>
  );
}

export function SiteFooter() {
  return (
    <footer className="site-footer">
      <div className="footer-columns">
        <div>
          <span className="caption">PLANBOUND</span>
          <p>Infrastructure changes, within intent.</p>
          <button onClick={() => window.scrollTo({ top: 0, behavior: "smooth" })}>Return to top ↑</button>
        </div>
        <div>
          <span className="caption">EXPLORE</span>
          {LINKS.slice(0, 3).map(([n, p]) => <Link key={p} to={p}>{n}</Link>)}
        </div>
        <div>
          <span className="caption">UNDERSTAND</span>
          {LINKS.slice(3).map(([n, p]) => <Link key={p} to={p}>{n}</Link>)}
          <Link to="/legal">Legal</Link>
          <a href="/console.html">Classic console (fallback)</a>
        </div>
      </div>
      <div className="footer-notice">Local-first. Every task shown comes from the PlanReview backend. Real AWS apply is disabled. Cinematic sections are illustrations and are labelled as such.</div>
      <div className="footer-word" aria-hidden="true">PLANBOUND</div>
    </footer>
  );
}
