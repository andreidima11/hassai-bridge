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
let lang = readStoredLang() || "en";

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

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = content || "";

  wrap.appendChild(roleEl);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  mainEl.scrollTop = mainEl.scrollHeight;
  return { wrap, bubble };
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

function startNewChat() {
  sessionId = newSessionId();
  storeSession(sessionId);
  clearThread();
  renderSessions();
  setSidebar(false);
  inputEl.focus();
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
        appendMessage(m.role, m.content || "");
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
  if (sessionId === id) startNewChat();
  await refreshSessions();
}

async function bootIdentity() {
  const data = await apiJson("/api/me");
  currentUser = data.user || currentUser;
  lang = (data.language === "ro" ? "ro" : "en");
  persistLang(lang);
  applyChatI18n();
  if (userLabelEl) {
    const name = currentUser.display_name || currentUser.username || "";
    userLabelEl.textContent = name;
  }
  await refreshSessions();
  const stored = loadStoredSession();
  if (stored && sessions.some((s) => s.session_id === stored)) {
    await openSession(stored);
  } else {
    startNewChat();
  }
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
}

function keyboardOverlap() {
  const vv = window.visualViewport;
  if (!vv) return 0;
  return Math.max(0, window.innerHeight - vv.height - vv.offsetTop);
}

function syncKeyboardLayout() {
  keepPagePinned();
  const composer = document.querySelector(".chat-composer");
  const overlap = keyboardOverlap();
  if (composer) {
    composer.style.transform = overlap ? `translateY(-${overlap}px)` : "";
  }
  // Keep the welcome logo on the layout viewport — do not follow the keyboard.
  if (welcomeEl) welcomeEl.style.transform = "";
  if (welcomeEl && !welcomeEl.hidden && mainEl) mainEl.scrollTop = 0;
}

inputEl.addEventListener("focus", () => {
  syncKeyboardLayout();
  setTimeout(syncKeyboardLayout, 50);
  setTimeout(syncKeyboardLayout, 300);
});
inputEl.addEventListener("blur", () => {
  setTimeout(syncKeyboardLayout, 50);
});
window.addEventListener("scroll", keepPagePinned, { passive: true });
window.visualViewport?.addEventListener("resize", syncKeyboardLayout);
window.visualViewport?.addEventListener("scroll", syncKeyboardLayout);

const sidebarToggleEl = document.getElementById("sidebarToggle");
sidebarToggleEl?.addEventListener("click", toggleSidebar);
backdropEl?.addEventListener("click", () => setSidebar(false));
document.getElementById("newChatBtn")?.addEventListener("click", startNewChat);
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

async function postChat(stream, userText) {
  return fetch(API + "/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: [{ role: "user", content: userText }],
      stream,
      session_id: sessionId,
    }),
  });
}

async function completeNonStream(bubble, userText) {
  const resp = await postChat(false, userText);
  if (!resp.ok) throw new Error(await readError(resp));
  const data = await resp.json();
  const text = extractText(data);
  if (!text) {
    throw new Error(tr("emptyReply"));
  }
  bubble.textContent = text;
  mainEl.scrollTop = mainEl.scrollHeight;
  return text;
}

async function completeStream(bubble, userText) {
  const resp = await postChat(true, userText);
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
        const delta = extractText(chunk);
        if (delta) {
          full += delta;
          bubble.textContent = full;
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
  if (!sessionId) startNewChat();
  history.push({ role: "user", content: userText });
  appendMessage("user", userText);

  const { wrap, bubble } = appendMessage("assistant", "", { streaming: true });
  let full = "";

  try {
    // Companion app / Ingress WebViews often drop SSE → empty reply.
    // Use JSON there; stream on direct :8899.
    if (ON_INGRESS) {
      full = await completeNonStream(bubble, userText);
    } else {
      try {
        full = await completeStream(bubble, userText);
      } catch (e) {
        full = "";
        if (!String(e.message || "").includes("Empty reply")) {
          /* stream transport error — fall through */
        }
      }
      if (!full) {
        full = await completeNonStream(bubble, userText);
      }
    }
  } catch (err) {
    wrap.classList.add("msg-error");
    wrap.classList.remove("streaming");
    bubble.textContent = err.message || "Request failed";
    history.pop();
    throw err;
  }

  wrap.classList.remove("streaming");
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
    if (!window.matchMedia("(pointer: coarse)").matches) inputEl.focus();
  }
});

if (!window.matchMedia("(pointer: coarse)").matches) inputEl.focus();

(async () => {
  applyChatI18n();
  try {
    await bootIdentity();
  } catch (_) {
    startNewChat();
    try {
      const info = await fetch(API + "/api/settings/info").then((r) => r.json());
      if (info && info.language) setChatLang(info.language);
    } catch (_) { /* ignore */ }
    try {
      const cfg = await fetch(API + "/api/settings/").then((r) => r.json());
      if (cfg && cfg.language) setChatLang(cfg.language);
    } catch (_) { /* ignore */ }
  }
  try {
    const info = await fetch(API + "/api/settings/info").then((r) => r.json());
    if (info && info.language) setChatLang(info.language);
    const el = document.getElementById("haStatus");
    if (!el) return;
    const ha = info && info.home_assistant;
    if (!ha) return;
    el.hidden = false;
    if (ha.connected) {
      el.textContent = tr("haOk");
    } else if (ha.available) {
      el.textContent = tr("haToken", { detail: ha.detail || "unknown" });
    } else {
      el.textContent = tr("haOff");
    }
  } catch (_) {
    /* ignore */
  }
})();
