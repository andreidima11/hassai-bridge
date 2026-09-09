import { useRef } from "react";

const LONG_MS = 450;
const MOVE_PX = 10;

export function RecommendationChips({
  items,
  onSelect,
  onManage,
  variant = "empty",
  className = "",
}) {
  const list = Array.isArray(items) ? items.filter((c) => c?.label && c?.prompt) : [];
  const pressRef = useRef(null);

  if (!list.length) return null;

  const clearPress = () => {
    const p = pressRef.current;
    if (p?.timer) clearTimeout(p.timer);
    pressRef.current = null;
  };

  const startPress = (chip, event) => {
    if (!onManage) return;
    if (event.pointerType === "mouse" && event.button !== 0) return;
    clearPress();
    const x = event.clientX;
    const y = event.clientY;
    pressRef.current = {
      chip,
      x,
      y,
      long: false,
      timer: setTimeout(() => {
        if (!pressRef.current || pressRef.current.chip !== chip) return;
        pressRef.current.long = true;
        onManage(chip);
      }, LONG_MS),
    };
  };

  const movePress = (event) => {
    const p = pressRef.current;
    if (!p) return;
    if (Math.hypot(event.clientX - p.x, event.clientY - p.y) > MOVE_PX) {
      clearPress();
    }
  };

  const endPress = (chip, event) => {
    const p = pressRef.current;
    const wasLong = Boolean(p?.long);
    clearPress();
    if (wasLong) {
      event.preventDefault();
      return;
    }
    onSelect?.(chip);
  };

  return (
    <div
      className={`rec-chips rec-chips--${variant} ${className}`.trim()}
      data-rec-chips={variant}
      role="group"
      aria-label="Suggestions"
    >
      {list.map((chip) => (
        <button
          key={chip.id || chip.prompt}
          type="button"
          className={`rec-chip rec-chip--${chip.kind === "action" ? "action" : "ask"}`}
          onPointerDown={(e) => startPress(chip, e)}
          onPointerMove={movePress}
          onPointerUp={(e) => endPress(chip, e)}
          onPointerCancel={clearPress}
          onPointerLeave={clearPress}
          onContextMenu={(e) => {
            if (!onManage) return;
            e.preventDefault();
            clearPress();
            onManage(chip);
          }}
        >
          <span className="rec-chip-label">{chip.label}</span>
        </button>
      ))}
    </div>
  );
}
