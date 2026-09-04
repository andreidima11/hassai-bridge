import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { XIcon } from "./Icons.jsx";
import { tr } from "../lib/i18n.js";

function faviconUrl(site) {
  const host = String(site || "").trim();
  if (!host) return "";
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(host)}&sz=32`;
}

function Favicon({ site, title }) {
  const [failed, setFailed] = useState(false);
  const letter = String(title || site || "?").trim().charAt(0).toUpperCase() || "?";
  if (failed || !site) {
    return (
      <span
        className="grid size-4 shrink-0 place-items-center rounded-[4px] bg-white/15 text-[9px] font-semibold text-foreground/80"
        aria-hidden="true"
      >
        {letter}
      </span>
    );
  }
  return (
    <img
      alt=""
      className="size-4 shrink-0 rounded-[3px] bg-white/10 object-contain"
      src={faviconUrl(site)}
      onError={() => setFailed(true)}
    />
  );
}

function SourceChip({ source }) {
  const site = source.site || "source";
  const title = source.title || site;
  return (
    <a
      href={source.url}
      target="_blank"
      rel="noopener noreferrer"
      className="inline-flex max-w-[11rem] items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[12px] text-muted-foreground transition hover:border-white/20 hover:bg-white/[0.08] hover:text-foreground"
      title={title}
    >
      <Favicon site={site} title={title} />
      <span className="truncate">{site}</span>
    </a>
  );
}

function SourcesModal({ sources, lang, onClose }) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label={tr(lang, "sourcesTitle")}
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        aria-label={tr(lang, "closeSources")}
        onClick={onClose}
      />
      <div className="relative z-[1] mb-0 max-h-[min(80vh,32rem)] w-full max-w-md overflow-hidden rounded-t-2xl border border-white/10 bg-[#141414] shadow-2xl sm:mb-0 sm:rounded-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <h2 className="text-[15px] font-medium text-foreground">{tr(lang, "sourcesTitle")}</h2>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            aria-label={tr(lang, "closeSources")}
            onClick={onClose}
          >
            <XIcon size={16} />
          </button>
        </div>
        <ul className="max-h-[min(60vh,24rem)] overflow-y-auto p-2">
          {sources.map((source) => {
            const site = source.site || "source";
            const title = source.title || site;
            return (
              <li key={source.url || site}>
                <a
                  href={source.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-start gap-3 rounded-xl px-3 py-2.5 transition hover:bg-white/[0.06]"
                >
                  <span className="mt-0.5">
                    <Favicon site={site} title={title} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-[14px] text-foreground">{title}</span>
                    <span className="block truncate text-[12px] text-muted-foreground">{site}</span>
                  </span>
                </a>
              </li>
            );
          })}
        </ul>
      </div>
    </div>,
    document.body,
  );
}

export function SourceChips({ sources, lang }) {
  const [open, setOpen] = useState(false);
  const list = Array.isArray(sources) ? sources.filter((s) => s?.url) : [];
  if (!list.length) return null;

  const visible = list.slice(0, 2);
  const extra = list.length - visible.length;

  return (
    <div className="flex flex-wrap items-center gap-1.5 pt-0.5" data-sources="true">
      {visible.map((source) => (
        <SourceChip key={source.url || source.site} source={source} />
      ))}
      {extra > 0 ? (
        <button
          type="button"
          className="inline-flex items-center rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-[12px] text-muted-foreground transition hover:border-white/20 hover:bg-white/[0.08] hover:text-foreground"
          onClick={() => setOpen(true)}
        >
          {tr(lang, "sourcesMore").replace("{n}", String(extra))}
        </button>
      ) : null}
      {open ? <SourcesModal lang={lang} sources={list} onClose={() => setOpen(false)} /> : null}
    </div>
  );
}
