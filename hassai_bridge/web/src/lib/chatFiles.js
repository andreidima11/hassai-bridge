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

export function baseName(path) {
  const parts = String(path || "").split("/").filter(Boolean);
  return parts.length ? parts[parts.length - 1] : String(path || "");
}
