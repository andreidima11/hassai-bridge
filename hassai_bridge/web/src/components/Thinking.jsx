import { useEffect, useRef, useState } from "react";
import { ChevronIcon } from "./Icons.jsx";
import {
  activityVerb,
  enableApprovalPreview,
  formatMs,
  liveThinkingLabel,
  stepDisplayDetail,
  tr,
} from "../lib/i18n.js";
import { toolSteps } from "../lib/thinking.js";

/** Enable-group / browser-host Approve — matches chat chrome (neutral HA dark). */
export function ApprovalCard({ step, lang, busy, onDecide }) {
  const isBrowserHost = Boolean(step.browser_host);
  const [addAllowlist, setAddAllowlist] = useState(true);
  const preview = isBrowserHost
    ? (() => {
        const host = String(step.browser_host || "").trim();
        const url = String(step.browser_url || step.args_preview || "").trim();
        const bits = [tr(lang, "browserHostPreview", { host: host || "site" })];
        if (url && url !== host) bits.push(url);
        return bits.join(" · ");
      })()
    : step.enable_group
      ? enableApprovalPreview(lang, step.enable_group, step.enable_reason)
      : String(step.args_preview || step.detail || "").trim();
  const title = tr(lang, isBrowserHost ? "browserHostTitle" : "enableTitle");
  const approveLabel = tr(lang, isBrowserHost ? "browserHostAllow" : "enableApprove");
  const declineLabel = tr(lang, isBrowserHost ? "browserHostDecline" : "approvalDecline");

  return (
    <div
      className="w-full max-w-md rounded-2xl border border-white/10 bg-card px-4 py-3.5 shadow-composer"
      data-approval="true"
      role="group"
      aria-label={title}
    >
      <div className="text-[15px] font-medium text-foreground">{title}</div>
      {preview ? (
        <p className="mt-1.5 break-words text-[13px] leading-snug text-muted-foreground">{preview}</p>
      ) : null}
      {isBrowserHost ? (
        <label className="mt-3 flex cursor-pointer items-center gap-2 text-[12px] text-muted-foreground">
          <input
            type="checkbox"
            className="size-3.5 rounded border-white/20 bg-white/5 accent-emerald-400"
            checked={addAllowlist}
            disabled={busy}
            onChange={(e) => setAddAllowlist(e.target.checked)}
          />
          <span>{tr(lang, "browserHostAddAllowlist")}</span>
        </label>
      ) : null}
      <div className="mt-3 flex items-center justify-between gap-2">
        <button
          type="button"
          disabled={busy}
          className="rounded-lg border border-emerald-500/35 bg-emerald-500/15 px-2.5 py-1.5 text-[12px] font-medium text-emerald-300 transition hover:bg-emerald-500/25 disabled:opacity-50"
          onClick={() =>
            onDecide?.(
              "approve",
              isBrowserHost ? (addAllowlist ? "allowlist" : "once") : "once",
            )
          }
        >
          {approveLabel}
        </button>
        <button
          type="button"
          disabled={busy}
          className="rounded-lg border border-red-500/35 bg-red-500/15 px-2.5 py-1.5 text-[12px] font-medium text-red-300 transition hover:bg-red-500/25 disabled:opacity-50"
          onClick={() => onDecide?.("decline", "once")}
        >
          {declineLabel}
        </button>
      </div>
    </div>
  );
}

function ThinkStepRow({ step, lang }) {
  const running = step.status === "running";
  const detail = String(step.detail || "").trim();
  const [expanded, setExpanded] = useState(false);
  const label = running
    ? tr(lang, "thinkingLive")
    : `${tr(lang, "thinking")}${step.ms ? ` · ${formatMs(step.ms)}` : ""}`;

  return (
    <div className="relative flex min-w-0 items-start gap-2.5 py-1 text-[13px] leading-snug text-muted-foreground/85">
      <span className="mt-1.5 size-1.5 shrink-0 rounded-full bg-muted-foreground/35" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        <div className="flex min-w-0 items-center gap-2">
          <span className={`min-w-0 ${running ? "thinking-shimmer" : ""}`}>{label}</span>
          {detail ? (
            <button
              type="button"
              className="shrink-0 text-[11px] text-muted-foreground/70 underline-offset-2 hover:text-foreground hover:underline"
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? tr(lang, "hideThinkingDetail") : tr(lang, "showThinkingDetail")}
            </button>
          ) : null}
        </div>
        {detail && expanded ? (
          <p className="mt-1.5 max-h-40 overflow-y-auto whitespace-pre-wrap break-words text-[12px] font-normal leading-relaxed text-muted-foreground/70">
            {detail}
          </p>
        ) : null}
      </div>
    </div>
  );
}

function StepRow({ step, lang }) {
  const running = step.status === "running";
  const awaiting = step.status === "awaiting_approval";
  const done = step.status === "done";
  const skipped = step.status === "skip";
  const isThink = step.name === "think";

  // Approvals render in the chat message body, not in Thinking.
  if (awaiting) return null;

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
    return <ThinkStepRow lang={lang} step={step} />;
  }

  const display = stepDisplayDetail(step);

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
          <span className={`min-w-0 font-medium ${running ? "text-foreground" : "text-muted-foreground"}`}>
            {activityVerb(lang, step.name)}
          </span>
          {done && step.ms ? (
            <span className="ml-auto shrink-0 text-[11px] tabular-nums text-muted-foreground/55">
              {formatMs(step.ms)}
            </span>
          ) : null}
          {skipped ? (
            <span className="ml-auto shrink-0 text-[11px] text-amber-400/90">{tr(lang, "skipped")}</span>
          ) : null}
        </div>
        {display ? (
          <p className="mt-0.5 break-words text-[12px] leading-snug text-muted-foreground/85">{display}</p>
        ) : null}
      </div>
    </div>
  );
}

export function Thinking({ thinking, lang, streaming = false }) {
  const steps = thinking.steps || [];
  const tools = toolSteps(steps);
  const hasSteps = steps.length > 0;
  const hasTools = tools.length > 0;
  const hasActionTrail = tools.length > 0 || steps.some((s) => s.name === "say");
  const awaiting = steps.some((s) => s.status === "awaiting_approval");
  const isLive = Boolean(thinking.active || streaming || awaiting);
  const canToggle = isLive || hasSteps;
  const [open, setOpen] = useState(false);
  const [userToggled, setUserToggled] = useState(false);
  const [autoClosed, setAutoClosed] = useState(false);
  const wasLive = useRef(false);

  useEffect(() => {
    if (awaiting) setAutoClosed(false);
  }, [awaiting]);

  // Auto-expand when the first real action/say appears while live.
  useEffect(() => {
    if (isLive && hasActionTrail && !userToggled) {
      setOpen(true);
      setAutoClosed(false);
    }
  }, [isLive, hasActionTrail, userToggled]);

  useEffect(() => {
    if (isLive) {
      wasLive.current = true;
      return undefined;
    }
    // After a live turn finishes: keep open briefly, then collapse unless user pinned it open.
    if (wasLive.current && hasSteps && open && !autoClosed && !awaiting && !userToggled) {
      const timer = window.setTimeout(() => {
        setOpen(false);
        setAutoClosed(true);
        wasLive.current = false;
      }, 3500);
      return () => window.clearTimeout(timer);
    }
    if (!isLive) wasLive.current = false;
    return undefined;
  }, [isLive, hasSteps, open, autoClosed, awaiting, userToggled]);

  useEffect(() => {
    if (thinking.collapsed && !isLive && !awaiting && !userToggled) setOpen(false);
  }, [thinking.collapsed, isLive, awaiting, userToggled]);

  if (!thinking.visible && !hasSteps) return null;

  const headerLabel = isLive
    ? liveThinkingLabel(lang, thinking)
    : thinking.label || tr(lang, "thoughtBrief");

  return (
    <div className="w-full">
      <button
        type="button"
        className="group flex w-fit max-w-full items-center gap-1.5 rounded-md py-0.5 text-left text-[13px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:cursor-default"
        onClick={() => {
          if (!canToggle) return;
          setUserToggled(true);
          setOpen((value) => !value);
        }}
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
