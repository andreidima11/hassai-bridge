import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { DownloadIcon, XIcon } from "./Icons.jsx";
import { downloadImage } from "../lib/downloadImage.js";
import { tr } from "../lib/i18n.js";

export function ImageLightbox({ src, alt = "", filename = "", mime = "", lang, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prevOverflow;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const handleDownload = async () => {
    setError("");
    setBusy(true);
    try {
      await downloadImage(src, { name: filename, mime });
    } catch {
      setError(tr(lang, "downloadFailed"));
    } finally {
      setBusy(false);
    }
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex flex-col bg-black/92"
      role="dialog"
      aria-modal="true"
      aria-label={tr(lang, "enlargeImage")}
    >
      <div className="flex shrink-0 items-center justify-end gap-2 px-3 pb-2 pt-[max(0.75rem,env(safe-area-inset-top))] pr-[max(0.75rem,env(safe-area-inset-right))]">
        {error ? <span className="mr-auto text-[13px] text-amber-300">{error}</span> : null}
        <button
          type="button"
          className="grid size-10 place-items-center rounded-full bg-white/10 text-white hover:bg-white/20 disabled:opacity-50"
          aria-label={tr(lang, "downloadImage")}
          title={tr(lang, "downloadImage")}
          disabled={busy}
          onClick={handleDownload}
        >
          <DownloadIcon />
        </button>
        <button
          type="button"
          className="grid size-10 place-items-center rounded-full bg-white/10 text-white hover:bg-white/20"
          aria-label={tr(lang, "closeImage")}
          title={tr(lang, "closeImage")}
          onClick={onClose}
        >
          <XIcon size={18} />
        </button>
      </div>
      <div
        className="flex min-h-0 flex-1 cursor-zoom-out items-center justify-center px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
        onClick={onClose}
      >
        <img
          alt={alt || ""}
          className="max-h-full max-w-full cursor-default touch-pinch-zoom object-contain select-none"
          src={src}
          onClick={(event) => event.stopPropagation()}
        />
      </div>
    </div>,
    document.body,
  );
}
