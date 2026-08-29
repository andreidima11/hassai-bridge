import { apiUrl } from "./api.js";

export const MAX_CHAT_IMAGES = 4;
export const MAX_CHAT_ATTACHMENTS = MAX_CHAT_IMAGES;
export const MAX_IMAGE_BYTES = 1_200_000;
export const MAX_DOC_BYTES = 4_000_000;
const DRAFT_ATTACHMENTS_KEY = "hassai.chat.draftAttachments";

const ALLOWED_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "image/heic",
  "image/heif",
]);

const DOC_ACCEPT =
  ".pdf,.txt,.md,.markdown,.csv,.json,.xml,.html,.htm,.log,.rtf,application/pdf,text/plain,text/markdown,text/csv,application/json,text/html,application/xml,text/xml,application/rtf,text/rtf";

const DOC_EXT = new Set([
  ".pdf",
  ".txt",
  ".md",
  ".markdown",
  ".csv",
  ".json",
  ".xml",
  ".html",
  ".htm",
  ".log",
  ".rtf",
]);

export function documentAcceptAttr() {
  return DOC_ACCEPT;
}

function resolveImageMime(file) {
  const type = String(file?.type || "").trim().toLowerCase();
  if (ALLOWED_TYPES.has(type)) return type;
  const name = String(file?.name || "").trim().toLowerCase();
  if (name.endsWith(".heic")) return "image/heic";
  if (name.endsWith(".heif")) return "image/heif";
  if (name.endsWith(".jpg") || name.endsWith(".jpeg")) return "image/jpeg";
  if (name.endsWith(".png")) return "image/png";
  if (name.endsWith(".webp")) return "image/webp";
  if (name.endsWith(".gif")) return "image/gif";
  return type;
}

function isAllowedImage(file) {
  const mime = resolveImageMime(file);
  if (ALLOWED_TYPES.has(mime)) return true;
  if (!mime && Boolean(file?.size)) return true;
  if (mime.startsWith("image/") && Boolean(file?.size)) return true;
  if (mime === "application/octet-stream" && Boolean(file?.size)) return true;
  return false;
}

export function looksLikeImage(file) {
  const mime = String(file?.type || "").trim().toLowerCase();
  if (mime.startsWith("image/")) return true;
  const name = String(file?.name || "").trim().toLowerCase();
  return /\.(jpe?g|png|webp|gif|heic|heif)$/.test(name);
}

export function isHaCompanionApp() {
  return /Home Assistant/i.test(navigator.userAgent || "");
}

export function useServerImageUpload() {
  return isHaCompanionApp();
}

const DRAFT_MAX_CHARS = 2_000_000; // localStorage quota is ~5MB per origin

// localStorage, not sessionStorage: the Companion WebView can be restarted by the
// native file picker, which starts a brand new session.
function draftStores() {
  const stores = [];
  try {
    if (window.localStorage) stores.push(window.localStorage);
  } catch {
    /* blocked */
  }
  try {
    if (window.sessionStorage) stores.push(window.sessionStorage);
  } catch {
    /* blocked */
  }
  return stores;
}

export function readDraftAttachments() {
  for (const store of draftStores()) {
    try {
      const raw = store.getItem(DRAFT_ATTACHMENTS_KEY);
      if (!raw) continue;
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length) return parsed;
    } catch {
      continue;
    }
  }
  return [];
}

export function persistDraftAttachments(items) {
  const stores = draftStores();
  if (!items?.length) {
    for (const store of stores) {
      try {
        store.removeItem(DRAFT_ATTACHMENTS_KEY);
      } catch {
        /* ignore */
      }
    }
    return;
  }
  const slim = items.map((item) => ({
    id: item.id,
    mime: item.mime,
    name: item.name,
    kind: item.kind || (String(item.mime || "").startsWith("image/") ? "image" : "document"),
    previewUrl: item.previewUrl,
    // A stored file is re-fetchable by URL; keep the heavy data URL only when it is the only copy.
    dataUrl: item.previewUrl && item.previewUrl !== item.dataUrl ? "" : item.dataUrl,
    text: item.kind === "document" ? item.text : undefined,
    chars: item.chars,
  }));
  let payload = JSON.stringify(slim);
  if (payload.length > DRAFT_MAX_CHARS) {
    payload = JSON.stringify(slim.map((item) => ({ ...item, dataUrl: "", text: undefined })));
  }
  for (const store of stores) {
    try {
      store.setItem(DRAFT_ATTACHMENTS_KEY, payload);
    } catch {
      /* quota or private mode */
    }
  }
}

const DRAFT_TEXT_KEY = "hassai.chat.draftText";

export function readDraftText() {
  for (const store of draftStores()) {
    try {
      const text = store.getItem(DRAFT_TEXT_KEY);
      if (text) return text;
    } catch {
      continue;
    }
  }
  return "";
}

export function persistDraftText(text) {
  const value = String(text || "");
  for (const store of draftStores()) {
    try {
      if (value) store.setItem(DRAFT_TEXT_KEY, value);
      else store.removeItem(DRAFT_TEXT_KEY);
    } catch {
      /* quota or private mode */
    }
  }
}

export function clearDraftAttachments() {
  for (const store of draftStores()) {
    try {
      store.removeItem(DRAFT_ATTACHMENTS_KEY);
    } catch {
      /* ignore */
    }
  }
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("image load failed"));
    img.src = src;
  });
}

async function compressDataUrl(dataUrl, mimeHint = "image/jpeg") {
  const img = await loadImage(dataUrl);
  const maxDim = 1280;
  const scale = Math.min(1, maxDim / Math.max(img.width, img.height, 1));
  const width = Math.max(1, Math.round(img.width * scale));
  const height = Math.max(1, Math.round(img.height * scale));
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) return dataUrl;
  ctx.drawImage(img, 0, 0, width, height);
  const mime = mimeHint === "image/png" ? "image/png" : "image/jpeg";
  const quality = mime === "image/jpeg" ? 0.82 : undefined;
  return canvas.toDataURL(mime, quality);
}

async function compressWithBitmap(file, mimeHint = "image/jpeg") {
  if (typeof createImageBitmap !== "function") return null;
  let bitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    return null;
  }
  try {
    const maxDim = 1280;
    const scale = Math.min(1, maxDim / Math.max(bitmap.width, bitmap.height, 1));
    const width = Math.max(1, Math.round(bitmap.width * scale));
    const height = Math.max(1, Math.round(bitmap.height * scale));
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(bitmap, 0, 0, width, height);
    const outMime = mimeHint === "image/png" ? "image/png" : "image/jpeg";
    const quality = outMime === "image/jpeg" ? 0.82 : undefined;
    return { dataUrl: canvas.toDataURL(outMime, quality), mime: outMime };
  } finally {
    bitmap.close?.();
  }
}

async function uploadChatFile(file, fallbackName = "file") {
  const form = new FormData();
  form.append("file", file, file.name || fallbackName);
  const resp = await fetch(apiUrl("/api/chat/upload"), {
    method: "POST",
    credentials: "same-origin",
    body: form,
  });
  if (!resp.ok) {
    const errText = await resp.text().catch(() => "");
    try {
      const j = JSON.parse(errText);
      const msg = j?.error?.message || j?.error || j?.detail;
      throw new Error(msg || `HTTP ${resp.status}`);
    } catch (err) {
      if (err instanceof SyntaxError) {
        throw new Error(errText ? errText.slice(0, 240) : `HTTP ${resp.status}`);
      }
      throw err;
    }
  }
  return resp.json();
}

/** Map an /api/chat/upload or /api/chat/files/attach response to a draft attachment. */
export function attachmentFromServer(data, fallbackName = "") {
  if (data?.kind === "document") {
    const text = data.text || "";
    return {
      id: data.id,
      name: data.name || fallbackName || "document",
      mime: data.mime || "text/plain",
      kind: "document",
      text,
      chars: data.chars || text.length,
      previewUrl: data.url ? apiUrl(data.url) : "",
      dataUrl: "",
    };
  }
  return {
    id: data.id,
    name: data.name || fallbackName || "image",
    mime: data.mime || "image/jpeg",
    kind: "image",
    previewUrl: data.url ? apiUrl(data.url) : data.dataUrl,
    dataUrl: data.dataUrl || "",
  };
}

async function uploadImageFile(file) {
  const data = await uploadChatFile(file, "photo.jpg");
  return attachmentFromServer(data, file.name || "image");
}

async function prepareImageFileClient(file) {
  const mime = resolveImageMime(file) || "image/jpeg";
  if (file.size > MAX_IMAGE_BYTES * 2) {
    throw new Error("too_large");
  }

  let dataUrl;
  let outMime = mime.startsWith("image/") ? mime : "image/jpeg";

  if (mime === "image/gif") {
    dataUrl = await readFileAsDataUrl(file);
  } else {
    const bitmapResult = await compressWithBitmap(file, mime === "image/png" ? "image/png" : "image/jpeg");
    if (bitmapResult) {
      dataUrl = bitmapResult.dataUrl;
      outMime = bitmapResult.mime;
    } else {
      dataUrl = await readFileAsDataUrl(file);
      try {
        dataUrl = await compressDataUrl(dataUrl, mime === "image/png" ? "image/png" : "image/jpeg");
        outMime = mime === "image/png" ? "image/png" : "image/jpeg";
      } catch {
        if (mime !== "image/heic" && mime !== "image/heif") {
          throw new Error("unsupported");
        }
      }
    }
  }

  const approxBytes = Math.ceil((dataUrl.length - dataUrl.indexOf(",") - 1) * 0.75);
  if (approxBytes > MAX_IMAGE_BYTES) {
    throw new Error("too_large");
  }
  return {
    id: crypto.randomUUID?.() || String(Date.now()),
    name: file.name || "image",
    mime: outMime,
    kind: "image",
    previewUrl: dataUrl,
    dataUrl,
  };
}

function isAllowedDocument(file) {
  const name = String(file?.name || "").trim().toLowerCase();
  const mime = String(file?.type || "").trim().toLowerCase();
  if ([...DOC_EXT].some((ext) => name.endsWith(ext))) return true;
  if (mime.startsWith("text/")) return true;
  if (mime === "application/pdf" || mime === "application/json" || mime === "application/xml") return true;
  if (mime === "application/rtf" || mime === "text/rtf") return true;
  return false;
}

export async function prepareDocumentFile(file) {
  if (!file || !isAllowedDocument(file)) {
    throw new Error("unsupported");
  }
  if (file.size > MAX_DOC_BYTES) {
    throw new Error("too_large");
  }
  // Always server-side: extract text + store file (also survives Companion WebView reload).
  const data = await uploadChatFile(file, "document.txt");
  if (data.kind !== "document" && !data.text) {
    throw new Error("unsupported");
  }
  return attachmentFromServer(data, file.name || "document");
}

export async function prepareImageFile(file) {
  if (!file || !isAllowedImage(file)) {
    throw new Error("unsupported");
  }
  // Companion app WebView reloads the panel after the native picker — server upload + sessionStorage draft.
  if (useServerImageUpload()) {
    return uploadImageFile(file);
  }
  return prepareImageFileClient(file);
}

function formatDocBlock(att) {
  const id = String(att?.id || "").trim();
  const name = String(att?.name || "document").replace(/"/g, "'");
  const mime = String(att?.mime || "text/plain").replace(/"/g, "");
  const text = String(att?.text || "");
  if (!id || !text) return "";
  return `<<<HASSAI_DOC id="${id}" name="${name}" mime="${mime}">>>\n${text}\n<<<END_HASSAI_DOC>>>`;
}

export function buildUserContent(text, images) {
  const parts = [];
  const trimmed = String(text || "").trim();
  if (trimmed) parts.push({ type: "text", text: trimmed });
  const docs = [];
  for (const att of images || []) {
    if (att?.kind === "document" || (att?.text && !String(att?.mime || "").startsWith("image/"))) {
      const block = formatDocBlock(att);
      if (block) docs.push(block);
      continue;
    }
    if (att?.dataUrl) {
      parts.push({ type: "image_url", image_url: { url: att.dataUrl, detail: "auto" } });
    }
  }
  if (docs.length) parts.push({ type: "text", text: docs.join("\n\n") });
  if (!parts.length) return null;
  if (parts.length === 1 && parts[0].type === "text") return parts[0].text;
  return parts;
}

export function canSendMessage(text, images) {
  return Boolean(String(text || "").trim()) || (images?.length || 0) > 0;
}

export function isDocumentAttachment(item) {
  return item?.kind === "document" || (item?.text && !String(item?.mime || "").startsWith("image/"));
}

export function isVideoAttachment(item) {
  const mime = String(item?.mime || "").toLowerCase();
  return item?.kind === "video" || mime.startsWith("video/");
}

export function isImageAttachment(item) {
  if (isDocumentAttachment(item) || isVideoAttachment(item) || item?.kind === "audio") return false;
  const mime = String(item?.mime || "").toLowerCase();
  return !mime || mime.startsWith("image/");
}
