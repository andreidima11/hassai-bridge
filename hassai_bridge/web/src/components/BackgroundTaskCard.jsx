import { useState } from "react";
import { apiJson } from "../lib/api.js";
import { tr } from "../lib/i18n.js";

const ACTIVE = new Set(["scheduled", "running", "blocked"]);

function statusLabel(lang, status) {
  const key = {
    scheduled: "bgTaskStatusScheduled",
    running: "bgTaskStatusRunning",
    completed: "bgTaskStatusCompleted",
    failed: "bgTaskStatusFailed",
    cancelled: "bgTaskStatusCancelled",
    blocked: "bgTaskStatusBlocked",
  }[status];
  return key ? tr(lang, key) : status;
}

function progressLine(task) {
  const p = task?.progress || {};
  if (p.phase === "waiting" && p.last_state != null) {
    return `last: ${p.last_state}`;
  }
  if (p.phase === "monitoring") {
    const left = Math.round(Number(p.seconds_left) || 0);
    const n = p.observation_count || 0;
    return left ? `${n} changes · ${left}s left` : `${n} changes`;
  }
  if (p.phase === "stabilizing") return "stabilizing…";
  return "";
}

export function BackgroundTaskCard({ task, lang, onCancelled }) {
  const [busy, setBusy] = useState(false);
  if (!task?.task_id) return null;
  const active = ACTIVE.has(task.status) && !task.cancel_requested_at;

  const cancel = async () => {
    if (busy || !active) return;
    setBusy(true);
    try {
      const out = await apiJson(`/api/background-tasks/${encodeURIComponent(task.task_id)}/cancel`, {
        method: "POST",
        body: "{}",
      });
      onCancelled?.(out?.task || { ...task, cancel_requested_at: Date.now() / 1000, status: task.status });
    } catch {
      /* ignore — next poll refreshes */
    } finally {
      setBusy(false);
    }
  };

  const hint = progressLine(task);
  const stopping = Boolean(task.cancel_requested_at) && ACTIVE.has(task.status);
  const blocked = task.status === "blocked";

  return (
    <div
      className="w-full max-w-[min(100%,36rem)] rounded-xl border border-white/10 bg-white/[0.04] px-3.5 py-2.5 text-[13px]"
      data-bg-task={task.task_id}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="truncate font-medium text-foreground/95">{task.title || task.kind}</div>
          <div className="mt-0.5 text-[12px] text-muted-foreground">
            {stopping
              ? tr(lang, "bgTaskStopping")
              : blocked
                ? tr(lang, "bgTaskStatusBlocked")
                : statusLabel(lang, task.status)}
            {hint ? ` · ${hint}` : ""}
          </div>
          {blocked ? (
            <div className="mt-1 text-[12px] text-amber-200/90">{tr(lang, "bgTaskBlockedHint")}</div>
          ) : null}
        </div>
        {active ? (
          <button
            type="button"
            disabled={busy}
            className="shrink-0 rounded-lg border border-red-500/30 bg-red-500/10 px-2.5 py-1 text-[12px] text-red-200 transition hover:bg-red-500/20 disabled:opacity-50"
            onClick={(e) => {
              e.stopPropagation();
              cancel();
            }}
          >
            {tr(lang, "bgTaskStop")}
          </button>
        ) : null}
      </div>
    </div>
  );
}

export function isActiveBgTask(task) {
  return task && ACTIVE.has(task.status);
}
