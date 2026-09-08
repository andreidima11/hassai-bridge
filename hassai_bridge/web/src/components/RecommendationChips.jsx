export function RecommendationChips({ items, onSelect, variant = "empty", className = "" }) {
  const list = Array.isArray(items) ? items.filter((c) => c?.label && c?.prompt) : [];
  if (!list.length) return null;

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
          onClick={() => onSelect?.(chip)}
        >
          <span className="rec-chip-label">{chip.label}</span>
        </button>
      ))}
    </div>
  );
}
