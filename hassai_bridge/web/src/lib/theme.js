const HA_MAP = [
  ["--primary-background-color", "--background"],
  ["--primary-background-color", "--sidebar"],
  ["--card-background-color", "--card"],
  ["--card-background-color", "--composer"],
  ["--card-background-color", "--muted"],
  ["--secondary-background-color", "--secondary"],
  ["--primary-text-color", "--foreground"],
  ["--secondary-text-color", "--muted-foreground"],
  ["--divider-color", "--border"],
];

export function syncHaTheme() {
  const el = document.documentElement;
  try {
    const parentRoot = window.parent?.document?.documentElement;
    if (!parentRoot || parentRoot === el) return;
    const ps = getComputedStyle(parentRoot);
    for (const [src, dst] of HA_MAP) {
      const val = ps.getPropertyValue(src).trim();
      if (val) el.style.setProperty(dst, val);
    }
  } catch {
    /* ingress cross-origin or unavailable */
  }
}
