export const MAX_CHAT_IMAGES = 4;
export const MAX_IMAGE_BYTES = 1_200_000;

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
  // Mobile pickers sometimes omit MIME type but still provide a decodable image.
  return !mime && Boolean(file?.size);
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

export async function prepareImageFile(file) {
  if (!file || !isAllowedImage(file)) {
    throw new Error("unsupported");
  }
  const mime = resolveImageMime(file) || "image/jpeg";
  if (file.size > MAX_IMAGE_BYTES * 2) {
    throw new Error("too_large");
  }
  let dataUrl = await readFileAsDataUrl(file);
  if (mime !== "image/gif") {
    dataUrl = await compressDataUrl(dataUrl, mime === "image/png" ? "image/png" : "image/jpeg");
  }
  const approxBytes = Math.ceil((dataUrl.length - dataUrl.indexOf(",") - 1) * 0.75);
  if (approxBytes > MAX_IMAGE_BYTES) {
    throw new Error("too_large");
  }
  return {
    id: crypto.randomUUID?.() || String(Date.now()),
    name: file.name || "image",
    mime: mime.startsWith("image/") ? mime : "image/jpeg",
    previewUrl: dataUrl,
    dataUrl,
  };
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
