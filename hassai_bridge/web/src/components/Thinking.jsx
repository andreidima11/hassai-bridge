import { useEffect, useState } from "react";
import { ChevronIcon } from "./Icons.jsx";
import { activityVerb, formatMs, liveThinkingLabel, tr } from "../lib/i18n.js";

function StepRow({ step, lang }) {
  const running = step.status === "running";
  const done = step.status === "done";
  const skipped = step.status === "skip";

  return (
    <div className="relative flex min-w-0 items-start gap-2.5 py-1.5 text-[13px] leading-snug">
      <span className="mt-1 flex size-4 shrink-0 items-center justify-center">
        {running ? (
          <span
            className="size-3.5 animate-spin rounded-full border-2 border-muted-foreground/25 border-t-foreground/90"
            aria-hidden="true"
          />
        ) : (
          <span
            className={`size-1.5 rounded-full ${
              done ? "bg-emerald-400/90" : skipped ? "bg-amber-400/90" : "bg-muted-foreground/45"
            }`}
            aria-hidden="true"
          />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-baseline gap-2">
          <span className={`shrink-0 font-medium ${running ? "text-foreground" : "text-muted-foreground"}`}>
            {activityVerb(lang, step.name)}
          </span>
          {step.detail ? <span className="min-w-0 truncate text-muted-foreground/85">{step.detail}</span> : null}
          {done && step.ms ? (
            <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground/55">{formatMs(step.ms)}</span>
          ) : null}
          {skipped ? (
            <span className="ml-auto shrink-0 text-[11px] text-amber-400/90">{tr(lang, "skipped")}</span>
          ) : null}
        </div>
      </div>
    </div>
  );
}

export function Thinking({ thinking, lang, streaming = false }) {
  const steps = thinking.steps || [];
  const hasSteps = steps.length > 0;
  const isLive = Boolean(thinking.active || streaming);
  const [open, setOpen] = useState(isLive || !thinking.collapsed);
  const [autoClosed, setAutoClosed] = useState(false);

  useEffect(() => {
    if (isLive) {
      setOpen(true);
      setAutoClosed(false);
    }
  }, [isLive]);

  useEffect(() => {
    if (!isLive && hasSteps && open && !autoClosed) {
      const timer = window.setTimeout(() => {
        setOpen(false);
        setAutoClosed(true);
      }, 1000);
      return () => window.clearTimeout(timer);
    }
  }, [isLive, hasSteps, open, autoClosed]);

  useEffect(() => {
    if (thinking.collapsed && !isLive) setOpen(false);
  }, [thinking.collapsed, isLive]);

  if (!thinking.visible && !hasSteps) return null;

  const headerLabel = isLive
    ? liveThinkingLabel(lang, thinking)
    : thinking.label || tr(lang, "thoughtBrief");

  return (
    <div className="w-full">
      <button
        type="button"
        className="group flex w-fit max-w-full items-center gap-1.5 rounded-md py-0.5 text-left text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:cursor-default"
        onClick={() => hasSteps && setOpen((value) => !value)}
        disabled={!hasSteps}
        aria-expanded={hasSteps ? open : undefined}
      >
        <ChevronIcon className={`mt-px shrink-0 transition-transform duration-200 ${open && hasSteps ? "rotate-180" : ""}`} />
        {isLive && !hasSteps ? (
          <span className="thinking-shimmer truncate">{headerLabel}</span>
        ) : (
          <span className="truncate">{headerLabel}</span>
        )}
        {!open && hasSteps && !isLive ? (
          <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground/75">
            {steps.length}
          </span>
        ) : null}
      </button>
      {open && hasSteps ? (
        <div className="mt-0.5 ml-[7px] border-l border-white/10 pl-3.5">
          {steps.map((step) => (
            <StepRow key={step.id} lang={lang} step={step} />
          ))}
        </div>
      ) : null}
    </div>
  );
}
