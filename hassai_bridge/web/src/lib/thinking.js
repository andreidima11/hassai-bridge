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
    if (ev.status === "done") {
      next.thinkMs = Number(next.thinkMs || 0) + (Number(ev.ms) || 0);
      next.active = false;
    }
    const id = String(ev.id || `think-${ev.i ?? next.steps.length}`);
    const idx = next.steps.findIndex((s) => s.id === id);
    const prev = idx >= 0 ? next.steps[idx] : null;
    const detail =
      ev.detail != null && String(ev.detail).length
        ? String(ev.detail)
        : prev?.detail || "";
    const row = { id, name: "think", status: ev.status, detail, ms: ev.ms ?? prev?.ms };
    if (idx >= 0) next.steps[idx] = row;
    else next.steps.push(row);
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

/** Steps that represent real actions — the count badge should not include
 *  thinking or the model's own narration. */
export function toolSteps(steps) {
  return (steps || []).filter(
    (step) => step.name !== "think" && step.name !== "say" && step.name !== "route",
  );
}
