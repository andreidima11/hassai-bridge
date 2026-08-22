import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { DownloadIcon, XIcon } from "./Icons.jsx";
import { downloadImage } from "../lib/downloadImage.js";
import { tr } from "../lib/i18n.js";

const MIN_SCALE = 1;
const MAX_SCALE = 4;

function touchDistance(touches) {
  const dx = touches[0].clientX - touches[1].clientX;
  const dy = touches[0].clientY - touches[1].clientY;
  return Math.hypot(dx, dy);
}

export function ImageLightbox({ src, alt = "", filename = "", mime = "", lang, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [scale, setScale] = useState(1);
  const scaleRef = useRef(1);
  const pinchStartDistRef = useRef(null);
  const pinchStartScaleRef = useRef(1);
  const viewportRef = useRef(null);

  const clampScale = useCallback((value) => {
    return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
  }, []);

  const applyScale = useCallback(
    (next) => {
      const clamped = clampScale(next);
      scaleRef.current = clamped;
      setScale(clamped);
    },
    [clampScale],
  );

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    const prevOverflow = document.body.style.overflow;
    const prevTouchAction = document.body.style.touchAction;
    document.body.style.overflow = "hidden";
    document.body.style.touchAction = "none";

    const meta = document.querySelector('meta[name="viewport"]');
    const prevViewport = meta?.getAttribute("content") ?? "";
    if (meta) {
      meta.setAttribute(
        "content",
        "width=device-width, initial-scale=1, maximum-scale=1, user-scalable=no, viewport-fit=cover",
      );
    }

    window.addEventListener("keydown", onKey);

    const blockGesture = (event) => event.preventDefault();
    document.addEventListener("gesturestart", blockGesture, { passive: false });
    document.addEventListener("gesturechange", blockGesture, { passive: false });
    document.addEventListener("gestureend", blockGesture, { passive: false });

    return () => {
      document.body.style.overflow = prevOverflow;
      document.body.style.touchAction = prevTouchAction;
      if (meta && prevViewport) meta.setAttribute("content", prevViewport);
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("gesturestart", blockGesture);
      document.removeEventListener("gesturechange", blockGesture);
      document.removeEventListener("gestureend", blockGesture);
    };
  }, [onClose]);

  useEffect(() => {
    const el = viewportRef.current;
    if (!el) return;

    const onTouchMove = (event) => {
      if (event.touches.length !== 2) return;
      event.preventDefault();
      const dist = touchDistance(event.touches);
      if (!pinchStartDistRef.current) {
        pinchStartDistRef.current = dist;
        pinchStartScaleRef.current = scaleRef.current;
        return;
      }
      const ratio = dist / pinchStartDistRef.current;
      applyScale(pinchStartScaleRef.current * ratio);
    };

    const endPinch = () => {
      pinchStartDistRef.current = null;
    };

    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", endPinch);
    el.addEventListener("touchcancel", endPinch);
    return () => {
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", endPinch);
      el.removeEventListener("touchcancel", endPinch);
    };
  }, [applyScale]);

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
      className="fixed inset-0 z-[80] flex touch-none flex-col"
      role="dialog"
      aria-modal="true"
      aria-label={tr(lang, "enlargeImage")}
    >
      <div className="absolute inset-0 overflow-hidden" aria-hidden="true">
        <img
          alt=""
          className="absolute inset-0 size-full scale-110 object-cover opacity-35 blur-2xl saturate-50"
          src={src}
        />
        <div className="absolute inset-0 bg-black/72 backdrop-blur-md" />
      </div>

      <div className="relative z-[1] flex shrink-0 items-center justify-end gap-2 px-3 pb-2 pt-[max(0.75rem,env(safe-area-inset-top))] pr-[max(0.75rem,env(safe-area-inset-right))]">
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
        ref={viewportRef}
        className="relative z-[1] flex min-h-0 flex-1 touch-none items-center justify-center px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
        onClick={onClose}
      >
        <img
          alt={alt || ""}
          className="max-h-full max-w-full origin-center object-contain select-none shadow-[0_24px_80px_-12px_rgba(0,0,0,0.65)] transition-transform duration-75 ease-out will-change-transform"
          src={src}
          style={{ transform: `scale(${scale})` }}
          onClick={(event) => event.stopPropagation()}
          onTouchStart={(event) => {
            if (event.touches.length === 2) {
              pinchStartDistRef.current = touchDistance(event.touches);
              pinchStartScaleRef.current = scaleRef.current;
            }
          }}
          draggable={false}
        />
      </div>
    </div>,
    document.body,
  );
}
