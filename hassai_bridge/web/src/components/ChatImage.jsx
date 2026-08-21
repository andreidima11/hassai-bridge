import { useEffect, useId, useState } from "react";
import { createPortal } from "react-dom";
import { DownloadIcon, XIcon } from "./Icons.jsx";

async function downloadUrl(url, filename) {
  const name = filename || "image.jpg";
  try {
    const resp = await fetch(url, { credentials: "same-origin" });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const blob = await resp.blob();
    const href = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = href;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(href);
  } catch {
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.rel = "noopener";
    a.target = "_blank";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }
}

function filenameFromUrl(url) {
  try {
    const path = new URL(url, window.location.href).pathname;
    const base = path.split("/").pop() || "";
    if (/\.(jpe?g|png|webp|gif)$/i.test(base)) return base;
  } catch {
    /* ignore */
  }
  return `hassai-${Date.now()}.jpg`;
}

export function ChatImage({
  src,
  alt = "",
  className = "",
  downloadLabel = "Download",
  closeLabel = "Close",
  openLabel = "Open image",
}) {
  const [open, setOpen] = useState(false);
  const titleId = useId();
  const url = String(src || "").trim();

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!url) return null;

  return (
    <>
      <button
        type="button"
        className="group/img relative block max-w-full overflow-hidden rounded-[inherit] text-left"
        aria-label={openLabel}
        onClick={() => setOpen(true)}
      >
        <img alt={alt} className={className} src={url} loading="lazy" />
        <span className="pointer-events-none absolute inset-0 bg-black/0 transition-colors group-hover/img:bg-black/20" />
      </button>
      {open
        ? createPortal(
            <div
              className="fixed inset-0 z-[80] flex flex-col bg-black/85 backdrop-blur-sm"
              role="dialog"
              aria-modal="true"
              aria-labelledby={titleId}
              onClick={() => setOpen(false)}
            >
              <div
                className="flex shrink-0 items-center justify-between gap-3 px-4 py-3 text-white"
                onClick={(e) => e.stopPropagation()}
              >
                <p id={titleId} className="truncate text-sm text-white/70">
                  {alt || openLabel}
                </p>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    className="inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm text-white/85 hover:bg-white/10 hover:text-white"
                    onClick={() => downloadUrl(url, filenameFromUrl(url))}
                  >
                    <DownloadIcon size={15} />
                    {downloadLabel}
                  </button>
                  <button
                    type="button"
                    className="inline-flex size-9 items-center justify-center rounded-lg text-white/85 hover:bg-white/10 hover:text-white"
                    aria-label={closeLabel}
                    onClick={() => setOpen(false)}
                  >
                    <XIcon size={16} />
                  </button>
                </div>
              </div>
              <div className="flex min-h-0 flex-1 items-center justify-center p-3 md:p-6" onClick={() => setOpen(false)}>
                <img
                  alt={alt}
                  src={url}
                  className="max-h-full max-w-full object-contain shadow-2xl"
                  onClick={(e) => e.stopPropagation()}
                />
              </div>
            </div>,
            document.body,
          )
        : null}
    </>
  );
}
