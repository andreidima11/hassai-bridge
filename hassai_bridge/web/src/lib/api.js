import { buildUserContent } from "./images.js";

const API = (typeof window.HASSAI_BASE === "string" ? window.HASSAI_BASE : "").replace(/\/$/, "");
export const ON_INGRESS = /\/api\/hassio_ingress\//.test(API || location.pathname);

export function apiUrl(path) {
  return API + path;
}

/** Resolve chat media and API paths for HA Ingress (relative /api/... URLs). */
export function resolveMediaUrl(src) {
  const raw = String(src || "").trim();
  if (!raw) return raw;
  if (raw.startsWith("/api/") || raw.startsWith("/v1/")) return apiUrl(raw);
  return raw;
}

export async function apiJson(path, opts = {}) {
  const resp = await fetch(API + path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!resp.ok) throw new Error(await readError(resp));
  if (resp.status === 204) return {};
  return resp.json();
}

export async function readError(resp) {
  const errText = await resp.text().catch(() => "");
  try {
    const j = JSON.parse(errText);
    return j?.error?.message || j?.detail || `HTTP ${resp.status}`;
  } catch {
    if (/^\s*</.test(errText) || /<!doctype/i.test(errText)) {
      if (resp.status === 504 || resp.status === 502 || resp.status === 524) {
        return (
          `HTTP ${resp.status}: gateway timeout while waiting for the model ` +
          `(common with Grok Imagine under HA Ingress). ` +
          `If you asked for an image, refresh this chat — it may already be saved.`
        );
      }
      return `HTTP ${resp.status}: server returned HTML instead of JSON. Check provider URL and API key.`;
    }
    return errText ? errText.slice(0, 240) : `HTTP ${resp.status}`;
  }
}

export function extractText(payload) {
  const choice = payload?.choices?.[0] || {};
  const delta = choice.delta || {};
  const msg = choice.message || {};
  return delta.content || msg.content || payload?.error?.message || "";
}

export function newId() {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

export function ensureFreshBuild(serverBuild) {
  const local = typeof window.HASSAI_BUILD === "string" ? window.HASSAI_BUILD : "";
  if (!serverBuild || !local || serverBuild === local) return;
  try {
    const u = new URL(location.href);
    if (u.searchParams.get("_b") === serverBuild) return;
    u.searchParams.set("_b", serverBuild);
    location.replace(u.href);
  } catch {
    /* ignore */
  }
}

export function cancelChat(traceId) {
  return apiJson(`/v1/chat/cancel/${encodeURIComponent(traceId)}`, { method: "POST" });
}

export function traceStoreKey(username) {
  return `hassai.chat.trace.${username || "default"}`;
}

export function persistPendingTrace(username, traceId, sessionId) {
  try {
    if (!traceId) {
      localStorage.removeItem(traceStoreKey(username));
      return;
    }
    localStorage.setItem(
      traceStoreKey(username),
      JSON.stringify({ traceId, sessionId: sessionId || "", ts: Date.now() }),
    );
  } catch {
    /* ignore */
  }
}

export function readPendingTrace(username) {
  try {
    const raw = localStorage.getItem(traceStoreKey(username));
    if (!raw) return null;
    const data = JSON.parse(raw);
    if (!data?.traceId) return null;
    return data;
  } catch {
    return null;
  }
}

export function clearPendingTrace(username) {
  persistPendingTrace(username, "", "");
}

export function postChat(stream, payload, sessionId, traceId, signal, thinkingMode, options = {}) {
  const content = typeof payload === "string" ? payload : buildUserContent(payload?.text, payload?.images);
  if (content == null || content === "") {
    return Promise.reject(new Error("empty message"));
  }
  const body = {
    messages: [{ role: "user", content }],
    stream: Boolean(stream) && !options.background,
    session_id: sessionId,
    trace_id: traceId,
  };
  if (options.background) body.background = true;
  if (thinkingMode) body.thinking = thinkingMode;
  return fetch(API + "/v1/chat/completions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify(body),
  });
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Poll activity until the background job finishes.
 * Live tokens arrive as name:"assistant" events (Ingress-safe).
 */
export async function waitForChatJob(traceId, { onActivity, onDelta, signal } = {}) {
  let after = -1;
  let full = "";
  const seen = new Set();
  while (true) {
    if (signal?.aborted) throw new DOMException("Aborted", "AbortError");
    let data;
    try {
      data = await apiJson(`/v1/chat/activity/${encodeURIComponent(traceId)}?after=${after}`, {
        signal,
      });
    } catch (err) {
      if (signal?.aborted || err?.name === "AbortError") throw err;
      await sleep(ON_INGRESS ? 320 : 400, signal);
      continue;
    }
    for (const ev of data.events || []) {
      if (typeof ev?.i === "number") {
        if (seen.has(ev.i)) continue;
        seen.add(ev.i);
      }
      if (ev?.name === "assistant" && typeof ev.detail === "string" && ev.detail) {
        full = ev.detail;
        onDelta?.(full);
        continue;
      }
      onActivity?.(ev);
    }
    if (typeof data.after === "number") after = data.after;
    if (data.cancelled) throw new DOMException("Aborted", "AbortError");
    if (data.done) {
      if (data.error) throw new Error(data.error);
      return full;
    }
    if (data.status === "error" && data.error) throw new Error(data.error);
    await sleep(ON_INGRESS ? 220 : 280, signal);
  }
}

/** Start a server-side job that keeps running if the panel is closed. */
export async function completeBackground(payload, sessionId, traceId, onActivity, onDelta, signal, thinkingMode) {
  const resp = await postChat(false, payload, sessionId, traceId, signal, thinkingMode, { background: true });
  if (!resp.ok) throw new Error(await readError(resp));
  const data = await resp.json().catch(() => ({}));
  if (data?.hassai_cancelled) throw new DOMException("Aborted", "AbortError");
  return waitForChatJob(traceId, { onActivity, onDelta, signal });
}

export function startActivityPoll(traceId, onEvent) {
  let after = -1;
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    try {
      const data = await apiJson(`/v1/chat/activity/${encodeURIComponent(traceId)}?after=${after}`);
      for (const ev of data.events || []) onEvent(ev);
      if (typeof data.after === "number") after = data.after;
      if (data.done || data.cancelled) return;
    } catch {
      /* retry */
    }
    if (!stopped) setTimeout(tick, ON_INGRESS ? 240 : 320);
  };
  tick();
  return () => {
    stopped = true;
  };
}
