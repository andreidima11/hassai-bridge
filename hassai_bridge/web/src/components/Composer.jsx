import { useEffect, useRef } from "react";
import { ArrowUpIcon } from "./Icons.jsx";

export function Composer({ value, onChange, onSubmit, disabled, placeholder }) {
  const ref = useRef(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "44px";
    el.style.height = `${Math.min(Math.max(el.scrollHeight, 44), 160)}px`;
  }, [value]);

  return (
    <div className="sticky bottom-0 z-[1] mx-auto flex w-full max-w-4xl gap-2 bg-background px-2 pb-3 md:px-4 md:pb-4">
      <form
        className="flex w-full flex-col rounded-2xl border border-border/30 bg-card/70 shadow-composer transition-shadow duration-300 focus-within:shadow-composer-focus"
        onSubmit={onSubmit}
      >
        <textarea
          ref={ref}
          className="block w-full resize-none bg-transparent px-4 pb-1.5 pt-3.5 text-[13px] leading-relaxed text-foreground placeholder:text-muted-foreground/35"
          enterKeyHint="send"
          placeholder={placeholder}
          rows={1}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              e.currentTarget.form?.requestSubmit();
            }
          }}
        />
        <div className="flex items-center justify-end px-2 pb-2 pt-1">
          <button
            className="grid size-7 place-items-center rounded-xl bg-foreground text-background transition hover:opacity-85 active:scale-95 disabled:cursor-not-allowed disabled:bg-muted disabled:text-muted-foreground/25"
            disabled={disabled || !value.trim()}
            type="submit"
          >
            <ArrowUpIcon />
          </button>
        </div>
      </form>
    </div>
  );
}
