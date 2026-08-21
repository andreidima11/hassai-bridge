import { apiUrl } from "./api.js";

async function readError(resp) {
  const text = await resp.text().catch(() => "");
  try {
    const data = JSON.parse(text);
    return data?.error || data?.detail || `HTTP ${resp.status}`;
  } catch {
    return text ? text.slice(0, 200) : `HTTP ${resp.status}`;
  }
}

export async function listChatFiles(path = "", kind = "") {
  const params = new URLSearchParams();
  if (path) params.set("path", path);
  if (kind) params.set("kind", kind);
  const query = params.toString();
  const resp = await fetch(apiUrl(`/api/chat/files${query ? `?${query}` : ""}`), {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

export async function attachChatFile(path) {
  const resp = await fetch(apiUrl("/api/chat/files/attach"), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

const LINK_KEY = "hassai.chat.uploadLink";

export async function createUploadLink() {
  const resp = await fetch(apiUrl("/api/chat/upload-link"), {
    method: "POST",
    credentials: "same-origin",
  });
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

export async function fetchUploadLinkFiles(token) {
  const resp = await fetch(apiUrl(`/api/chat/upload-link/${encodeURIComponent(token)}`), {
    credentials: "same-origin",
    cache: "no-store",
  });
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

/** Keep the link across a WebView restart so files sent from the browser still land. */
export function rememberUploadLink(link) {
  try {
    if (!link?.token) localStorage.removeItem(LINK_KEY);
    else localStorage.setItem(LINK_KEY, JSON.stringify({ ...link, at: Date.now() }));
  } catch {
    /* ignore */
  }
}

export function readUploadLink() {
  try {
    const raw = localStorage.getItem(LINK_KEY);
    if (!raw) return null;
    const link = JSON.parse(raw);
    const ageMs = Date.now() - Number(link?.at || 0);
    if (!link?.token || ageMs > (Number(link.expires_in) || 900) * 1000) {
      localStorage.removeItem(LINK_KEY);
      return null;
    }
    return link;
  } catch {
    return null;
  }
}

export function baseName(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : String(path || "");
}
