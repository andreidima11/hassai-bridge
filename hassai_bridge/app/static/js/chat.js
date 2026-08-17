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
  const resolved = next === "ro" ? "ro" : "en";
  lang = resolved;
  persistLang(resolved);
  applyChatI18n();
}

function tr(key, params = {}) {
  const table = I18N[lang] || I18N.en;
  let str = table[key] || I18N.en[key] || key;
  for (const [k, v] of Object.entries(params)) str = str.replaceAll(`{${k}}`, v);
  return str;
}

function applyChatI18n() {
  document.documentElement.lang = lang;
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
  if (role === "assistant") {
    traceEl = document.createElement("div");
    traceEl.className = "agent-trace";
    traceEl.hidden = true;
  }

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = content || "";
  if (role === "assistant" && !content) bubble.hidden = true;

  wrap.appendChild(roleEl);
  if (traceEl) wrap.appendChild(traceEl);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  mainEl.scrollTop = mainEl.scrollHeight;
  return { wrap, bubble, traceEl };
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

function applyActivity(traceEl, ev, opts = {}) {
  if (!traceEl || !ev) return;
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
  const name = ev.name || "think";
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
  traceEl.hidden = false;
  if (!opts.quiet) mainEl.scrollTop = mainEl.scrollHeight;
}

function finishTrace(traceEl) {
  if (!traceEl) return;
  const steps = [...traceEl.querySelectorAll(".agent-step")];
  const tools = steps.filter((el) => el.dataset.name !== "think");
  if (!tools.length) {
    traceEl.innerHTML = "";
    traceEl.hidden = true;
    return;
  }
  let total = 0;
  for (const el of steps) {
    const label = el.querySelector(".agent-ms")?.textContent || "";
    if (label.endsWith("ms")) total += parseFloat(label) || 0;
    else if (label.endsWith("s")) total += (parseFloat(label) || 0) * 1000;
  }
  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "agent-toggle";
  toggle.textContent = tr("steps", {
    n: tools.length,
    s: (total / 1000).toFixed(total >= 10000 ? 0 : 1),
  });
  toggle.addEventListener("click", () => {
    traceEl.classList.toggle("is-collapsed");
  });
  traceEl.querySelector(".agent-toggle")?.remove();
  traceEl.prepend(toggle);
  traceEl.classList.add("has-summary", "is-collapsed");
  traceEl.hidden = false;
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
    } catch (_) { /* ignore */ }
    if (!stopped) setTimeout(tick, 320);
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
  lang = (data.language === "ro" ? "ro" : "en");
  persistLang(lang);
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
  try {
    if (window.parent && window.parent !== window) {
      window.parent.scrollTo(0, 0);
      const se = window.parent.document.scrollingElement;
      if (se) se.scrollTop = 0;
    }
  } catch (_) { /* iframe parent blocked */ }
}

function keyboardInset() {
  const vv = window.visualViewport;
  if (vv) {
    // Bottom edge of the visible area in layout coordinates (ChatGPT/Gemini web pattern).
    const visualBottom = vv.offsetTop + vv.height;
    const layoutBottom = window.innerHeight || document.documentElement.clientHeight;
    return Math.max(0, Math.round(layoutBottom - visualBottom));
  }
  const vk = navigator.virtualKeyboard;
  if (vk && vk.boundingRect && vk.boundingRect.height > 0) {
    const rect = vk.boundingRect;
    const layoutBottom = window.innerHeight || document.documentElement.clientHeight;
    return Math.max(0, Math.round(layoutBottom - rect.top));
  }
  return 0;
}

function placeComposer(composer, focused) {
  const vv = window.visualViewport;
  if (!composer || !vv || !focused) {
    composer.style.top = "";
    composer.style.bottom = "0";
    return 0;
  }
  const inset = keyboardInset();
  if (inset <= 0) {
    composer.style.top = "";
    composer.style.bottom = "0";
    return 0;
  }
  const visualBottom = vv.offsetTop + vv.height;
  const top = Math.max(0, Math.round(visualBottom - composer.offsetHeight));
  composer.style.bottom = "auto";
  composer.style.top = `${top}px`;
  return inset;
}

let _parentOverflow = null;
function lockParentScroll() {
  try {
    if (_parentOverflow || !window.parent || window.parent === window) return;
    const html = window.parent.document.documentElement;
    const body = window.parent.document.body;
    _parentOverflow = {
      html: html.style.overflow,
      body: body.style.overflow,
      htmlOh: html.style.overscrollBehavior,
    };
    html.style.overflow = "hidden";
    body.style.overflow = "hidden";
    html.style.overscrollBehavior = "none";
  } catch (_) { /* ignore */ }
}

function unlockParentScroll() {
  try {
    if (!_parentOverflow || !window.parent || window.parent === window) return;
    const html = window.parent.document.documentElement;
    const body = window.parent.document.body;
    html.style.overflow = _parentOverflow.html;
    body.style.overflow = _parentOverflow.body;
    html.style.overscrollBehavior = _parentOverflow.htmlOh;
    _parentOverflow = null;
  } catch (_) {
    _parentOverflow = null;
  }
}

function syncKeyboardLayout() {
  keepPagePinned();
  const composer = document.querySelector(".chat-composer");
  const focused = document.activeElement === inputEl;
  const inset = composer ? placeComposer(composer, focused) : 0;
  document.documentElement.style.setProperty("--kb-inset", `${inset}px`);
  if (composer) {
    document.documentElement.style.setProperty("--composer-space", `${composer.offsetHeight}px`);
  }
  if (welcomeEl) welcomeEl.style.transform = "";
  if (focused) lockParentScroll();
  else unlockParentScroll();
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
  if (window.parent && window.parent !== window && window.parent.navigator.virtualKeyboard) {
    window.parent.navigator.virtualKeyboard.overlaysContent = true;
  }
} catch (_) { /* ignore */ }

inputEl.addEventListener("focus", () => {
  keepPagePinned();
  lockParentScroll();
  syncKeyboardLayout();
  startKeyboardSync();
  requestAnimationFrame(syncKeyboardLayout);
  setTimeout(syncKeyboardLayout, 50);
  setTimeout(syncKeyboardLayout, 280);
  setTimeout(syncKeyboardLayout, 520);
});
inputEl.addEventListener("blur", () => {
  stopKeyboardSync();
  setTimeout(() => {
    syncKeyboardLayout();
    unlockParentScroll();
  }, 50);
});
window.addEventListener("scroll", keepPagePinned, { passive: true });
window.visualViewport?.addEventListener("resize", syncKeyboardLayout);
window.visualViewport?.addEventListener("scroll", () => {
  keepPagePinned();
  syncKeyboardLayout();
});
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

  const { wrap, bubble, traceEl } = appendMessage("assistant", "", { streaming: true });
  const traceId = `${newSessionId()}${newSessionId()}`;
  const ui = { wrap, bubble, traceEl, traceId };
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
