import { THREE } from "./three128";
import installCore from "./core";
import installBoot from "./boot";
import installSupport from "./support";
import installHero from "./hero";
import installTree from "./tree";
import installRobot from "./robot";
import installAudio from "./audio";
import installCursor from "./cursor";
import installPerf from "./perf";

// Honest walkthrough copy for the cinematic tree. The original file carried
// sample numbers ("3 changes", "1 review open"); those are replaced by
// statements that are true of the real workflow, not of any task.
const FEATURE_METRICS = [
  "confirmed by a human",
  "input: a saved Terraform plan",
  "ALLOW · REVIEW · DENY",
  "only REVIEW takes a decision",
  "enforced by the backend",
  "persisted audit trail",
];

/**
 * Record window/document listeners added while `fn` runs so dispose() can
 * remove them exactly. (The original engine registers a few globally.)
 */
function recording(bucket, fn) {
  const targets = [window, document, document.documentElement];
  const originals = targets.map((t) => t.addEventListener);
  targets.forEach((t, i) => {
    t.addEventListener = function (type, handler, opts) {
      bucket.push([t, type, handler, opts]);
      return originals[i].call(t, type, handler, opts);
    };
  });
  try {
    return fn();
  } finally {
    targets.forEach((t) => delete t.addEventListener);
  }
}

/** Boots the original PlanBound engine against the rendered original markup. */
export function startEngine() {
  const bucket = [];
  const store = { gateOpen: false, subscribers: 0 };
  recording(bucket, () => {
    installCore(THREE);
    installBoot(THREE);
    installSupport(THREE);
    installHero(THREE);
    installTree(THREE);
    installRobot(THREE);
    installAudio(THREE);
    installCursor(THREE);
    installPerf(THREE);
  });
  const PB = window.PB;
  PB.FEATURES.forEach((f, i) => (f.metric = FEATURE_METRICS[i] || f.metric));
  // The engine's robot screen reads the gate from a store; here it is backend-fed.
  PB.store = { get: () => store, subscriberCount: () => 0 };

  let disposed = false;
  const api = {
    PB,
    setGate(open) {
      store.gateOpen = !!open;
      PB.bus.emit("gate", store.gateOpen);
    },
    /** Route change: the original lifecycle creates/pauses/disposes hero and robot. */
    routeTo(path) {
      if (disposed) return;
      recording(bucket, () => PB.lifecycle.routeTo(path));
      PB.scroll = 0;
      PB.P = 0;
      PB.targetProgress = 0;
      PB.layoutDirty = true;
    },
    robotTo(slot) {
      if (!disposed) PB.lifecycle.robotTo(slot);
    },
    completeDeferred(path) {
      if (path === "/") return;
      for (const key of ["context", "lattice", "links", "tree", "shaders"]) PB.boot.complete(key, "Home " + key + " deferred until first visit");
      if (!PB.robot) PB.boot.complete("robot", "Reviewer deferred until a view requests it");
    },
    dispose() {
      if (disposed) return;
      disposed = true;
      PB.disposed = true;
      PB.frames.length = 0;
      try { PB.lifecycle.disposeHero(); } catch (e) { console.warn("hero dispose", e); }
      const r = PB.robot;
      if (r) {
        try {
          r.renderer.dispose();
          r.renderer.forceContextLoss();
          r.renderer.domElement.replaceWith(r.renderer.domElement.cloneNode(false));
        } catch (e) { console.warn("robot dispose", e); }
      }
      for (const [t, type, fn, opts] of bucket) t.removeEventListener(type, fn, opts);
      bucket.length = 0;
      delete window.PB;
    },
  };
  return api;
}
