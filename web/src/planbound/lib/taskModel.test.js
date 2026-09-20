import { describe, it, expect } from "vitest";
import { taskFacts, statusChip, robotStateOf, modeLabel } from "./taskModel";

const V = (address, verdict) => ({ address, verdict, changes: [], reason: "r" });
const task = (verdicts, extra = {}, stage = "evaluated") => ({ mode: "replay", stage, contract: { status: "confirmed" }, runs: verdicts ? [{ plan_hash: "h", verdicts, resolutions: {}, apply_result: null, ...extra }] : [] });

describe("task facts mirror the backend", () => {
  it("counts verdicts of the latest run", () => {
    expect(taskFacts(task([V("a", "ALLOW"), V("b", "REVIEW"), V("c", "DENY")])).counts).toEqual({ ALLOW: 1, REVIEW: 1, DENY: 1, EVALUATION_ERROR: 0 });
  });
  it("REVIEW is awaiting until the backend records a resolution", () => {
    const t = task([V("b", "REVIEW")]);
    expect(taskFacts(t).awaiting).toHaveLength(1);
    t.runs[0].resolutions = { b: "approve" };
    expect(taskFacts(t).awaiting).toHaveLength(0);
  });
  it("EVALUATION_ERROR is a fault, never waiting", () => {
    expect(robotStateOf(task([V("a", "EVALUATION_ERROR")]))).toBe("fault");
    expect(statusChip(task([V("a", "EVALUATION_ERROR")])).label).toBe("Evaluation error");
  });
  it("a DENY keeps the robot blocked even if REVIEW is approved", () => {
    expect(robotStateOf(task([V("a", "REVIEW"), V("b", "DENY")], { resolutions: { a: "approve" } }))).toBe("blocked");
  });
  it("labels replay and live modes distinctly", () => {
    expect(modeLabel("replay")).toBe("FIXTURE REPLAY");
    expect(modeLabel("ollama")).toBe("LIVE LOCAL MODEL");
  });
});
