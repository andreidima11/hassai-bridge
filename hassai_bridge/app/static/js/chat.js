/* HASSAI Bridge — Agentic chat client */

const API = (typeof window.HASSAI_BASE === "string" ? window.HASSAI_BASE : "").replace(/\/$/, "");
const ON_INGRESS = /\/api\/hassio_ingress\//.test(API || location.pathname);

const messagesEl = document.getElementById("chatMessages");
const welcomeEl = document.getElementById("chatWelcome");
const formEl = document.getElementById("chatForm");
const inputEl = document.getElementById("chatInput");
const sendEl = document.getElementById("chatSend");
const mainEl = document.getElementById("chatMain");
const sidebarEl = document.getElementById("chatSidebar");
const backdropEl = document.getElementById("sidebarBackdrop");
const sessionListEl = document.getElementById("chatSessionList");
const userLabelEl = document.getElementById("chatUserLabel");

/** @type {{role: string, content: string}[]} */
const history = [];
let busy = false;
let sessionId = "";
let currentUser = { username: "default", display_name: "default" };
let sessions = [];
const LANG_STORE_KEY = "hassai.language";

function getChatLang() {
  const v = window.HASSAI_CHAT_LANG;
  return v === "ro" ? "ro" : "en";
}

function syncGlobalLang(next) {
  const resolved = next === "ro" ? "ro" : "en";
  window.HASSAI_CHAT_LANG = resolved;
  try { lang = resolved; } catch (_) { /* legacy global from index.html */ }
  return resolved;
}
let bootDone = false;
let panelHiddenAt = 0;
let keyboardSyncRaf = 0;

const I18N = {
  en: {
    you: "You",
    chats: "Chats",
    newChat: "New",
    noChats: "No chats yet",
    untitled: "New chat",
    deleteConfirm: "Delete this chat?",
    emptyReply: "Empty reply from provider. Check Settings → provider URL, API key, and model.",
    haOk: "Connected to Home Assistant — you can ask about devices and control them here.",
    haToken: "Home Assistant token is present; Core ping failed ({detail}). Chat still works; retry in a moment.",
    haOff: "Not running as a Home Assistant add-on — HA admin tools are off.",
    welcome: "Your Home Assistant copilot.",
    placeholder: "Message HASSAI…",
    settings: "Settings",
    thinking: "Thinking",
    working: "Working",
    steps: "{n} steps · {s}s",
    thoughtFor: "Thought for {s}s",
    thoughtBrief: "Finished thinking",
    skipped: "skipped",
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
    you: "Tu",
    chats: "Conversații",
    newChat: "Nou",
    noChats: "Nicio conversație",
    untitled: "Conversație nouă",
    deleteConfirm: "Ștergi această conversație?",
    emptyReply: "Răspuns gol de la provider. Verifică Setări → URL, cheie API și model.",
    haOk: "Conectat la Home Assistant — poți întreba despre dispozitive și le poți controla de aici.",
    haToken: "Token-ul Home Assistant e prezent; ping-ul către Core a eșuat ({detail}). Chat-ul merge; reîncearcă imediat.",
    haOff: "Nu rulează ca add-on Home Assistant — uneltele de admin HA sunt oprite.",
    welcome: "Copilotul tău pentru Home Assistant.",
    placeholder: "Mesaj către HASSAI…",
    settings: "Setări",
    thinking: "Gândește",
    working: "Lucrează",
    steps: "{n} pași · {s}s",
    thoughtFor: "A gândit {s}s",
    thoughtBrief: "Gândire terminată",
    skipped: "sărit",
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

function readStoredLang() {
  try {
    const stored = localStorage.getItem(LANG_STORE_KEY);
    if (stored === "ro" || stored === "en") return stored;
  } catch (_) { /* ignore */ }
  return "";
}

syncGlobalLang(readStoredLang() || "en");

function persistLang(next) {
  try { localStorage.setItem(LANG_STORE_KEY, next); } catch (_) { /* ignore */ }
}

function ensureFreshBuild(serverBuild) {
  const local = typeof window.HASSAI_BUILD === "string" ? window.HASSAI_BUILD : "";
  if (!serverBuild || !local || serverBuild === local) return;
  try {
    const u = new URL(location.href);
    if (u.searchParams.get("_b") === serverBuild) return;
    u.searchParams.set("_b", serverBuild);
    location.replace(u.href);
  } catch (_) { /* ignore */ }
}

function replayActivity(traceEl, events) {
  if (!traceEl || !Array.isArray(events) || !events.length) return;
  events.forEach((ev) => applyActivity(traceEl, ev, { quiet: true }));
  finishTrace(traceEl);
}

function setChatLang(next) {
  const resolved = syncGlobalLang(next);
  persistLang(resolved);
  applyChatI18n();
}

function tr(key, params = {}) {
  const table = I18N[getChatLang()] || I18N.en;
  let str = table[key] || I18N.en[key] || key;
  for (const [k, v] of Object.entries(params)) str = str.replaceAll(`{${k}}`, v);
  return str;
}

function applyChatI18n() {
  document.documentElement.lang = getChatLang();
  const title = document.getElementById("chatSidebarTitle");
  const neu = document.getElementById("newChatBtn");
  const welcomeText = document.getElementById("chatWelcomeText");
  const settings = document.getElementById("chatSettingsLink");
  const toggle = document.getElementById("sidebarToggle");
  if (title) title.textContent = tr("chats");
  if (neu) neu.textContent = tr("newChat");
  if (welcomeText) welcomeText.textContent = tr("welcome");
  if (inputEl) inputEl.placeholder = tr("placeholder");
  if (settings) {
    settings.title = tr("settings");
    settings.setAttribute("aria-label", tr("settings"));
  }
  if (toggle) {
    toggle.title = tr("chats");
    toggle.setAttribute("aria-label", tr("chats"));
  }
}

function sessionStoreKey() {
  return `hassai.chat.session.${currentUser.username || "default"}`;
}

function loadStoredSession() {
  try { return localStorage.getItem(sessionStoreKey()) || ""; } catch (_) { return ""; }
}

function storeSession(id) {
  try {
    if (id) localStorage.setItem(sessionStoreKey(), id);
    else localStorage.removeItem(sessionStoreKey());
  } catch (_) { /* ignore */ }
}

function newSessionId() {
  const bytes = new Uint8Array(6);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function apiJson(path, opts = {}) {
  const resp = await fetch(API + path, {
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(opts.headers || {}) },
    ...opts,
  });
  if (!resp.ok) {
    throw new Error(await readError(resp));
  }
  if (resp.status === 204) return {};
  return resp.json();
}

function showThread() {
  welcomeEl.hidden = true;
  messagesEl.hidden = false;
}

function clearThread() {
  history.length = 0;
  messagesEl.innerHTML = "";
  welcomeEl.hidden = false;
  messagesEl.hidden = true;
}

function appendMessage(role, content, { error = false, streaming = false } = {}) {
  showThread();
  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}${error ? " msg-error" : ""}${streaming ? " streaming" : ""}`;

  const roleEl = document.createElement("div");
  roleEl.className = "msg-role";
  roleEl.textContent = role === "user" ? tr("you") : "HASSAI";

  let traceEl = null;
  let thinkingEl = null;
  if (role === "assistant") {
    thinkingEl = document.createElement("div");
    thinkingEl.className = "agent-thinking is-collapsed";
    thinkingEl.hidden = true;

    const head = document.createElement("button");
    head.type = "button";
    head.className = "agent-thinking-head";
    head.innerHTML =
      '<span class="agent-thinking-dot" aria-hidden="true"></span>' +
      `<span class="agent-thinking-label">${escapeHtml(tr("thinking"))}</span>` +
      '<span class="agent-thinking-chevron" aria-hidden="true">›</span>';
    head.addEventListener("click", () => {
      if (thinkingEl.classList.contains("has-steps")) {
        thinkingEl.classList.toggle("is-collapsed");
      }
    });

    traceEl = document.createElement("div");
    traceEl.className = "agent-trace";

    thinkingEl.appendChild(head);
    thinkingEl.appendChild(traceEl);
  }

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble msg-answer";
  bubble.textContent = content || "";
  if (role === "assistant" && !content) bubble.hidden = true;

  wrap.appendChild(roleEl);
  if (thinkingEl) wrap.appendChild(thinkingEl);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  mainEl.scrollTop = mainEl.scrollHeight;
  return { wrap, bubble, traceEl, thinkingEl };
}

function setBubbleText(bubble, text) {
  bubble.textContent = text || "";
  bubble.hidden = !text;
}

function activityVerb(name) {
  if (name === "think") return tr("thinking");
  return tr(name) === name ? name.replace(/^ha_/, "").replace(/_/g, " ") : tr(name);
}

function formatMs(ms) {
  const n = Number(ms);
  if (!Number.isFinite(n) || n < 0) return "";
  if (n < 1000) return `${Math.round(n)}ms`;
  return `${(n / 1000).toFixed(n >= 10000 ? 0 : 1)}s`;
}

function thinkingPanel(traceEl) {
  return traceEl?.closest(".agent-thinking") || null;
}

function showThinkingPanel(thinkingEl, active) {
  if (!thinkingEl) return;
  thinkingEl.hidden = false;
  thinkingEl.classList.toggle("is-active", !!active);
  if (active && !thinkingEl.classList.contains("has-summary")) {
    const label = thinkingEl.querySelector(".agent-thinking-label");
    if (label) label.textContent = tr("thinking");
  }
}

function addThinkMs(thinkingEl, ms) {
  if (!thinkingEl) return;
  const n = Number(ms);
  if (!Number.isFinite(n) || n <= 0) return;
  const prev = Number(thinkingEl.dataset.thinkMs || 0);
  thinkingEl.dataset.thinkMs = String(prev + n);
}

function applyActivity(traceEl, ev, opts = {}) {
  if (!traceEl || !ev) return;
  const thinkingEl = thinkingPanel(traceEl);
  const name = ev.name || "think";

  if (name === "think") {
    if (ev.status === "running") showThinkingPanel(thinkingEl, true);
    if (ev.status === "done") addThinkMs(thinkingEl, ev.ms);
    if (!opts.quiet) mainEl.scrollTop = mainEl.scrollHeight;
    return;
  }

  showThinkingPanel(thinkingEl, ev.status === "running");

  const id = String(ev.id || `i${ev.i ?? ""}`);
  let row = null;
  for (const child of traceEl.querySelectorAll(".agent-step")) {
    if (child.dataset.aid === id) { row = child; break; }
  }
  if (!row) {
    row = document.createElement("div");
    row.className = "agent-step";
    row.dataset.aid = id;
    traceEl.appendChild(row);
  }
  row.dataset.name = name;
  row.classList.toggle("is-run", ev.status === "running");
  row.classList.toggle("is-done", ev.status === "done");
  row.classList.toggle("is-skip", ev.status === "skip");
  const ms = formatMs(ev.ms);
  const detail = ev.detail ? escapeHtml(ev.detail) : "";
  const skip = ev.status === "skip" ? `<span class="agent-skip">${escapeHtml(tr("skipped"))}</span>` : "";
  row.innerHTML =
    `<span class="agent-mark"></span>` +
    `<span class="agent-verb">${escapeHtml(activityVerb(name))}</span>` +
    (detail ? `<span class="agent-detail">${detail}</span>` : "") +
    skip +
    (ms ? `<span class="agent-ms">${escapeHtml(ms)}</span>` : "");
  if (thinkingEl) thinkingEl.classList.add("has-steps");
  if (!opts.quiet) mainEl.scrollTop = mainEl.scrollHeight;
}

function finishTrace(traceEl) {
  if (!traceEl) return;
  const thinkingEl = thinkingPanel(traceEl);
  if (!thinkingEl) return;

  thinkingEl.classList.remove("is-active");
  const steps = [...traceEl.querySelectorAll(".agent-step")];
  const tools = steps.filter((el) => el.dataset.name !== "think");
  const label = thinkingEl.querySelector(".agent-thinking-label");
  const thinkMs = Number(thinkingEl.dataset.thinkMs || 0);

  if (!tools.length && thinkMs <= 0) {
    thinkingEl.hidden = true;
    return;
  }

  let toolMs = 0;
  for (const el of tools) {
    const t = el.querySelector(".agent-ms")?.textContent || "";
    if (t.endsWith("ms")) toolMs += parseFloat(t) || 0;
    else if (t.endsWith("s")) toolMs += (parseFloat(t) || 0) * 1000;
  }
  const totalMs = Math.max(thinkMs + toolMs, thinkMs, toolMs);

  if (label) {
    if (tools.length) {
      label.textContent = tr("steps", {
        n: tools.length,
        s: (totalMs / 1000).toFixed(totalMs >= 10000 ? 0 : 1),
      });
    } else {
      label.textContent = thinkMs >= 1000
        ? tr("thoughtFor", { s: (thinkMs / 1000).toFixed(thinkMs >= 10000 ? 0 : 1) })
        : tr("thoughtBrief");
    }
  }

  thinkingEl.classList.add("has-summary");
  thinkingEl.classList.toggle("has-steps", tools.length > 0);
  thinkingEl.classList.add("is-collapsed");
  thinkingEl.hidden = false;
}

function startActivityPoll(traceId, onEvent) {
  let after = -1;
  let stopped = false;
  const tick = async () => {
    if (stopped) return;
    try {
      const data = await apiJson(`/v1/chat/activity/${encodeURIComponent(traceId)}?after=${after}`);
      for (const ev of data.events || []) onEvent(ev);
      if (typeof data.after === "number") after = data.after;
      if (data.done) return;
    } catch (_) { /* retry — ingress may start the trace slightly later */ }
    if (!stopped) setTimeout(tick, ON_INGRESS ? 240 : 320);
  };
  tick();
  return () => { stopped = true; };
}

function sessionTitle(row) {
  const raw = String(row.title || "").replace(/\s+/g, " ").trim();
  return raw ? raw.slice(0, 56) : tr("untitled");
}

function renderSessions() {
  if (!sessionListEl) return;
  const inDb = sessions.some((s) => s.session_id === sessionId);
  const rows = [];
  if (sessionId && !inDb) {
    rows.push({ session_id: sessionId, title: tr("untitled"), message_count: 0 });
  }
  rows.push(...sessions);
  if (!rows.length) {
    sessionListEl.innerHTML = `<div class="chat-sidebar-empty">${tr("noChats")}</div>`;
    return;
  }
  sessionListEl.innerHTML = rows.map((s) => {
    const active = s.session_id === sessionId ? " active" : "";
    const id = encodeURIComponent(s.session_id);
    return `<div class="chat-session${active}" data-session="${id}">
      <span class="chat-session-title">${escapeHtml(sessionTitle(s))}</span>
      <button type="button" class="chat-session-del" data-del="${id}" aria-label="Delete">×</button>
    </div>`;
  }).join("");
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function setSidebar(open) {
  const show = !!open;
  if (sidebarEl) {
    sidebarEl.classList.toggle("is-open", show);
    sidebarEl.setAttribute("aria-hidden", show ? "false" : "true");
  }
  if (backdropEl) {
    backdropEl.classList.toggle("is-open", show);
    backdropEl.setAttribute("aria-hidden", show ? "false" : "true");
  }
  document.body.classList.toggle("sidebar-open", show);
}

function toggleSidebar(event) {
  if (event) {
    event.preventDefault();
    event.stopPropagation();
  }
  const open = !(sidebarEl && sidebarEl.classList.contains("is-open"));
  setSidebar(open);
}

window.__hassaiToggleSidebar = toggleSidebar;

function startNewChat(options) {
  const focus = !(options && options.focus === false);
  const persist = !(options && options.ephemeral);
  sessionId = newSessionId();
  if (persist) storeSession(sessionId);
  else {
    try { localStorage.removeItem(sessionStoreKey()); } catch (_) { /* ignore */ }
  }
  clearThread();
  renderSessions();
  setSidebar(false);
  if (focus) inputEl.focus({ preventScroll: true });
}

async function refreshSessions() {
  const data = await apiJson("/api/conversations?limit=80");
  sessions = data.sessions || [];
  renderSessions();
}

async function openSession(id) {
  sessionId = id;
  storeSession(id);
  const data = await apiJson(`/api/conversations/${encodeURIComponent(id)}`);
  history.length = 0;
  messagesEl.innerHTML = "";
  const msgs = data.messages || [];
  if (!msgs.length) {
    welcomeEl.hidden = false;
    messagesEl.hidden = true;
  } else {
    for (const m of msgs) {
      if (m.role === "user" || m.role === "assistant") {
        history.push({ role: m.role, content: m.content || "" });
        const ui = appendMessage(m.role, m.content || "");
        if (m.role === "assistant") replayActivity(ui.traceEl, m.activity);
      }
    }
  }
  renderSessions();
  setSidebar(false);
}

async function deleteSession(id) {
  if (!confirm(tr("deleteConfirm"))) return;
  const inDb = sessions.some((s) => s.session_id === id);
  if (inDb) {
    await apiJson(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
  }
  if (sessionId === id) startNewChat({ focus: false });
  await refreshSessions();
}

async function bootIdentity() {
  const data = await apiJson("/api/me");
  ensureFreshBuild(data.build);
  currentUser = data.user || currentUser;
  syncGlobalLang(data.language === "ro" ? "ro" : "en");
  persistLang(getChatLang());
  applyChatI18n();
  if (userLabelEl) {
    const name = currentUser.display_name || currentUser.username || "";
    userLabelEl.textContent = name;
  }
  await refreshSessions();
  startNewChat({ focus: false, ephemeral: true });
  bootDone = true;
}

function onPanelReopen() {
  if (!bootDone || busy) return;
  if (panelHiddenAt > 0) startNewChat({ focus: false, ephemeral: true });
}

function autosize() {
  inputEl.style.height = "24px";
  const next = Math.min(Math.max(inputEl.scrollHeight, 24), 160);
  inputEl.style.height = next + "px";
  formEl.style.alignItems = next > 28 ? "flex-end" : "center";
}

inputEl.addEventListener("input", autosize);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

function keepPagePinned() {
  window.scrollTo(0, 0);
  document.documentElement.scrollTop = 0;
  document.body.scrollTop = 0;
  try { window.visualViewport?.scrollTo?.(0, 0); } catch (_) { /* ignore */ }
}

function lockAppHeight() {
  const h = window.innerHeight || document.documentElement.clientHeight || 0;
  if (!h) return;
  if (!window.__hassaiRestH || h > window.__hassaiRestH + 24) {
    window.__hassaiRestH = h;
    document.documentElement.style.setProperty("--app-height", `${h}px`);
  }
}

/** Visible bottom, in iframe CSS pixels. Prefer parent visualViewport (HA + browser chrome). */
function visualBottomPx() {
  const bottoms = [];
  const local = window.visualViewport;
  if (local) bottoms.push(local.offsetTop + local.height);
  bottoms.push(window.innerHeight || document.documentElement.clientHeight || 0);

  try {
    const parentWin = window.parent && window.parent !== window ? window.parent : null;
    const frame = window.frameElement;
    const pvv = parentWin?.visualViewport;
    if (parentWin && pvv) {
      const frameTop = frame ? frame.getBoundingClientRect().top : 0;
      bottoms.push(pvv.offsetTop + pvv.height - frameTop);
    }
  } catch (_) { /* ignore */ }

  try {
    const topWin = window.top && window.top !== window ? window.top : null;
    const tvv = topWin?.visualViewport;
    const frame = window.frameElement;
    if (tvv && frame && topWin !== window.parent) {
      const frameTop = frame.getBoundingClientRect().top;
      bottoms.push(tvv.offsetTop + tvv.height - frameTop);
    }
  } catch (_) { /* ignore */ }

  try {
    const vk = navigator.virtualKeyboard;
    if (vk?.boundingRect?.height > 0) bottoms.push(vk.boundingRect.top);
  } catch (_) { /* ignore */ }

  const valid = bottoms.filter((n) => Number.isFinite(n) && n > 64);
  return valid.length ? Math.min(...valid) : (window.innerHeight || 0);
}

function placeComposer() {
  const composer = document.querySelector(".chat-composer");
  if (!composer) return;
  const height = composer.offsetHeight || 92;
  const layoutH = window.innerHeight || document.documentElement.clientHeight || 0;
  const visBottom = visualBottomPx();
  const inset = Math.max(0, Math.round(layoutH - visBottom));
  composer.style.top = "auto";
  composer.style.bottom = `${inset}px`;
  document.documentElement.style.setProperty("--kb-offset", `${inset}px`);
  document.documentElement.style.setProperty("--composer-space", `${height}px`);
}

function syncKeyboardLayout() {
  keepPagePinned();
  lockAppHeight();
  placeComposer();
  const focused = document.activeElement === inputEl;
  document.body.classList.toggle("chat-kb-open", focused);
  if (welcomeEl && !welcomeEl.hidden && mainEl) mainEl.scrollTop = 0;
}

function startKeyboardSync() {
  if (keyboardSyncRaf) return;
  const tick = () => {
    syncKeyboardLayout();
    if (document.activeElement === inputEl) {
      keyboardSyncRaf = requestAnimationFrame(tick);
    } else {
      keyboardSyncRaf = 0;
    }
  };
  keyboardSyncRaf = requestAnimationFrame(tick);
}

function stopKeyboardSync() {
  if (keyboardSyncRaf) {
    cancelAnimationFrame(keyboardSyncRaf);
    keyboardSyncRaf = 0;
  }
}

try {
  if (navigator.virtualKeyboard) {
    navigator.virtualKeyboard.overlaysContent = true;
    navigator.virtualKeyboard.addEventListener("geometrychange", syncKeyboardLayout);
  }
} catch (_) { /* ignore */ }

inputEl.addEventListener("focus", () => {
  keepPagePinned();
  syncKeyboardLayout();
  startKeyboardSync();
  requestAnimationFrame(syncKeyboardLayout);
  setTimeout(syncKeyboardLayout, 50);
  setTimeout(syncKeyboardLayout, 280);
  setTimeout(syncKeyboardLayout, 520);
});
inputEl.addEventListener("blur", () => {
  stopKeyboardSync();
  setTimeout(syncKeyboardLayout, 50);
});
document.querySelector(".chat-composer")?.addEventListener("pointerdown", () => {
  startKeyboardSync();
  syncKeyboardLayout();
}, { passive: true });
window.addEventListener("scroll", keepPagePinned, { passive: true });
window.addEventListener("resize", syncKeyboardLayout, { passive: true });
window.addEventListener("orientationchange", () => {
  window.__hassaiRestH = 0;
  setTimeout(syncKeyboardLayout, 80);
  setTimeout(syncKeyboardLayout, 320);
});
window.visualViewport?.addEventListener("resize", syncKeyboardLayout);
window.visualViewport?.addEventListener("scroll", () => {
  keepPagePinned();
  syncKeyboardLayout();
});
try {
  const pvv = window.parent?.visualViewport;
  pvv?.addEventListener("resize", syncKeyboardLayout);
  pvv?.addEventListener("scroll", syncKeyboardLayout);
} catch (_) { /* ignore */ }
try {
  const tvv = window.top?.visualViewport;
  if (tvv && tvv !== window.visualViewport && tvv !== window.parent?.visualViewport) {
    tvv.addEventListener("resize", syncKeyboardLayout);
    tvv.addEventListener("scroll", syncKeyboardLayout);
  }
} catch (_) { /* ignore */ }
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") {
    panelHiddenAt = Date.now();
    stopKeyboardSync();
    return;
  }
  onPanelReopen();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) onPanelReopen();
});

const sidebarToggleEl = document.getElementById("sidebarToggle");
sidebarToggleEl?.addEventListener("click", toggleSidebar);
backdropEl?.addEventListener("click", () => setSidebar(false));
document.getElementById("newChatBtn")?.addEventListener("click", () => startNewChat());
sessionListEl?.addEventListener("click", (e) => {
  const del = e.target.closest("[data-del]");
  if (del) {
    e.preventDefault();
    e.stopPropagation();
    deleteSession(decodeURIComponent(del.getAttribute("data-del")));
    return;
  }
  const row = e.target.closest("[data-session]");
  if (row) openSession(decodeURIComponent(row.getAttribute("data-session")));
});

function extractText(payload) {
  const choice = payload?.choices?.[0] || {};
  const delta = choice.delta || {};
  const msg = choice.message || {};
  return (
    delta.content ||
    delta.reasoning_content ||
    msg.content ||
    msg.reasoning_content ||
    payload?.error?.message ||
    ""
  );
}

async function readError(resp) {
  const errText = await resp.text().catch(() => "");
  try {
    const j = JSON.parse(errText);
    return j?.error?.message || j?.detail || `HTTP ${resp.status}`;
  } catch (_) {
    return errText ? errText.slice(0, 240) : `HTTP ${resp.status}`;
  }
}

async function postChat(stream, userText, traceId) {
  return fetch(API + "/v1/chat/completions", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: [{ role: "user", content: userText }],
      stream,
      session_id: sessionId,
      trace_id: traceId,
    }),
  });
}

async function completeNonStream(ui, userText) {
  const resp = await postChat(false, userText, ui.traceId);
  if (!resp.ok) throw new Error(await readError(resp));
  const data = await resp.json();
  if (Array.isArray(data.hassai_activity)) {
    data.hassai_activity.forEach((ev) => applyActivity(ui.traceEl, ev));
  }
  const text = extractText(data);
  if (!text) {
    throw new Error(tr("emptyReply"));
  }
  setBubbleText(ui.bubble, text);
  mainEl.scrollTop = mainEl.scrollHeight;
  return text;
}

async function completeStream(ui, userText) {
  const resp = await postChat(true, userText, ui.traceId);
  if (!resp.ok) throw new Error(await readError(resp));
  if (!resp.body) throw new Error("No stream body (Ingress blocked SSE)");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n");
    buffer = parts.pop() || "";

    for (const line of parts) {
      const trimmed = line.trim();
      if (!trimmed.startsWith("data:")) continue;
      const payload = trimmed.slice(5).trim();
      if (payload === "[DONE]") continue;
      try {
        const chunk = JSON.parse(payload);
        if (chunk && chunk.hassai === "activity") {
          applyActivity(ui.traceEl, chunk);
          continue;
        }
        const delta = extractText(chunk);
        if (delta) {
          full += delta;
          setBubbleText(ui.bubble, full);
          mainEl.scrollTop = mainEl.scrollHeight;
        }
      } catch (_) {
        /* keepalive / partial JSON */
      }
    }
  }
  return full;
}

async function streamChat(userText) {
  if (!sessionId) startNewChat({ focus: false, ephemeral: true });
  storeSession(sessionId);
  history.push({ role: "user", content: userText });
  appendMessage("user", userText);

  const { wrap, bubble, traceEl, thinkingEl } = appendMessage("assistant", "", { streaming: true });
  showThinkingPanel(thinkingEl, true);
  const traceId = `${newSessionId()}${newSessionId()}`;
  const ui = { wrap, bubble, traceEl, thinkingEl, traceId };
  const stopPoll = startActivityPoll(traceId, (ev) => applyActivity(traceEl, ev));
  let full = "";

  try {
    // Companion app / Ingress WebViews often drop SSE → empty reply.
    // Use JSON there; stream on direct :8899. Activity still arrives via poll.
    if (ON_INGRESS) {
      full = await completeNonStream(ui, userText);
    } else {
      try {
        full = await completeStream(ui, userText);
      } catch (e) {
        full = "";
        if (!String(e.message || "").includes("Empty reply")) {
          /* stream transport error — fall through */
        }
      }
      if (!full) {
        full = await completeNonStream(ui, userText);
      }
    }
  } catch (err) {
    wrap.classList.add("msg-error");
    setBubbleText(bubble, err.message || "Request failed");
    history.pop();
    throw err;
  } finally {
    stopPoll();
    finishTrace(traceEl);
    wrap.classList.remove("streaming");
  }

  history.push({ role: "assistant", content: full || "" });
  refreshSessions().catch(() => {});
}

formEl.addEventListener("submit", async (e) => {
  e.preventDefault();
  if (busy) return;
  const text = inputEl.value.trim();
  if (!text) return;

  busy = true;
  sendEl.disabled = true;
  inputEl.value = "";
  autosize();

  try {
    await streamChat(text);
  } catch (err) {
    if (!messagesEl.querySelector(".msg-error:last-child")) {
      appendMessage("assistant", err.message || "Request failed", { error: true });
    }
  } finally {
    busy = false;
    sendEl.disabled = false;
    if (!window.matchMedia("(pointer: coarse)").matches) inputEl.focus({ preventScroll: true });
  }
});

(async () => {
  applyChatI18n();
  try {
    await bootIdentity();
  } catch (_) {
    startNewChat({ focus: false, ephemeral: true });
    bootDone = true;
    try {
      const info = await fetch(API + "/api/settings/info").then((r) => r.json());
      if (info && info.build) ensureFreshBuild(info.build);
      if (info && info.language) setChatLang(info.language);
    } catch (_) { /* ignore */ }
    try {
      const cfg = await fetch(API + "/api/settings/").then((r) => r.json());
      if (cfg && cfg.language) setChatLang(cfg.language);
    } catch (_) { /* ignore */ }
  }
  try {
    const info = await fetch(API + "/api/settings/info").then((r) => r.json());
    if (info && info.build) ensureFreshBuild(info.build);
    if (info && info.language) setChatLang(info.language);
  } catch (_) {
    /* ignore */
  }
  syncKeyboardLayout();
})();

lockAppHeight();
syncKeyboardLayout();
