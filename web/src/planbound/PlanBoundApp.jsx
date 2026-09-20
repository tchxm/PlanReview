import { useEffect, useMemo, useRef, useState } from "react";
import { Route, Routes, useLocation } from "react-router-dom";
import { SHELL_HTML } from "./shell.generated";
import { HOME_MARKUP } from "./home";
import { startEngine } from "./engine";
import { useTasks } from "./state/tasks";
import { taskFacts } from "./lib/taskModel";
import { Nav, SiteFooter, MenuDialog, KeyboardNav } from "./chrome";
import { HomeLive, HomeRecord } from "./pages/HomeLive";
import HomeBelow from "./pages/HomeBelow";
import { Workspace, NewTask } from "./pages/Tasks";
import TaskContract from "./pages/TaskContract";
import TaskPlan from "./pages/TaskPlan";
import TaskEvidence from "./pages/TaskEvidence";
import { HowItWorks, About, Legal, NotFound, LatestTaskRedirect } from "./pages/Editorial";

/** React route -> the engine's original lifecycle route names. */
const engineRoute = (p) => (p === "/" ? "/" : /^\/task\/[^/]+\/plan/.test(p) || p === "/plan-review" ? "/plan-review" : p);
const hashPath = () => window.location.hash.replace(/^#/, "") || "/";

export default function PlanBoundApp() {
  const loc = useLocation();
  const { tasks } = useTasks();
  const engine = useRef(null);
  const [ready, setReady] = useState(false);
  const [homeRoot, setHomeRoot] = useState(null);
  const [recordEl, setRecordEl] = useState(null);
  const [belowRoot, setBelowRoot] = useState(null);
  const shell = useMemo(() => ({ __html: SHELL_HTML }), []);
  const home = useMemo(() => ({ __html: HOME_MARKUP }), []);
  const path = loc.pathname;

  // Start the ORIGINAL engine once the ORIGINAL markup is in the DOM.
  useEffect(() => {
    let cancelled = false, raf = 0;
    const eng = startEngine();
    engine.current = eng;
    setHomeRoot(document.getElementById("home-live-root"));
    setRecordEl(document.querySelector("#data pre"));
    setBelowRoot(document.getElementById("home-below-root"));
    // Let the boot screen paint before either WebGL factory runs (as the original does).
    raf = requestAnimationFrame(() => requestAnimationFrame(() => {
      if (cancelled) return;
      const r = engineRoute(hashPath());
      eng.routeTo(r);
      eng.completeDeferred(r);
      setReady(true);
    }));
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      eng.dispose();
      engine.current = null;
    };
  }, []);

  // Route effects: original lifecycle (hero/robot creation, pausing, disposal), then attach the
  // singleton robot canvas to Home's studio or the page's companion slot, as the original router does.
  useEffect(() => {
    const homeEl = document.getElementById("home-view");
    if (homeEl) homeEl.hidden = path !== "/";
    if (!ready) return undefined;
    const eng = engine.current;
    eng.routeTo(engineRoute(path));
    const slot = path === "/" ? document.querySelector("#unit .studio-sticky") : document.querySelector("#route-view [data-robot-slot]");
    if (slot) slot.dataset.robotSlot = "";
    eng.robotTo(slot);
    if (!slot) return undefined;
    const ro = new ResizeObserver(() => eng.PB.robot?.resize?.());
    ro.observe(slot);
    return () => ro.disconnect();
  }, [path, ready]);

  // The engine's robot screen and tree read the gate from the backend, never from a sample store.
  const gateOpen = tasks[0] ? taskFacts(tasks[0]).apply?.status === "APPLIED" : false;
  useEffect(() => { if (ready) engine.current?.setGate(gateOpen); }, [gateOpen, ready]);

  return (
    <>
      <div dangerouslySetInnerHTML={shell} />
      <Nav />
      <MenuDialog />
      <KeyboardNav />
      <main id="view" tabIndex={-1}>
        <div id="home-view" dangerouslySetInnerHTML={home} />
        <div id="route-view" hidden={path === "/"}>
          <Routes>
            <Route path="/" element={null} />
            <Route path="/how-it-works" element={<HowItWorks />} />
            <Route path="/workspace" element={<Workspace />} />
            <Route path="/new" element={<NewTask />} />
            <Route path="/task/:id/contract" element={<TaskContract />} />
            <Route path="/task/:id/plan" element={<TaskPlan />} />
            <Route path="/task/:id/evidence" element={<TaskEvidence />} />
            <Route path="/plan-review" element={<LatestTaskRedirect page="plan" />} />
            <Route path="/evidence" element={<LatestTaskRedirect page="evidence" />} />
            <Route path="/about" element={<About />} />
            <Route path="/legal" element={<Legal />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </div>
      </main>
      <SiteFooter />
      {homeRoot && <HomeLive root={homeRoot} />}
      {belowRoot && <HomeBelow root={belowRoot} />}
      {recordEl && <HomeRecord pre={recordEl} engine={engine} tasks={tasks} />}
    </>
  );
}
