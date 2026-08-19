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
    stop: "Stop",
    stopped: "Stopped",
    settings: "Settings",
    thinking: "Thinking",
    thinkingLive: "Thinking…",
    thinkingBrieflyLive: "Thinking briefly…",
    thoughtBriefly: "Thought briefly",
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
    ha_list_services: "Services",
    ha_list_entity_registry: "Registry",
    ha_get_entity_registry: "Entity",
    ha_update_entity: "Update entity",
    ha_list_areas: "Areas",
    ha_list_devices: "Devices",
    ha_get_device: "Device",
    ha_list_labels: "Labels",
    ha_create_label: "Create label",
    ha_update_label: "Update label",
    ha_create_area: "Create area",
    ha_update_area: "Update area",
    ha_update_device: "Update device",
    ha_set_state: "Set state",
    ha_get_history: "History",
    ha_get_logbook: "Logbook",
    ha_get_entity_source: "Source",
    ha_list_exposed_entities: "Exposed",
    ha_expose_entity: "Expose",
    ha_list_floors: "Floors",
    ha_create_floor: "Create floor",
    ha_update_floor: "Update floor",
    ha_list_automations: "Automations",
    ha_get_automation: "Automation",
    ha_trigger_automation: "Trigger",
    ha_delete_automation: "Delete automation",
    ha_list_scripts: "Scripts",
    ha_run_script: "Run script",
    ha_delete_script: "Delete script",
    ha_list_scenes: "Scenes",
    ha_activate_scene: "Scene",
    ha_delete_scene: "Delete scene",
    ha_list_config_entries: "Integrations",
    ha_get_config_entry: "Integration",
    ha_reload_config_entry: "Reload",
    ha_list_statistic_ids: "Statistics",
    ha_get_statistics: "Stats",
    ha_list_groups: "Groups",
    ha_list_zones: "Zones",
    ha_list_persons: "Persons",
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
    ha_create_dashboard: "Dashboard",
    ha_upsert_view: "View",
    ha_upsert_section: "Section",
    ha_delete_card: "Remove card",
    ha_delete_view: "Remove view",
    ha_update_dashboard: "Update dash",
    ha_delete_dashboard: "Delete dash",
    ha_list_lovelace_resources: "Resources",
    ha_append_card_yaml: "YAML card",
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
    stop: "Oprește",
    stopped: "Oprit",
    settings: "Setări",
    thinking: "Gândește",
    thinkingLive: "Gândește…",
    thinkingBrieflyLive: "Gândește puțin…",
    thoughtBriefly: "A gândit puțin",
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
    ha_list_services: "Servicii",
    ha_list_entity_registry: "Registru",
    ha_get_entity_registry: "Entitate",
    ha_update_entity: "Actualizează entitate",
    ha_list_areas: "Camere",
    ha_list_devices: "Dispozitive",
    ha_get_device: "Dispozitiv",
    ha_set_state: "Setează stare",
    ha_list_labels: "Etichete",
    ha_create_label: "Creează etichetă",
    ha_update_label: "Actualizează etichetă",
    ha_create_area: "Creează cameră",
    ha_update_area: "Actualizează cameră",
    ha_update_device: "Actualizează dispozitiv",
    ha_get_history: "Istoric",
    ha_get_logbook: "Jurnal",
    ha_get_entity_source: "Sursă",
    ha_list_exposed_entities: "Expuse",
    ha_expose_entity: "Expune",
    ha_list_floors: "Etaje",
    ha_create_floor: "Creează etaj",
    ha_update_floor: "Actualizează etaj",
    ha_list_automations: "Automatizări",
    ha_get_automation: "Automatizare",
    ha_trigger_automation: "Declanșează",
    ha_delete_automation: "Șterge automatizare",
    ha_list_scripts: "Scripturi",
    ha_run_script: "Rulează script",
    ha_delete_script: "Șterge script",
    ha_list_scenes: "Scene",
    ha_activate_scene: "Scenă",
    ha_delete_scene: "Șterge scenă",
    ha_list_config_entries: "Integrări",
    ha_get_config_entry: "Integrare",
    ha_reload_config_entry: "Reîncarcă",
    ha_list_statistic_ids: "Statistici",
    ha_get_statistics: "Statistici",
    ha_list_groups: "Grupuri",
    ha_list_zones: "Zone",
    ha_list_persons: "Persoane",
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
    ha_create_dashboard: "Dashboard",
    ha_upsert_view: "Pagină",
    ha_upsert_section: "Secțiune",
    ha_delete_card: "Șterge card",
    ha_delete_view: "Șterge pagină",
    ha_update_dashboard: "Actualizează dash",
    ha_delete_dashboard: "Șterge dash",
    ha_list_lovelace_resources: "Resurse",
    ha_append_card_yaml: "Card YAML",
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
  if (name === "think") return tr(lang, "thoughtBriefly");
  const translated = tr(lang, name);
  return translated === name ? name.replace(/^ha_/, "").replace(/_/g, " ") : translated;
}

export function liveThinkingLabel(lang, thinking) {
  const runningTool = (thinking.steps || []).find((step) => step.status === "running" && step.name !== "think");
  if (runningTool) {
    const verb = activityVerb(lang, runningTool.name);
    const detail = String(runningTool.detail || "").trim();
    if (detail) return `${verb} · ${detail}`;
    return `${verb}…`;
  }
  const runningThink = (thinking.steps || []).find((step) => step.status === "running" && step.name === "think");
  if (runningThink || thinking.active) return tr(lang, "thinkingBrieflyLive");
  return thinking.label || tr(lang, "thoughtBrief");
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
  if (thinkMs > 0 && thinkMs < 4000) return tr(lang, "thoughtBriefly");
  return thinkMs >= 1000
    ? tr(lang, "thoughtFor", { s: (thinkMs / 1000).toFixed(thinkMs >= 10000 ? 0 : 1) })
    : tr(lang, "thoughtBrief");
}
