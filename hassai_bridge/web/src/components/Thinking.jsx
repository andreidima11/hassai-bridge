import { useState } from "react";
import { activityVerb, formatMs, tr } from "../lib/i18n.js";

export function Thinking({ thinking, lang }) {
  const [open, setOpen] = useState(!thinking.collapsed);
  const steps = thinking.steps || [];
  const hasSteps = steps.length > 0;

  return (
    <div className="flex flex-col gap-2">
      <button
        type="button"
        className="flex w-fit max-w-full items-center gap-2 bg-transparent p-0 text-left text-[13px] font-medium leading-[1.65] text-muted-foreground hover:text-foreground"
        onClick={() => hasSteps && setOpen((v) => !v)}
      >
        <span className={`size-1.5 shrink-0 rounded-full ${thinking.active ? "animate-pulse bg-foreground" : "bg-muted-foreground/60"}`} />
        <span className="truncate">{thinking.label || tr(lang, "thinking")}</span>
        {hasSteps ? <span className={`opacity-50 transition-transform ${open ? "rotate-90" : ""}`}>›</span> : null}
      </button>
      {open && hasSteps ? (
        <div className="max-h-[200px] overflow-y-auto rounded-lg border border-border/20 bg-muted/30 px-3 py-2">
          {steps.map((step) => (
            <div key={step.id} className="flex min-w-0 items-baseline gap-2 text-[11px] leading-relaxed text-muted-foreground/80">
              <span
                className={`size-1.5 shrink-0 rounded-full ${
                  step.status === "done"
                    ? "bg-emerald-400"
                    : step.status === "skip"
                      ? "bg-amber-400"
                      : "bg-foreground"
                }`}
              />
              <span className="shrink-0 font-semibold text-foreground">{activityVerb(lang, step.name)}</span>
              {step.detail ? <span className="min-w-0 truncate font-mono">{step.detail}</span> : null}
              {step.status === "skip" ? <span className="ml-auto text-amber-400">{tr(lang, "skipped")}</span> : null}
              {step.ms ? <span className="ml-auto text-[10px]">{formatMs(step.ms)}</span> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
