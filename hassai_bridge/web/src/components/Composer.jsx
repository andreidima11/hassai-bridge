import { useEffect, useRef, useState } from "react";
import { ArrowUpIcon, StopIcon } from "./Icons.jsx";

export function Composer({ value, onChange, onSubmit, onStop, busy, placeholder, stopLabel }) {
  const ref = useRef(null);
  const [tall, setTall] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(Math.max(el.scrollHeight, 24), 160);
    el.style.height = `${next}px`;
    setTall(next > 28);
  }, [value]);

  return (
    <div className="sticky bottom-0 z-[1] mx-auto flex w-full max-w-4xl bg-background px-3 pb-3 md:px-4 md:pb-4">
      <form
        className={`flex w-full gap-2 overflow-hidden border border-white/[0.08] bg-composer pl-4 pr-1.5 shadow-composer transition-[border-radius] duration-200 focus-within:border-white/15 ${
          tall ? "items-end rounded-3xl py-2" : "items-center rounded-full py-1"
        }`}
        onSubmit={onSubmit}
      >
        <textarea
          ref={ref}
          className="block max-h-40 min-h-6 w-full flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-6 text-foreground placeholder:text-muted-foreground/50"
          enterKeyHint="send"
          placeholder={placeholder}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              if (busy) return;
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        {busy ? (
          <button
            className="mb-0 grid size-8 shrink-0 place-items-center rounded-full bg-white text-black transition hover:opacity-90 active:scale-95"
            type="button"
            aria-label={stopLabel}
            title={stopLabel}
            onClick={onStop}
          >
            <StopIcon />
          </button>
        ) : (
          <button
            className="mb-0 grid size-8 shrink-0 place-items-center rounded-full bg-white text-black transition hover:opacity-90 active:scale-95 disabled:cursor-not-allowed disabled:bg-white/15 disabled:text-white/35"
            disabled={!value.trim()}
            type="submit"
          >
            <ArrowUpIcon />
          </button>
        )}
      </form>
    </div>
  );
}
