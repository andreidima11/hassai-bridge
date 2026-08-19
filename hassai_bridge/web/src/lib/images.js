import { apiUrl } from "./api.js";

export const MAX_CHAT_IMAGES = 4;
export const MAX_IMAGE_BYTES = 1_200_000;
const DRAFT_ATTACHMENTS_KEY = "hassai.chat.draftAttachments";

const ALLOWED_TYPES = new Set([
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/gif",
  "image/heic",
  "image/heif",
]);

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

export function isHaCompanionApp() {
  return /Home Assistant/i.test(navigator.userAgent || "");
}

export function useServerImageUpload() {
  return isHaCompanionApp();
}

export function readDraftAttachments() {
  try {
    const raw = sessionStorage.getItem(DRAFT_ATTACHMENTS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function persistDraftAttachments(items) {
  try {
    if (!items?.length) {
      sessionStorage.removeItem(DRAFT_ATTACHMENTS_KEY);
      return;
    }
    sessionStorage.setItem(
      DRAFT_ATTACHMENTS_KEY,
      JSON.stringify(
        items.map((item) => ({
          id: item.id,
          mime: item.mime,
          name: item.name,
          previewUrl: item.previewUrl,
          dataUrl: item.dataUrl,
        })),
      ),
    );
  } catch {
    /* quota or private mode */
  }
}

export function clearDraftAttachments() {
  try {
    sessionStorage.removeItem(DRAFT_ATTACHMENTS_KEY);
  } catch {
    /* ignore */
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

async function uploadImageFile(file) {
  const form = new FormData();
  form.append("file", file, file.name || "photo.jpg");
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
  const data = await resp.json();
  const previewUrl = data.url ? apiUrl(data.url) : data.dataUrl;
  return {
    id: data.id,
    name: data.name || file.name || "image",
    mime: data.mime || "image/jpeg",
    previewUrl,
    dataUrl: data.dataUrl || "",
  };
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
    previewUrl: dataUrl,
    dataUrl,
  };
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

export function buildUserContent(text, images) {
  const parts = [];
  const trimmed = String(text || "").trim();
  if (trimmed) parts.push({ type: "text", text: trimmed });
  for (const img of images || []) {
    if (img?.dataUrl) {
      parts.push({ type: "image_url", image_url: { url: img.dataUrl, detail: "auto" } });
    }
  }
  if (!parts.length) return null;
  if (parts.length === 1 && parts[0].type === "text") return parts[0].text;
  return parts;
}

export function canSendMessage(text, images) {
  return Boolean(String(text || "").trim()) || (images?.length || 0) > 0;
}
