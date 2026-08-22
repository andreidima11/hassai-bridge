import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { ChevronIcon } from "./Icons.jsx";

const MENU_GAP_PX = 6;
const MENU_MAX_HEIGHT_PX = 208; // max-h-52

/**
 * Themed listbox — replaces native &lt;select&gt; so provider/model pickers
 * match the chat composer (no OS chrome).
 */
export function ThemeSelect({
  value = "",
  options = [],
  onChange,
  placeholder = "—",
  disabled = false,
  "aria-label": ariaLabel,
}) {
  const listId = useId();
  const rootRef = useRef(null);
  const triggerRef = useRef(null);
  const [open, setOpen] = useState(false);
  const [placement, setPlacement] = useState("down");
  const [menuMaxHeight, setMenuMaxHeight] = useState(MENU_MAX_HEIGHT_PX);
  const selected = options.find((row) => row.value === value);
  const label = selected?.label || value || placeholder;

  useLayoutEffect(() => {
    if (!open || !triggerRef.current) return undefined;

    const updatePlacement = () => {
      const rect = triggerRef.current.getBoundingClientRect();
      const spaceBelow = window.innerHeight - rect.bottom - MENU_GAP_PX;
      const spaceAbove = rect.top - MENU_GAP_PX;
      const openUp = spaceBelow < 120 && spaceAbove > spaceBelow;
      const side = openUp ? "up" : "down";
      setPlacement(side);
      const available = openUp ? spaceAbove : spaceBelow;
      setMenuMaxHeight(Math.max(96, Math.min(MENU_MAX_HEIGHT_PX, Math.floor(available))));
    };

    updatePlacement();
    window.addEventListener("resize", updatePlacement);
    window.addEventListener("scroll", updatePlacement, true);
    return () => {
      window.removeEventListener("resize", updatePlacement);
      window.removeEventListener("scroll", updatePlacement, true);
    };
  }, [open, options.length]);

  useEffect(() => {
    if (!open) return undefined;
    const onDoc = (event) => {
      if (rootRef.current?.contains(event.target)) return;
      setOpen(false);
    };
    const onKey = (event) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const menuPositionClass =
    placement === "up" ? "bottom-[calc(100%+6px)]" : "top-[calc(100%+6px)]";

  return (
    <div ref={rootRef} className="theme-select relative">
      <button
        ref={triggerRef}
        type="button"
        className="theme-select__trigger flex w-full items-center gap-2 rounded-xl border border-white/10 bg-secondary/70 px-3 py-2.5 text-left text-[13px] text-foreground transition hover:border-white/18 hover:bg-secondary disabled:cursor-not-allowed disabled:opacity-50"
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-controls={listId}
        aria-label={ariaLabel}
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="min-w-0 flex-1 truncate">{label}</span>
        <ChevronIcon
          className={`shrink-0 text-muted-foreground transition-transform duration-200 ease-spring ${
            open ? "rotate-180" : ""
          }`}
        />
      </button>

      {open ? (
        <ul
          id={listId}
          role="listbox"
          aria-label={ariaLabel}
          className={`theme-select__menu absolute left-0 right-0 z-[60] overflow-y-auto rounded-xl border border-white/10 bg-card p-1 shadow-float ${menuPositionClass}`}
          style={{ maxHeight: menuMaxHeight }}
        >
          {options.map((row) => {
            const active = row.value === value;
            return (
              <li key={row.value} role="presentation">
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  className={`flex w-full items-center rounded-[10px] px-2.5 py-2 text-left text-[13px] transition ${
                    active
                      ? "bg-white/12 text-foreground"
                      : "text-muted-foreground hover:bg-white/[0.06] hover:text-foreground"
                  }`}
                  onClick={() => {
                    onChange?.(row.value);
                    setOpen(false);
                  }}
                >
                  <span className="min-w-0 flex-1 truncate">{row.label}</span>
                  {active ? (
                    <span className="ml-2 size-1.5 shrink-0 rounded-full bg-foreground/80" aria-hidden="true" />
                  ) : null}
                </button>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
