// Single HTTP client for the PlanReview backend. All requests use relative
// /api paths: Vite proxies them to FastAPI in development.
//
// Every failure is thrown as ApiError with a stable shape:
//   { code, message, details, status }
// A failed request is never converted into a success value, and mutating
// requests are never retried automatically.

export class ApiError extends Error {
  constructor(code, message, { details = null, status = null } = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
    this.status = status;
  }
}

const BASE = "/api";
export const DEFAULT_TIMEOUT_MS = 30_000;
// Terraform / agent stages may legitimately run for minutes.
export const LONG_TIMEOUT_MS = 15 * 60_000;

const NOT_STOPPED =
  " The backend may still be running this operation; check the task state before retrying.";

const STATUS_CODES = {
  400: "BAD_REQUEST",
  403: "FORBIDDEN",
  404: "NOT_FOUND",
  409: "INVALID_STATE",
  422: "VALIDATION_ERROR",
};

function text(v) {
  if (typeof v === "string") return v;
  if (v === null || v === undefined) return "";
  try {
    return JSON.stringify(v);
  } catch {
    return String(v);
  }
}

// Normalize the error shapes the backend emits:
//   structured: { detail: { error, message, details } }   (PlanReviewError)
//   legacy:     { detail: "message" }                     (ValueError, 503, 403, 404)
//   pydantic:   { detail: [ { loc, msg, type }, ... ] }   (422)
export function normalizeErrorBody(status, body, rawText = "") {
  const detail = body && typeof body === "object" ? body.detail : undefined;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    if (detail.error || detail.message) {
      return new ApiError(
        detail.error || STATUS_CODES[status] || "HTTP_ERROR",
        text(detail.message) || `Request failed (HTTP ${status})`,
        { details: detail.details ?? null, status },
      );
    }
  }
  if (Array.isArray(detail)) {
    const lines = detail.map((d) => {
      const where = Array.isArray(d?.loc)
        ? d.loc.filter((p) => p !== "body").join(".")
        : "";
      return where ? `${where}: ${text(d?.msg)}` : text(d?.msg ?? d);
    });
    return new ApiError("VALIDATION_ERROR", lines.join("; ") || "Invalid request", {
      details: detail,
      status,
    });
  }
  if (typeof detail === "string" && detail) {
    let code = STATUS_CODES[status] || "HTTP_ERROR";
    if (status === 503) code = "PIPELINE_INCOMPLETE";
    return new ApiError(code, detail, { status });
  }
  // The Vite proxy answers with an empty-body 500/502/503/504 when FastAPI is down.
  if ([500, 502, 503, 504].includes(status) && !rawText.trim()) {
    return new ApiError(
      "BACKEND_UNAVAILABLE",
      "The PlanReview backend is not reachable. Start FastAPI on 127.0.0.1:8000.",
      { status },
    );
  }
  const snippet = rawText.trim().slice(0, 200);
  return new ApiError(
    STATUS_CODES[status] || "HTTP_ERROR",
    snippet && !snippet.startsWith("<")
      ? `${snippet} (HTTP ${status})`
      : `Request failed (HTTP ${status})`,
    { status },
  );
}

/**
 * request(path, { method, body, timeoutMs, signal, fetchImpl })
 * Resolves with parsed JSON (or null for an empty 2xx body).
 */
export async function request(
  path,
  { method = "GET", body, timeoutMs = DEFAULT_TIMEOUT_MS, signal, fetchImpl } = {},
) {
  const doFetch = fetchImpl || globalThis.fetch.bind(globalThis);
  const controller = new AbortController();
  let timedOut = false;
  const timer = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const onAbort = () => controller.abort();
  if (signal) {
    if (signal.aborted) controller.abort();
    else signal.addEventListener("abort", onAbort, { once: true });
  }
  const mutating = method !== "GET";
  try {
    let response;
    try {
      response = await doFetch(BASE + path, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
      });
    } catch (e) {
      if (timedOut) {
        throw new ApiError(
          "TIMEOUT",
          `No response within ${Math.round(timeoutMs / 1000)}s.` +
            (mutating ? NOT_STOPPED : ""),
        );
      }
      if (e?.name === "AbortError" || controller.signal.aborted) {
        throw new ApiError(
          "ABORTED",
          "The request was abandoned in the browser." + (mutating ? NOT_STOPPED : ""),
        );
      }
      throw new ApiError(
        "NETWORK_ERROR",
        "Could not reach the PlanReview backend. Is FastAPI running on 127.0.0.1:8000?",
      );
    }

    let raw = "";
    try {
      raw = await response.text();
    } catch {
      throw new ApiError(
        timedOut ? "TIMEOUT" : "NETWORK_ERROR",
        "The response was interrupted before it completed." +
          (mutating ? NOT_STOPPED : ""),
        { status: response.status },
      );
    }
    let parsed;
    let isJson = false;
    if (raw.trim()) {
      try {
        parsed = JSON.parse(raw);
        isJson = true;
      } catch {
        isJson = false;
      }
    }
    if (!response.ok) throw normalizeErrorBody(response.status, isJson ? parsed : null, raw);
    if (!raw.trim()) return null;
    if (!isJson) {
      throw new ApiError(
        "INVALID_RESPONSE",
        "The server returned a non-JSON response. The /api proxy may be misconfigured.",
        { status: response.status },
      );
    }
    return parsed;
  } finally {
    clearTimeout(timer);
    if (signal) signal.removeEventListener("abort", onAbort);
  }
}

const post = (path, body = {}, opts = {}) =>
  request(path, { method: "POST", body, ...opts });

const enc = encodeURIComponent;

export const api = {
  health: (o) => request("/health", o),
  listTasks: (o) => request("/tasks", o),
  getTask: (id, o) => request(`/tasks/${enc(id)}`, o),
  getAudit: (id, o) => request(`/tasks/${enc(id)}/audit`, o),
  // Mutating calls: never auto-retried.
  createTask: (task, mode, o) =>
    post("/tasks", { task, mode }, { timeoutMs: LONG_TIMEOUT_MS, ...o }),
  confirm: (id, contract, o) => post(`/tasks/${enc(id)}/confirm`, contract, o),
  runAgent: (id, variant, o) =>
    post(`/tasks/${enc(id)}/agent?variant=${enc(variant)}`, {}, { timeoutMs: LONG_TIMEOUT_MS, ...o }),
  plan: (id, o) =>
    post(`/tasks/${enc(id)}/plan`, {}, { timeoutMs: LONG_TIMEOUT_MS, ...o }),
  canonicalize: (id, o) => post(`/tasks/${enc(id)}/canonicalize`, {}, o),
  evaluate: (id, o) => post(`/tasks/${enc(id)}/evaluate`, {}, o),
  resolve: (id, decisions, o) => post(`/tasks/${enc(id)}/resolve`, decisions, o),
  apply: (id, o) => post(`/tasks/${enc(id)}/apply`, {}, o),
};

// Render any thrown value as a readable string (never "[object Object]").
export function describeError(e) {
  if (e instanceof ApiError) {
    return e.code && !["HTTP_ERROR", "BAD_REQUEST"].includes(e.code)
      ? `${e.message} [${e.code}]`
      : e.message;
  }
  return text(e?.message ?? e) || "Unexpected error";
}
