import { useEffect, useState } from "react";
import { CopyIcon, ReuseIcon } from "./Icons.jsx";

export function ActionButton({ label, activeLabel, onClick, children, title }) {
  const [active, setActive] = useState(false);

  useEffect(() => {
    if (!active) return undefined;
    const id = setTimeout(() => setActive(false), 1400);
    return () => clearTimeout(id);
  }, [active]);

  return (
    <button
      type="button"
      title={title || label}
      className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[12px] text-muted-foreground transition-colors hover:bg-white/10 hover:text-foreground"
      onClick={async () => {
        try {
          await onClick?.();
          if (activeLabel) setActive(true);
        } catch {
          /* ignore */
        }
      }}
    >
      {children}
      <span>{active && activeLabel ? activeLabel : label}</span>
    </button>
  );
}

export function MessageActions({ align = "start", children }) {
  return (
    <div
      className={`flex flex-wrap items-center gap-0.5 ${
        align === "end" ? "justify-end" : "justify-start"
      } opacity-100 transition-opacity md:opacity-0 md:group-hover/message:opacity-100 md:group-focus-within/message:opacity-100`}
    >
      {children}
    </div>
  );
}

export async function copyText(text) {
  const value = String(text || "");
  if (!value) return;
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(value);
    return;
  }
  const ta = document.createElement("textarea");
  ta.value = value;
  ta.setAttribute("readonly", "");
  ta.style.position = "fixed";
  ta.style.left = "-9999px";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  ta.remove();
}

export function CopyAction({ text, copyLabel, copiedLabel }) {
  return (
    <ActionButton
      label={copyLabel}
      activeLabel={copiedLabel}
      onClick={() => copyText(text)}
    >
      <CopyIcon />
    </ActionButton>
  );
}

export function ReuseAction({ text, label, onReuse }) {
  if (!onReuse || !String(text || "").trim()) return null;
  return (
    <ActionButton label={label} onClick={() => onReuse(String(text || ""))}>
      <ReuseIcon />
    </ActionButton>
  );
}
