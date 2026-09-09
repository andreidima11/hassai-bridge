import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { XIcon } from "./Icons.jsx";
import { tr } from "../lib/i18n.js";

export function ChipManageModal({ chip, lang, onClose, onSave, onSuppress }) {
  const [label, setLabel] = useState(String(chip?.label || ""));
  const [prompt, setPrompt] = useState(String(chip?.prompt || ""));
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    setLabel(String(chip?.label || ""));
    setPrompt(String(chip?.prompt || ""));
    setError("");
  }, [chip]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose?.();
    };
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", onKey);
    return () => {
      document.body.style.overflow = prev;
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  if (!chip || typeof document === "undefined") return null;

  const save = async () => {
    const nextLabel = label.trim();
    const nextPrompt = prompt.trim() || nextLabel;
    if (!nextLabel || !nextPrompt) {
      setError(tr(lang, "chipManageNeedText"));
      return;
    }
    setBusy(true);
    setError("");
    try {
      await onSave?.({ ...chip, label: nextLabel, prompt: nextPrompt });
      onClose?.();
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  const suppress = async () => {
    setBusy(true);
    setError("");
    try {
      await onSuppress?.(chip);
      onClose?.();
    } catch (e) {
      setError(e?.message || String(e));
    } finally {
      setBusy(false);
    }
  };

  return createPortal(
    <div
      className="fixed inset-0 z-[80] flex items-end justify-center sm:items-center"
      role="dialog"
      aria-modal="true"
      aria-label={tr(lang, "chipManageTitle")}
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        aria-label={tr(lang, "chipManageClose")}
        onClick={onClose}
      />
      <div className="relative z-[1] mb-0 w-full max-w-md overflow-hidden rounded-t-2xl border border-white/10 bg-[#141414] shadow-2xl sm:rounded-2xl">
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
          <h2 className="text-[15px] font-medium text-foreground">{tr(lang, "chipManageTitle")}</h2>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            aria-label={tr(lang, "chipManageClose")}
            onClick={onClose}
          >
            <XIcon size={16} />
          </button>
        </div>
        <div className="space-y-3 px-4 py-4">
          <label className="block text-[12px] text-muted-foreground">
            {tr(lang, "chipManageLabel")}
            <input
              className="mt-1 w-full rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-[14px] text-foreground outline-none focus:border-white/25"
              value={label}
              maxLength={80}
              disabled={busy}
              onChange={(e) => setLabel(e.target.value)}
            />
          </label>
          <label className="block text-[12px] text-muted-foreground">
            {tr(lang, "chipManagePrompt")}
            <textarea
              className="mt-1 min-h-[4.5rem] w-full resize-y rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2 text-[14px] text-foreground outline-none focus:border-white/25"
              value={prompt}
              maxLength={240}
              disabled={busy}
              onChange={(e) => setPrompt(e.target.value)}
            />
          </label>
          {error ? <p className="text-[13px] text-red-400">{error}</p> : null}
          <div className="flex flex-col gap-2 pt-1 sm:flex-row sm:justify-between">
            <button
              type="button"
              className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-[13px] text-red-300 hover:bg-red-500/20 disabled:opacity-50"
              disabled={busy}
              onClick={suppress}
            >
              {tr(lang, "chipManageSuppress")}
            </button>
            <div className="flex gap-2 sm:justify-end">
              <button
                type="button"
                className="rounded-xl border border-white/10 px-3 py-2 text-[13px] text-muted-foreground hover:bg-white/5"
                disabled={busy}
                onClick={onClose}
              >
                {tr(lang, "chipManageCancel")}
              </button>
              <button
                type="button"
                className="rounded-xl bg-white/90 px-3 py-2 text-[13px] font-medium text-black hover:bg-white disabled:opacity-50"
                disabled={busy}
                onClick={save}
              >
                {tr(lang, "chipManageSave")}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body,
  );
}
