const THINKING_STORE_KEY = "hassai.thinking.mode";

export const THINKING_MODES = ["auto", "off", "high", "max"];

export function readStoredThinkingMode(defaultMode = "auto") {
  try {
    const raw = localStorage.getItem(THINKING_STORE_KEY);
    if (raw && THINKING_MODES.includes(raw)) return raw;
  } catch {
    /* ignore */
  }
  return defaultMode;
}

export function persistThinkingMode(mode) {
  try {
    localStorage.setItem(THINKING_STORE_KEY, mode);
  } catch {
    /* ignore */
  }
}

export function hasThinkingCapability(capabilities) {
  return Boolean(capabilities?.thinking?.modes?.length);
}

export function defaultThinkingMode(capabilities) {
  const mode = capabilities?.thinking?.default;
  return THINKING_MODES.includes(mode) ? mode : "auto";
}
