import { useEffect, useState } from "react";
import { ChevronIcon } from "./Icons.jsx";
import { activityVerb, formatMs, liveThinkingLabel, tr } from "../lib/i18n.js";
import { toolSteps } from "../lib/thinking.js";

function StepRow({ step, lang }) {
  const running = step.status === "running";
  const done = step.status === "done";
  const skipped = step.status === "skip";
  const isThink = step.name === "think";

  // What the model said on its way to the answer — full sentence, not truncated
  // like a tool argument.
  if (step.name === "say") {
    return (
      <div className="relative flex min-w-0 items-start gap-2.5 py-1 text-[13px] leading-snug">
        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/35" aria-hidden="true" />
        <p className="min-w-0 flex-1 whitespace-pre-wrap break-words text-muted-foreground/80">
          {step.detail}
        </p>
      </div>
    );
  }

  if (isThink) {
    const label = running
      ? tr(lang, "thinkingLive")
      : `${tr(lang, "thinking")}${step.ms ? ` · ${formatMs(step.ms)}` : ""}`;
    const detail = String(step.detail || "").trim();
    return (
      <div className="relative flex min-w-0 items-start gap-2.5 py-1 text-[13px] leading-snug text-muted-foreground/85">
        <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/35" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <span className={`block min-w-0 truncate ${running ? "thinking-shimmer" : ""}`}>{label}</span>
          {detail ? (
            <p className="mt-1.5 whitespace-pre-wrap break-words text-[12px] font-normal leading-relaxed text-muted-foreground/70">
              {detail}
            </p>
          ) : null}
        </div>
      </div>
    );
  }

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
  const tools = toolSteps(steps);
  const hasSteps = steps.length > 0;
  const hasTools = tools.length > 0;
  const isLive = Boolean(thinking.active || streaming);
  const canToggle = isLive || hasSteps;
  const [open, setOpen] = useState(false);
  const [autoClosed, setAutoClosed] = useState(false);

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
        onClick={() => canToggle && setOpen((value) => !value)}
        disabled={!canToggle}
        aria-expanded={canToggle ? open : undefined}
      >
        <ChevronIcon className={`mt-px shrink-0 transition-transform duration-200 ${open && canToggle ? "rotate-180" : ""}`} />
        {isLive && !hasTools ? (
          <span className="thinking-shimmer truncate">{headerLabel}</span>
        ) : (
          <span className="truncate">{headerLabel}</span>
        )}
        {!open && hasTools && !isLive ? (
          <span className="rounded-md bg-white/[0.06] px-1.5 py-0.5 text-[10px] font-semibold tabular-nums text-muted-foreground/75">
            {tools.length}
          </span>
        ) : null}
      </button>
      {open && canToggle ? (
        <div className="mt-0.5 ml-[7px] border-l border-white/10 pl-3.5">
          {hasSteps ? (
            steps.map((step) => <StepRow key={step.id} lang={lang} step={step} />)
          ) : isLive ? (
            <div className="flex items-center gap-2.5 py-1.5 text-[13px] text-muted-foreground">
              <span
                className="size-3.5 animate-spin rounded-full border-2 border-muted-foreground/25 border-t-foreground/90"
                aria-hidden="true"
              />
              <span className="thinking-shimmer">{headerLabel}</span>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
