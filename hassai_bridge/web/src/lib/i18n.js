const LANG_STORE_KEY = "hassai.language";

const I18N = {
  en: {
    chats: "Chats",
    newChat: "New",
    noChats: "No chats yet",
    untitled: "New chat",
    deleteConfirm: "Delete this chat?",
    emptyReply: "Empty reply from provider. Check Settings → provider URL, API key, and model.",
    welcome: "What can I help with?",
    welcomeHint: "Ask about devices, dashboards, or Home Assistant.",
    placeholder: "Message HASSAI…",
    settings: "Settings",
    thinking: "Thinking",
    steps: "{n} steps · {s}s",
    thoughtFor: "Thought for {s}s",
    thoughtBrief: "Finished thinking",
    skipped: "skipped",
    copy: "Copy",
    copied: "Copied",
    search_web: "Search",
    run_skill: "Skill",
    ha_list_entities: "List",
    ha_get_state: "State",
    ha_call_service: "Call",
    ha_system_info: "System",
    ha_get_logs: "Logs",
    ha_list_problems: "Problems",
    ha_apply_fix: "Fix",
    ha_check_config: "Check config",
    ha_reload: "Reload",
    ha_list_dashboards: "Dashboards",
    ha_get_dashboard: "Dashboard",
    ha_save_dashboard: "Save dash",
    ha_upsert_card: "Card",
    ha_delete_card: "Remove card",
    ha_list_files: "Files",
    ha_read_file: "Read",
    ha_write_file: "Write",
  },
  ro: {
    chats: "Conversații",
    newChat: "Nou",
    noChats: "Nicio conversație",
    untitled: "Conversație nouă",
    deleteConfirm: "Ștergi această conversație?",
    emptyReply: "Răspuns gol de la provider. Verifică Setări → URL, cheie API și model.",
    welcome: "Cu ce te pot ajuta?",
    welcomeHint: "Întreabă despre dispozitive, dashboard-uri sau Home Assistant.",
    placeholder: "Mesaj către HASSAI…",
    settings: "Setări",
    thinking: "Gândește",
    steps: "{n} pași · {s}s",
    thoughtFor: "A gândit {s}s",
    thoughtBrief: "Gândire terminată",
    skipped: "sărit",
    copy: "Copiază",
    copied: "Copiat",
    search_web: "Caută",
    run_skill: "Skill",
    ha_list_entities: "Listează",
    ha_get_state: "Stare",
    ha_call_service: "Apelează",
    ha_system_info: "Sistem",
    ha_get_logs: "Loguri",
    ha_list_problems: "Probleme",
    ha_apply_fix: "Repară",
    ha_check_config: "Verifică config",
    ha_reload: "Reîncarcă",
    ha_list_dashboards: "Dashboard-uri",
    ha_get_dashboard: "Dashboard",
    ha_save_dashboard: "Salvează dash",
    ha_upsert_card: "Card",
    ha_delete_card: "Șterge card",
    ha_list_files: "Fișiere",
    ha_read_file: "Citește",
    ha_write_file: "Scrie",
  },
};

export function readStoredLang() {
  try {
    const stored = localStorage.getItem(LANG_STORE_KEY);
    if (stored === "ro" || stored === "en") return stored;
  } catch {
    /* ignore */
  }
  return "en";
}

export function persistLang(next) {
  try {
    localStorage.setItem(LANG_STORE_KEY, next);
  } catch {
    /* ignore */
  }
}

export function tr(lang, key, params = {}) {
  const table = I18N[lang] || I18N.en;
  let str = table[key] || I18N.en[key] || key;
  for (const [k, v] of Object.entries(params)) str = str.replaceAll(`{${k}}`, v);
  return str;
}

export function activityVerb(lang, name) {
  if (name === "think") return tr(lang, "thinking");
  const translated = tr(lang, name);
  return translated === name ? name.replace(/^ha_/, "").replace(/_/g, " ") : translated;
}

export function formatMs(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}s`;
}

export function finishThinkingLabel(lang, thinking) {
  const tools = (thinking.steps || []).filter((s) => s.name !== "think");
  const thinkMs = Number(thinking.thinkMs || 0);
  let toolMs = 0;
  for (const s of tools) {
    const t = formatMs(s.ms);
    if (t.endsWith("ms")) toolMs += parseFloat(t) || 0;
    else if (t.endsWith("s")) toolMs += (parseFloat(t) || 0) * 1000;
  }
  const totalMs = Math.max(thinkMs + toolMs, thinkMs, toolMs);
  if (!tools.length && thinkMs <= 0) return "";
  if (tools.length) {
    return tr(lang, "steps", {
      n: tools.length,
      s: (totalMs / 1000).toFixed(totalMs >= 10000 ? 0 : 1),
    });
  }
  return thinkMs >= 1000
    ? tr(lang, "thoughtFor", { s: (thinkMs / 1000).toFixed(thinkMs >= 10000 ? 0 : 1) })
    : tr(lang, "thoughtBrief");
}
