function mimeFromDataUrl(src) {
  return /data:([^;]+)/i.exec(String(src || ""))?.[1] || "";
}

function extFromMime(mime) {
  const type = String(mime || "").toLowerCase();
  if (type.includes("jpeg") || type.includes("jpg")) return "jpg";
  if (type.includes("png")) return "png";
  if (type.includes("webp")) return "webp";
  if (type.includes("gif")) return "gif";
  return "";
}

function extFromSrc(src) {
  const path = String(src || "").split("?")[0];
  const match = /\.(jpe?g|png|webp|gif)$/i.exec(path);
  if (!match) return "";
  return match[1].toLowerCase() === "jpeg" ? "jpg" : match[1].toLowerCase();
}

export function imageDownloadFilename(name, src, mime) {
  const raw = String(name || "").trim();
  if (/\.(jpe?g|png|webp|gif)$/i.test(raw)) {
    return raw.replace(/[^\w.-]+/g, "_") || "image.png";
  }
  const ext =
    extFromMime(mime) ||
    extFromMime(mimeFromDataUrl(src)) ||
    extFromSrc(src) ||
    "png";
  const base = (raw.replace(/\.[^.]+$/, "") || "image").replace(/[^\w.-]+/g, "_");
  return `${base || "image"}.${ext}`;
}

function dataUrlToBlob(dataUrl) {
  const [header, data] = String(dataUrl).split(",", 2);
  if (!data) throw new Error("invalid data url");
  const mime = mimeFromDataUrl(header) || "image/png";
  const binary = atob(data);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

async function blobFromSrc(src) {
  const url = String(src || "").trim();
  if (!url) throw new Error("missing image");
  if (url.startsWith("data:")) return dataUrlToBlob(url);
  if (url.startsWith("blob:")) {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return resp.blob();
  }
  const resp = await fetch(url, { credentials: "same-origin", cache: "no-store" });
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.blob();
}

async function saveWithPicker(blob, filename) {
  if (typeof window.showSaveFilePicker !== "function") return false;
  const ext = `.${String(filename).split(".").pop() || "png"}`;
  const mime = blob.type || "image/png";
  try {
    const handle = await window.showSaveFilePicker({
      suggestedName: filename,
      types: [{ description: "Image", accept: { [mime]: [ext] } }],
    });
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
    return true;
  } catch (err) {
    if (err?.name === "AbortError") return true;
    return false;
  }
}

function clickDownloadLink(blob, filename) {
  const objectUrl = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = objectUrl;
    a.download = filename;
    a.rel = "noopener";
    a.style.display = "none";
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(objectUrl), 4000);
  }
}

/** Ingress-safe image download: never navigate the iframe with a blob URL. */
export async function downloadImage(src, { name = "", mime = "" } = {}) {
  const filename = imageDownloadFilename(name, src, mime);
  const blob = await blobFromSrc(src);
  if (await saveWithPicker(blob, filename)) return;
  clickDownloadLink(blob, filename);
}
