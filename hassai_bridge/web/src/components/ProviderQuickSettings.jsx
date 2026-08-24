import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { BrainIcon } from "./Icons.jsx";
import { ThemeSelect } from "./ThemeSelect.jsx";
import { THINKING_MODES } from "../lib/providerCapabilities.js";
import { apiJson } from "../lib/api.js";
import { tr } from "../lib/i18n.js";

function usePopoverPosition(open, anchorRef) {
  const [style, setStyle] = useState(null);

  useLayoutEffect(() => {
    if (!open || !anchorRef.current) {
      setStyle(null);
      return undefined;
    }

    const update = () => {
      const rect = anchorRef.current?.getBoundingClientRect();
      if (!rect) return;
      setStyle({
        position: "fixed",
        right: Math.max(12, window.innerWidth - rect.right),
        bottom: window.innerHeight - rect.top + 8,
        width: "min(92vw, 280px)",
        zIndex: 50,
      });
    };

    update();
    window.addEventListener("resize", update);
    window.addEventListener("scroll", update, true);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("scroll", update, true);
    };
  }, [open, anchorRef]);

  return style;
}

// Sentinel option in the provider list — not a provider id.
export const AUTO_PROVIDER = "__auto__";

export function ProviderQuickSettings({
  providerId,
  providerName,
  model,
  capabilities,
  thinkingMode,
  auto = false,
  onThinkingModeChange,
  onModelChange,
  onProviderChange,
  lang,
  disabled = false,
}) {
  const anchorRef = useRef(null);
  const panelRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [providers, setProviders] = useState([]);
  const [loadingProviders, setLoadingProviders] = useState(false);
  const [providersError, setProvidersError] = useState("");
  const [models, setModels] = useState([]);
  const [loadingModels, setLoadingModels] = useState(false);
  const [modelsError, setModelsError] = useState("");
  const panelStyle = usePopoverPosition(open, anchorRef);
  const showThinking = Boolean(capabilities?.thinking?.modes?.length);
  const thinkingActive = thinkingMode !== "off" || auto;

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event) => {
      if (anchorRef.current?.contains(event.target)) return;
      if (panelRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setLoadingProviders(true);
    setProvidersError("");
    apiJson("/api/settings/providers")
      .then((data) => {
        if (cancelled) return;
        setProviders(Array.isArray(data.providers) ? data.providers : []);
      })
      .catch((err) => {
        if (cancelled) return;
        setProviders([]);
        setProvidersError(String(err.message || "error"));
      })
      .finally(() => {
        if (!cancelled) setLoadingProviders(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open]);

  useEffect(() => {
    if (!open || !providerId || auto) return;
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
  }, [open, providerId, auto]);

  const thinkingLabel = showThinking
    ? tr(lang, `thinkingMode${thinkingMode.charAt(0).toUpperCase()}${thinkingMode.slice(1)}`)
    : "";

  const providerOptions = (() => {
    const rows = providers.map((row) => ({
      value: row.id,
      label: row.name || row.id,
    }));
    if (providerId && !rows.some((row) => row.value === providerId)) {
      rows.unshift({ value: providerId, label: providerName || providerId });
    }
    rows.unshift({ value: AUTO_PROVIDER, label: tr(lang, "providerAuto") });
    return rows;
  })();

  const modelOptions = (() => {
    const rows = models.map((row) => ({
      value: row.id,
      label: row.name && row.name !== row.id ? `${row.id} — ${row.name}` : row.id,
    }));
    if (model && !rows.some((row) => row.value === model)) {
      rows.unshift({ value: model, label: model });
    }
    return rows;
  })();

  const panel = open && panelStyle ? (
    <div
      ref={panelRef}
      style={panelStyle}
      className="rounded-2xl border border-white/10 bg-card p-3 shadow-composer"
      role="dialog"
      aria-label={tr(lang, "providerSettings")}
    >
      <label className="mb-3 block">
        <div className="mb-1.5 text-[12px] text-muted-foreground">{tr(lang, "providerLabel")}</div>
        {loadingProviders ? (
          <div className="text-[12px] text-muted-foreground">{tr(lang, "loadingProviders")}</div>
        ) : providerOptions.length ? (
          <ThemeSelect
            aria-label={tr(lang, "providerLabel")}
            value={auto ? AUTO_PROVIDER : providerId || ""}
            options={providerOptions}
            onChange={(next) => onProviderChange?.(next)}
          />
        ) : (
          <div className="rounded-xl border border-white/10 bg-secondary/70 px-3 py-2.5 text-[13px] text-foreground">
            {providerName || tr(lang, "noProviders")}
          </div>
        )}
        {providersError ? <div className="mt-1 text-[11px] text-amber-400/90">{providersError}</div> : null}
        {auto ? <div className="mt-1 text-[11px] text-muted-foreground">{tr(lang, "providerAutoHint")}</div> : null}
      </label>

      {auto ? null : (
        <label className="mb-3 block">
          <div className="mb-1.5 text-[12px] text-muted-foreground">{tr(lang, "modelLabel")}</div>
          {loadingModels ? (
            <div className="text-[12px] text-muted-foreground">{tr(lang, "loadingModels")}</div>
          ) : modelOptions.length ? (
            <ThemeSelect
              aria-label={tr(lang, "modelLabel")}
              value={model || ""}
              options={modelOptions}
              onChange={(next) => onModelChange?.(next)}
            />
          ) : (
            <div className="rounded-xl border border-white/10 bg-secondary/70 px-3 py-2.5 text-[13px] text-foreground">
              {model || "—"}
            </div>
          )}
          {modelsError ? <div className="mt-1 text-[11px] text-amber-400/90">{modelsError}</div> : null}
          {models.length ? (
            <div className="mt-1 text-[11px] text-muted-foreground">{tr(lang, "modelsLoaded", { count: models.length })}</div>
          ) : null}
        </label>
      )}

      {showThinking ? (
        <div>
          <div className="mb-1.5 text-[12px] text-muted-foreground">{tr(lang, "thinkingLabel")}</div>
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
                      ? "bg-white/14 text-foreground ring-1 ring-white/18"
                      : "bg-white/[0.04] text-muted-foreground hover:bg-white/[0.08] hover:text-foreground"
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
  ) : null;

  return (
    <>
      <div ref={anchorRef} className="relative mb-0 shrink-0">
        <button
          type="button"
          className={`grid size-8 place-items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-40 ${
            open || thinkingActive
              ? "bg-white/14 text-foreground hover:bg-white/18"
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
      </div>
      {panel ? createPortal(panel, document.body) : null}
    </>
  );
}
