const API = (typeof window.HASSAI_BASE === "string" ? window.HASSAI_BASE : "").replace(/\/$/, "");
export const ON_INGRESS = /\/api\/hassio_ingress\//.test(API || location.pathname);

export function apiUrl(path) {
  return API + path;
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

export function postChat(stream, userText, sessionId, traceId, signal) {
  return fetch(API + "/v1/chat/completions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    signal,
    body: JSON.stringify({
      messages: [{ role: "user", content: userText }],
      stream,
      session_id: sessionId,
      trace_id: traceId,
    }),
  });
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
