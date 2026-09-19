import { describe, it, expect, vi } from "vitest";
import { request, api, ApiError, describeError, normalizeErrorBody } from "./api";

const resp = (status, body, { json = true } = {}) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => (body === undefined ? "" : json ? JSON.stringify(body) : body),
});
const f = (r) => vi.fn(async () => r);
const fail = async (p) => {
  try {
    await p;
  } catch (e) {
    return e;
  }
  throw new Error("expected rejection");
};

describe("success", () => {
  it("parses JSON and uses relative /api", async () => {
    const fetchImpl = f(resp(200, { status: "ok" }));
    expect(await request("/health", { fetchImpl })).toEqual({ status: "ok" });
    expect(fetchImpl.mock.calls[0][0]).toBe("/api/health");
  });
  it("returns null for empty 2xx", async () => {
    expect(await request("/x", { fetchImpl: f(resp(204)) })).toBeNull();
  });
  it("sends JSON body on POST", async () => {
    const fetchImpl = f(resp(200, {}));
    await request("/tasks", { method: "POST", body: { a: 1 }, fetchImpl });
    const init = fetchImpl.mock.calls[0][1];
    expect(init.method).toBe("POST");
    expect(init.body).toBe('{"a":1}');
  });
});

describe("error shapes", () => {
  it("structured PlanReviewError", async () => {
    const e = await fail(
      request("/tasks", {
        fetchImpl: f(
          resp(400, { detail: { error: "UNSUPPORTED_OPERATION", message: "Nope", details: { k: 1 } } }),
        ),
      }),
    );
    expect(e).toBeInstanceOf(ApiError);
    expect(e).toMatchObject({ code: "UNSUPPORTED_OPERATION", message: "Nope", details: { k: 1 }, status: 400 });
  });
  it("model unavailable keeps its code", async () => {
    const e = await fail(
      request("/tasks", {
        fetchImpl: f(resp(503, { detail: { error: "MODEL_UNAVAILABLE", message: "Ollama down", details: {} } })),
      }),
    );
    expect(e.code).toBe("MODEL_UNAVAILABLE");
  });
  it("legacy string detail 409 -> INVALID_STATE", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(409, { detail: "Run already applied" })) }));
    expect(e).toMatchObject({ code: "INVALID_STATE", message: "Run already applied", status: 409 });
  });
  it("legacy 503 -> PIPELINE_INCOMPLETE", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(503, { detail: "Pipeline incomplete: boom" })) }));
    expect(e.code).toBe("PIPELINE_INCOMPLETE");
  });
  it("pydantic 422 list", async () => {
    const e = await fail(
      request("/x", {
        fetchImpl: f(resp(422, { detail: [{ loc: ["body", "task"], msg: "String should have at least 1 character", type: "x" }] })),
      }),
    );
    expect(e.code).toBe("VALIDATION_ERROR");
    expect(e.message).toBe("task: String should have at least 1 character");
  });
  it("origin block 403", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(403, { detail: "Cross-origin mutation blocked" })) }));
    expect(e).toMatchObject({ code: "FORBIDDEN", status: 403 });
  });
  it("unknown route 404", async () => {
    const e = await fail(request("/nope", { fetchImpl: f(resp(404, { detail: "Not Found" })) }));
    expect(e).toMatchObject({ code: "NOT_FOUND", message: "Not Found" });
  });
  it("proxy 502 with empty body -> BACKEND_UNAVAILABLE", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(502)) }));
    expect(e.code).toBe("BACKEND_UNAVAILABLE");
  });
  it("proxy 500 with empty body (Vite, backend down) -> BACKEND_UNAVAILABLE", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(500)) }));
    expect(e.code).toBe("BACKEND_UNAVAILABLE");
  });
  it("non-JSON HTML error does not leak markup", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(500, "<html>boom</html>", { json: false })) }));
    expect(e.message).toBe("Request failed (HTTP 500)");
  });
  it("plain-text error body is kept", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(400, "Invalid host header", { json: false })) }));
    expect(e.message).toBe("Invalid host header (HTTP 400)");
  });
  it("non-JSON 200 is INVALID_RESPONSE, not success", async () => {
    const e = await fail(request("/x", { fetchImpl: f(resp(200, "<html></html>", { json: false })) }));
    expect(e.code).toBe("INVALID_RESPONSE");
  });
  it("never yields [object Object]", () => {
    const e = normalizeErrorBody(400, { detail: { error: "X", message: { a: 1 } } });
    expect(e.message).not.toContain("[object Object]");
    expect(describeError({ message: { a: 1 } })).not.toContain("[object Object]");
    expect(describeError(new ApiError("X", "msg"))).toBe("msg [X]");
  });
});

describe("transport failures", () => {
  it("network failure", async () => {
    const e = await fail(request("/x", { fetchImpl: vi.fn(async () => { throw new TypeError("Failed to fetch"); }) }));
    expect(e.code).toBe("NETWORK_ERROR");
  });
  it("timeout warns backend may still run for POST", async () => {
    const fetchImpl = vi.fn((_u, { signal }) => new Promise((_, rej) => signal.addEventListener("abort", () => rej(Object.assign(new Error("a"), { name: "AbortError" })))));
    const e = await fail(request("/x", { method: "POST", body: {}, timeoutMs: 10, fetchImpl }));
    expect(e.code).toBe("TIMEOUT");
    expect(e.message).toMatch(/may still be running/);
    expect(e.message).not.toMatch(/cancel/i);
  });
  it("caller abort never claims cancellation", async () => {
    const ctl = new AbortController();
    const fetchImpl = vi.fn((_u, { signal }) => new Promise((_, rej) => signal.addEventListener("abort", () => rej(Object.assign(new Error("a"), { name: "AbortError" })))));
    const p = request("/x", { method: "POST", body: {}, signal: ctl.signal, fetchImpl });
    ctl.abort();
    const e = await fail(p);
    expect(e.code).toBe("ABORTED");
    expect(e.message).toMatch(/may still be running/);
    expect(e.message).not.toMatch(/cancelled/i);
  });
  it("GET abort has no backend-running warning", async () => {
    const ctl = new AbortController();
    ctl.abort();
    const fetchImpl = vi.fn(async (_u, { signal }) => { if (signal.aborted) throw Object.assign(new Error("a"), { name: "AbortError" }); });
    const e = await fail(request("/x", { signal: ctl.signal, fetchImpl }));
    expect(e.code).toBe("ABORTED");
    expect(e.message).not.toMatch(/may still/);
  });
});

describe("no automatic retry", () => {
  it("failed POST is sent exactly once", async () => {
    const fetchImpl = vi.fn(async () => { throw new TypeError("x"); });
    await fail(request("/tasks", { method: "POST", body: {}, fetchImpl }));
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });
});

describe("endpoint helpers", () => {
  it("encode ids and paths", async () => {
    const spy = vi.spyOn(globalThis, "fetch").mockImplementation(async () => resp(200, {}));
    await api.runAgent("a/b", "poisoned");
    expect(spy.mock.calls[0][0]).toBe("/api/tasks/a%2Fb/agent?variant=poisoned");
    await api.createTask("t", "replay");
    expect(JSON.parse(spy.mock.calls[1][1].body)).toEqual({ task: "t", mode: "replay" });
    spy.mockRestore();
  });
});
