import { BrainIcon } from "./Icons.jsx";
import { THINKING_MODES } from "../lib/providerCapabilities.js";
import { tr } from "../lib/i18n.js";

export function ThinkingMode({ mode, onChange, lang, disabled = false }) {
  const cycle = () => {
    if (disabled) return;
    const idx = THINKING_MODES.indexOf(mode);
    const next = THINKING_MODES[(idx + 1) % THINKING_MODES.length];
    onChange(next);
  };

  const label = tr(lang, `thinkingMode${mode.charAt(0).toUpperCase()}${mode.slice(1)}`);
  const active = mode !== "off";

  return (
    <button
      type="button"
      className={`mb-0 grid size-8 shrink-0 place-items-center rounded-full transition disabled:cursor-not-allowed disabled:opacity-40 ${
        active
          ? "bg-violet-500/20 text-violet-200 hover:bg-violet-500/30"
          : "text-muted-foreground hover:bg-white/10 hover:text-foreground"
      }`}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={cycle}
    >
      <BrainIcon active={active} />
    </button>
  );
}
