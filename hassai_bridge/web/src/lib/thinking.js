export function emptyThinking(label) {
  return {
    visible: false,
    active: false,
    collapsed: true,
    label,
    thinkMs: 0,
    steps: [],
  };
}

export function applyActivity(thinking, ev, fallbackLabel) {
  const next = {
    ...thinking,
    steps: [...(thinking.steps || [])],
    visible: true,
    label: thinking.label || fallbackLabel,
  };
  const name = ev.name || "think";
  if (name === "think") {
    if (ev.status === "running") next.active = true;
    if (ev.status === "done") next.thinkMs = Number(next.thinkMs || 0) + (Number(ev.ms) || 0);
    return next;
  }
  next.active = ev.status === "running";
  const id = String(ev.id || `i${ev.i ?? ""}`);
  const idx = next.steps.findIndex((s) => s.id === id);
  const row = { id, name, status: ev.status, detail: ev.detail || "", ms: ev.ms };
  if (idx >= 0) next.steps[idx] = row;
  else next.steps.push(row);
  return next;
}
