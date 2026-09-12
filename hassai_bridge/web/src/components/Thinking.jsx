import { useEffect, useState } from "react";
import { ChevronIcon } from "./Icons.jsx";
import { activityVerb, formatMs, liveThinkingLabel, tr } from "../lib/i18n.js";
import { toolSteps } from "../lib/thinking.js";

function ApprovalCard({ step, lang, busy, onDecide }) {
  const preview = String(step.args_preview || step.detail || "").trim();
  const enabling = Boolean(step.enable_group);
  return (
    <div className="relative my-1.5 rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-[13px] leading-snug">
      <div className="font-medium text-foreground">
        {enabling ? tr(lang, "enableTitle") : tr(lang, "approvalTitle")}
        {!enabling ? ` · ${activityVerb(lang, step.name)}` : null}
      </div>
      {preview ? (
        <p className="mt-1 break-words text-[12px] text-muted-foreground/90">{preview}</p>
      ) : null}
      <div className="mt-2.5 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy}
          className="rounded-lg bg-emerald-500/90 px-2.5 py-1 text-[12px] font-semibold text-white disabled:opacity-50"
          onClick={() => onDecide?.("approve", enabling ? "once" : "once")}
        >
          {enabling ? tr(lang, "enableApprove") : tr(lang, "approvalApprove")}
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-lg bg-white/10 px-2.5 py-1 text-[12px] font-semibold text-foreground disabled:opacity-50"
          onClick={() => onDecide?.("decline", "once")}
        >
          {tr(lang, "approvalDecline")}
        </button>
        {enabling ? (
          <button
            type="button"
            disabled={busy}
            className="rounded-lg border border-white/15 px-2.5 py-1 text-[12px] font-medium text-muted-foreground disabled:opacity-50"
            onClick={() => onDecide?.("approve", "settings")}
          >
            {tr(lang, "enableSaveSettings")}
          </button>
        ) : (
          <button
            type="button"
            disabled={busy}
            className="rounded-lg border border-white/15 px-2.5 py-1 text-[12px] font-medium text-muted-foreground disabled:opacity-50"
            onClick={() => onDecide?.("approve", "conversation")}
          >
            {tr(lang, "approvalAllowChat")}
          </button>
        )}
      </div>
    </div>
  );
}

function StepRow({ step, lang, onApprove, approvalBusy }) {
  const running = step.status === "running";
  const awaiting = step.status === "awaiting_approval";
  const done = step.status === "done";
  const skipped = step.status === "skip";
  const isThink = step.name === "think";

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

  if (awaiting) {
    return (
      <ApprovalCard
        step={step}
        lang={lang}
        busy={approvalBusy}
        onDecide={(decision, scope) => onApprove?.(step.id, decision, scope)}
      />
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

export function Thinking({ thinking, lang, streaming = false, onApprove = null }) {
  const steps = thinking.steps || [];
  const tools = toolSteps(steps);
  const hasSteps = steps.length > 0;
  const hasTools = tools.length > 0;
  const awaiting = steps.some((s) => s.status === "awaiting_approval");
  const isLive = Boolean(thinking.active || streaming || awaiting);
  const canToggle = isLive || hasSteps;
  const [open, setOpen] = useState(false);
  const [autoClosed, setAutoClosed] = useState(false);
  const [approvalBusy, setApprovalBusy] = useState(false);

  useEffect(() => {
    if (awaiting) {
      setOpen(true);
      setAutoClosed(false);
    }
  }, [awaiting]);

  useEffect(() => {
    if (!isLive && hasSteps && open && !autoClosed && !awaiting) {
      const timer = window.setTimeout(() => {
        setOpen(false);
        setAutoClosed(true);
      }, 1000);
      return () => window.clearTimeout(timer);
    }
  }, [isLive, hasSteps, open, autoClosed, awaiting]);

  useEffect(() => {
    if (thinking.collapsed && !isLive) setOpen(false);
  }, [thinking.collapsed, isLive]);

  if (!thinking.visible && !hasSteps) return null;

  const headerLabel = awaiting
    ? tr(lang, "approvalWaiting")
    : isLive
      ? liveThinkingLabel(lang, thinking)
      : thinking.label || tr(lang, "thoughtBrief");

  const handleDecide = async (callId, decision, scope) => {
    if (!onApprove || approvalBusy) return;
    setApprovalBusy(true);
    try {
      await onApprove(callId, decision, scope);
    } finally {
      setApprovalBusy(false);
    }
  };

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
          <span className={`truncate ${awaiting ? "text-amber-300" : ""}`}>{headerLabel}</span>
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
            steps.map((step) => (
              <StepRow
                key={step.id}
                lang={lang}
                step={step}
                onApprove={handleDecide}
                approvalBusy={approvalBusy}
              />
            ))
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
