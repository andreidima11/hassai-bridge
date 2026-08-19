import { useEffect, useRef, useState } from "react";
import { BrainIcon } from "./Icons.jsx";
import { THINKING_MODES } from "../lib/providerCapabilities.js";
import { apiJson } from "../lib/api.js";
import { tr } from "../lib/i18n.js";

export function ProviderQuickSettings({
  providerId,
  providerName,
  model,
  capabilities,
  thinkingMode,
  onThinkingModeChange,
  onModelChange,
  lang,
  disabled = false,
}) {
  const rootRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const showThinking = Boolean(capabilities?.thinking?.modes?.length);
  const thinkingActive = thinkingMode !== "off";

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event) => {
      if (!rootRef.current?.contains(event.target)) setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open || !providerId) return;
    let cancelled = false;
    setLoadingModels(true);
    setModelsError("");
    apiJson(`/api/settings/providers/${encodeURIComponent(providerId)}/models`)
      .then((data) => {
        if (cancelled) return;
        setModels(Array.isArray(data.models) ? data.models : []);
      })
      .catch((err) => {
        if (cancelled) return;
        setModels([]);
        setModelsError(String(err.message || "error"));
      })
      .finally(() => {
        if (!cancelled) setLoadingModels(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, providerId]);

  const thinkingLabel = showThinking
    ? tr(lang, `thinkingMode${thinkingMode.charAt(0).toUpperCase()}${thinkingMode.slice(1)}`)
    : "";

  return (
    <div ref={rootRef} className="relative mb-0 shrink-0">
      <button
        type="button"
        className={`grid size-8 place-items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-40 ${
          open || thinkingActive
            ? "bg-violet-500/20 text-violet-200 hover:bg-violet-500/30"
            : "text-muted-foreground hover:bg-white/10 hover:text-foreground"
        }`}
        aria-label={tr(lang, "providerSettings")}
        title={tr(lang, "providerSettings")}
        disabled={disabled}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        <BrainIcon active={open || thinkingActive} />
      </button>

      {open ? (
        <div className="absolute bottom-[calc(100%+8px)] right-0 z-20 w-[min(92vw,280px)] rounded-2xl border border-white/10 bg-card p-3 shadow-composer">
          <div className="mb-3">
            <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{tr(lang, "providerLabel")}</div>
            <div className="truncate text-[14px] font-medium text-foreground">{providerName || "—"}</div>
          </div>

          <label className="mb-3 block">
            <div className="mb-1 text-[12px] text-muted-foreground">{tr(lang, "modelLabel")}</div>
            {loadingModels ? (
              <div className="text-[12px] text-muted-foreground">{tr(lang, "loadingModels")}</div>
            ) : models.length ? (
              <select
                className="w-full rounded-xl border border-white/10 bg-background px-2.5 py-2 text-[13px] text-foreground outline-none focus:border-white/20"
                value={model || ""}
                onChange={(e) => onModelChange?.(e.target.value)}
              >
                {!models.some((row) => row.id === model) && model ? (
                  <option value={model}>{model}</option>
                ) : null}
                {models.map((row) => (
                  <option key={row.id} value={row.id}>
                    {row.name && row.name !== row.id ? `${row.id} — ${row.name}` : row.id}
                  </option>
                ))}
              </select>
            ) : (
              <div className="rounded-xl border border-white/10 bg-background px-2.5 py-2 text-[13px] text-foreground">
                {model || "—"}
              </div>
            )}
            {modelsError ? <div className="mt-1 text-[11px] text-amber-400/90">{modelsError}</div> : null}
            {models.length ? (
              <div className="mt-1 text-[11px] text-muted-foreground">{tr(lang, "modelsLoaded", { count: models.length })}</div>
            ) : null}
          </label>

          {showThinking ? (
            <div>
              <div className="mb-1 text-[12px] text-muted-foreground">{tr(lang, "thinkingLabel")}</div>
              <div className="grid grid-cols-2 gap-1.5">
                {THINKING_MODES.map((mode) => {
                  const active = mode === thinkingMode;
                  const label = tr(lang, `thinkingMode${mode.charAt(0).toUpperCase()}${mode.slice(1)}`);
                  return (
                    <button
                      key={mode}
                      type="button"
                      className={`rounded-xl px-2 py-1.5 text-[12px] transition ${
                        active
                          ? "bg-violet-500/25 text-violet-100 ring-1 ring-violet-400/30"
                          : "bg-white/5 text-muted-foreground hover:bg-white/10 hover:text-foreground"
                      }`}
                      aria-pressed={active}
                      title={label}
                      onClick={() => onThinkingModeChange?.(mode)}
                    >
                      {label.replace(/^Thinking:\s*/i, "").replace(/^Gândire:\s*/i, "")}
                    </button>
                  );
                })}
              </div>
              <div className="mt-1 text-[11px] text-muted-foreground">{thinkingLabel}</div>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
