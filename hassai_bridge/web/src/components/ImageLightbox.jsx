import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { DownloadIcon, XIcon } from "./Icons.jsx";
import { downloadImage } from "../lib/downloadImage.js";
import { tr } from "../lib/i18n.js";

const MIN_SCALE = 1;
const MAX_SCALE = 4;
// Movement past this many pixels is a drag, not a tap, so it must not close.
const DRAG_SLOP = 4;

function touchDistance(touches) {
  const dx = touches[0].clientX - touches[1].clientX;
  const dy = touches[0].clientY - touches[1].clientY;
  return Math.hypot(dx, dy);
}

export function ImageLightbox({ src, alt = "", filename = "", mime = "", lang, onClose }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const scaleRef = useRef(1);
  const offsetRef = useRef({ x: 0, y: 0 });
  const pinchStartDistRef = useRef(null);
  const pinchStartScaleRef = useRef(1);
  const dragStartRef = useRef(null);
  const movedRef = useRef(false);
  const viewportRef = useRef(null);
  const imageRef = useRef(null);

  const clampScale = useCallback((value) => {
    return Math.min(MAX_SCALE, Math.max(MIN_SCALE, value));
  }, []);

  // How far the image may travel before its edge would come inside the frame.
  const clampOffset = useCallback((x, y, atScale) => {
    const image = imageRef.current;
    const viewport = viewportRef.current;
    if (!image || !viewport) return { x: 0, y: 0 };
    const frame = viewport.getBoundingClientRect();
    const maxX = Math.max(0, (image.offsetWidth * atScale - frame.width) / 2);
    const maxY = Math.max(0, (image.offsetHeight * atScale - frame.height) / 2);
    return {
      x: Math.min(maxX, Math.max(-maxX, x)),
      y: Math.min(maxY, Math.max(-maxY, y)),
    };
  }, []);

  const applyOffset = useCallback(
    (x, y, atScale) => {
      const next = clampOffset(x, y, atScale ?? scaleRef.current);
      offsetRef.current = next;
      setOffset(next);
    },
    [clampOffset],
  );

  const applyScale = useCallback(
    (next) => {
      const clamped = clampScale(next);
      scaleRef.current = clamped;
      setScale(clamped);
      if (clamped <= MIN_SCALE) {
        offsetRef.current = { x: 0, y: 0 };
        setOffset({ x: 0, y: 0 });
      } else {
        // Zooming out can leave the image parked outside its new bounds.
        applyOffset(offsetRef.current.x, offsetRef.current.y, clamped);
      }
    },
    [applyOffset, clampScale],
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
      if (event.touches.length === 2) {
        event.preventDefault();
        const dist = touchDistance(event.touches);
        if (!pinchStartDistRef.current) {
          pinchStartDistRef.current = dist;
          pinchStartScaleRef.current = scaleRef.current;
          return;
        }
        applyScale(pinchStartScaleRef.current * (dist / pinchStartDistRef.current));
        return;
      }

      // One finger drags the image once it is bigger than the frame.
      if (event.touches.length !== 1 || scaleRef.current <= MIN_SCALE) return;
      const start = dragStartRef.current;
      if (!start) return;
      event.preventDefault();
      const dx = event.touches[0].clientX - start.x;
      const dy = event.touches[0].clientY - start.y;
      if (Math.hypot(dx, dy) > DRAG_SLOP) movedRef.current = true;
      applyOffset(start.ox + dx, start.oy + dy);
    };

    const onTouchStart = (event) => {
      if (event.touches.length === 2) {
        pinchStartDistRef.current = touchDistance(event.touches);
        pinchStartScaleRef.current = scaleRef.current;
        dragStartRef.current = null;
        return;
      }
      if (event.touches.length === 1) {
        movedRef.current = false;
        dragStartRef.current = {
          x: event.touches[0].clientX,
          y: event.touches[0].clientY,
          ox: offsetRef.current.x,
          oy: offsetRef.current.y,
        };
      }
    };

    const endTouch = () => {
      pinchStartDistRef.current = null;
      dragStartRef.current = null;
    };

    // React registers wheel listeners passively at the root, so preventDefault
    // from an onWheel prop is refused and logs an error on every notch.
    const onWheel = (event) => {
      event.preventDefault();
      applyScale(scaleRef.current * (event.deltaY < 0 ? 1.12 : 1 / 1.12));
    };

    el.addEventListener("touchstart", onTouchStart, { passive: false });
    el.addEventListener("touchmove", onTouchMove, { passive: false });
    el.addEventListener("touchend", endTouch);
    el.addEventListener("touchcancel", endTouch);
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      el.removeEventListener("touchstart", onTouchStart);
      el.removeEventListener("touchmove", onTouchMove);
      el.removeEventListener("touchend", endTouch);
      el.removeEventListener("touchcancel", endTouch);
      el.removeEventListener("wheel", onWheel);
    };
  }, [applyOffset, applyScale]);

  // Mouse drag, so the same panning works with a pointer.
  useEffect(() => {
    if (!dragging) return undefined;
    const onMove = (event) => {
      const start = dragStartRef.current;
      if (!start) return;
      const dx = event.clientX - start.x;
      const dy = event.clientY - start.y;
      if (Math.hypot(dx, dy) > DRAG_SLOP) movedRef.current = true;
      applyOffset(start.ox + dx, start.oy + dy);
    };
    const onUp = () => {
      dragStartRef.current = null;
      setDragging(false);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [applyOffset, dragging]);

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

  const zoomed = scale > MIN_SCALE;

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
        {zoomed ? (
          <button
            type="button"
            className="mr-auto rounded-full bg-white/10 px-3 py-1.5 text-[12px] text-white hover:bg-white/20"
            onClick={() => applyScale(MIN_SCALE)}
          >
            {tr(lang, "resetZoom")}
          </button>
        ) : null}
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
        className="relative z-[1] flex min-h-0 flex-1 touch-none items-center justify-center overflow-hidden px-3 pb-[max(0.75rem,env(safe-area-inset-bottom))]"
        onClick={() => {
          // A drag that ended off the image must not be taken for a tap.
          if (movedRef.current) {
            movedRef.current = false;
            return;
          }
          onClose();
        }}
      >
        <img
          ref={imageRef}
          alt={alt || ""}
          className={`max-h-full max-w-full origin-center object-contain select-none shadow-[0_24px_80px_-12px_rgba(0,0,0,0.65)] will-change-transform ${
            zoomed ? (dragging ? "cursor-grabbing" : "cursor-grab") : ""
          } ${dragging || scale !== 1 ? "" : "transition-transform duration-75 ease-out"}`}
          src={src}
          style={{ transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})` }}
          onClick={(event) => event.stopPropagation()}
          onDoubleClick={(event) => {
            event.stopPropagation();
            applyScale(zoomed ? MIN_SCALE : 2);
          }}
          onMouseDown={(event) => {
            if (!zoomed) return;
            event.preventDefault();
            movedRef.current = false;
            dragStartRef.current = {
              x: event.clientX,
              y: event.clientY,
              ox: offsetRef.current.x,
              oy: offsetRef.current.y,
            };
            setDragging(true);
          }}
          draggable={false}
        />
      </div>
    </div>,
    document.body,
  );
}
