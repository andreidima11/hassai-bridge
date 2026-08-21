import { useEffect, useState } from "react";
import { CopyIcon, InfoIcon, ReuseIcon } from "./Icons.jsx";
import { tr } from "../lib/i18n.js";
import { toolSteps } from "../lib/thinking.js";

function plainText(message) {
  return String(message?.content || "").trim();
}

function formatWhen(ts, lang) {
  const n = Number(ts);
  if (!Number.isFinite(n) || n <= 0) return "";
  const ms = n > 1e12 ? n : n * 1000;
  try {
    return new Intl.DateTimeFormat(lang === "ro" ? "ro-RO" : "en-GB", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(ms));
  } catch {
    return new Date(ms).toLocaleString();
  }
}

function wordCount(text) {
  const parts = String(text || "").trim().match(/\S+/g);
  return parts ? parts.length : 0;
}

async function writeClipboard(text) {
  if (!text) return false;
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    try {
      const el = document.createElement("textarea");
      el.value = text;
      el.setAttribute("readonly", "");
      el.style.position = "fixed";
      el.style.left = "-9999px";
      document.body.appendChild(el);
      el.select();
      const ok = document.execCommand("copy");
      el.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

export function MessageActions({ message, lang, onReuse, onClose }) {
  const [copied, setCopied] = useState(false);
  const [detailsOpen, setDetailsOpen] = useState(false);
  const isUser = message.role === "user";
  const text = plainText(message);
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];
  const steps = toolSteps(message.thinking?.steps);
  const when = formatWhen(message.createdAt, lang);
  const canReuse = Boolean(text) || attachments.length > 0;

  useEffect(() => {
    if (!copied) return undefined;
    const id = window.setTimeout(() => setCopied(false), 1600);
    return () => window.clearTimeout(id);
  }, [copied]);

  const align = isUser ? "justify-end" : "justify-start";

  return (
    <div className={`flex w-full flex-col gap-2 ${isUser ? "items-end" : "items-start"}`}>
      <div
        className={`flex flex-wrap items-center gap-1 ${align}`}
        role="toolbar"
        aria-label={tr(lang, "messageActions")}
      >
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full bg-white/8 px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/12 hover:text-foreground disabled:opacity-40"
          disabled={!text}
          onClick={async (e) => {
            e.stopPropagation();
            if (await writeClipboard(text)) setCopied(true);
          }}
        >
          <CopyIcon size={13} />
          <span>{copied ? tr(lang, "copied") : tr(lang, "copy")}</span>
        </button>
        <button
          type="button"
          className="inline-flex items-center gap-1.5 rounded-full bg-white/8 px-2.5 py-1.5 text-[12px] text-muted-foreground transition hover:bg-white/12 hover:text-foreground disabled:opacity-40"
          disabled={!canReuse}
          onClick={(e) => {
            e.stopPropagation();
            onReuse?.(message);
            onClose?.();
          }}
        >
          <ReuseIcon size={13} />
          <span>{isUser ? tr(lang, "reusePrompt") : tr(lang, "useInComposer")}</span>
        </button>
        <button
          type="button"
          className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[12px] transition ${
            detailsOpen
              ? "bg-white/15 text-foreground"
              : "bg-white/8 text-muted-foreground hover:bg-white/12 hover:text-foreground"
          }`}
          aria-expanded={detailsOpen}
          onClick={(e) => {
            e.stopPropagation();
            setDetailsOpen((v) => !v);
          }}
        >
          <InfoIcon size={13} />
          <span>{tr(lang, "messageDetails")}</span>
        </button>
      </div>

      {detailsOpen ? (
        <div
          className={`w-full max-w-[min(100%,36rem)] rounded-2xl border border-white/10 bg-white/[0.04] px-3.5 py-3 text-[12px] leading-5 text-muted-foreground ${
            isUser ? "text-right" : "text-left"
          }`}
          onClick={(e) => e.stopPropagation()}
        >
          <dl className={`grid gap-1.5 ${isUser ? "justify-items-end" : "justify-items-start"}`}>
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{tr(lang, "messageRole")}</dt>
              <dd className="text-foreground/90">{isUser ? tr(lang, "messageRoleYou") : tr(lang, "messageRoleAssistant")}</dd>
            </div>
            {when ? (
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{tr(lang, "messageTime")}</dt>
                <dd className="text-foreground/90">{when}</dd>
              </div>
            ) : null}
            <div>
              <dt className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{tr(lang, "messageSize")}</dt>
              <dd className="text-foreground/90">
                {tr(lang, "messageSizeValue", {
                  chars: String(text.length),
                  words: String(wordCount(text)),
                })}
              </dd>
            </div>
            {attachments.length ? (
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{tr(lang, "messageImages")}</dt>
                <dd className="text-foreground/90">{attachments.length}</dd>
              </div>
            ) : null}
            {message.thinking?.label ? (
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{tr(lang, "thinking")}</dt>
                <dd className="text-foreground/90">{message.thinking.label}</dd>
              </div>
            ) : null}
            {steps.length ? (
              <div className={isUser ? "w-full text-right" : "w-full text-left"}>
                <dt className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{tr(lang, "messageSteps")}</dt>
                <dd className="mt-1 space-y-1 text-foreground/85">
                  {steps.slice(0, 8).map((step, idx) => (
                    <div key={`${step.name}-${idx}`} className="truncate">
                      {step.name.replace(/^ha_/, "").replace(/_/g, " ")}
                      {step.status === "skip" ? ` · ${tr(lang, "skipped")}` : ""}
                    </div>
                  ))}
                  {steps.length > 8 ? <div>…</div> : null}
                </dd>
              </div>
            ) : null}
            {message.error ? (
              <div>
                <dt className="text-[11px] uppercase tracking-wide text-muted-foreground/70">{tr(lang, "messageStatus")}</dt>
                <dd className="text-destructive">{tr(lang, "messageStatusError")}</dd>
              </div>
            ) : null}
          </dl>
        </div>
      ) : null}
    </div>
  );
}
