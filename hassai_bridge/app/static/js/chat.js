/* HASSAI Bridge — Agentic chat client */

const API = (typeof window.HASSAI_BASE === "string" ? window.HASSAI_BASE : "").replace(/\/$/, "");
const ON_INGRESS = /\/api\/hassio_ingress\//.test(API || location.pathname);

const messagesEl = document.getElementById("chatMessages");
const welcomeEl = document.getElementById("chatWelcome");
const formEl = document.getElementById("chatForm");
const inputEl = document.getElementById("chatInput");
const sendEl = document.getElementById("chatSend");
const mainEl = document.getElementById("chatMain");

/** @type {{role: string, content: string}[]} */
const history = [];
let busy = false;

function showThread() {
  welcomeEl.hidden = true;
  messagesEl.hidden = false;
}

function appendMessage(role, content, { error = false, streaming = false } = {}) {
  showThread();
  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}${error ? " msg-error" : ""}${streaming ? " streaming" : ""}`;

  const roleEl = document.createElement("div");
  roleEl.className = "msg-role";
  roleEl.textContent = role === "user" ? "You" : "HASSAI";

  const bubble = document.createElement("div");
  bubble.className = "msg-bubble";
  bubble.textContent = content || "";

  wrap.appendChild(roleEl);
  wrap.appendChild(bubble);
  messagesEl.appendChild(wrap);
  mainEl.scrollTop = mainEl.scrollHeight;
  return { wrap, bubble };
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

async function postChat(stream) {
  return fetch(API + "/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: history.map((m) => ({ role: m.role, content: m.content })),
      stream,
      user: "webui",
    }),
  });
}

async function completeNonStream(bubble) {
  const resp = await postChat(false);
  if (!resp.ok) throw new Error(await readError(resp));
  const data = await resp.json();
  const text = extractText(data);
  if (!text) {
    throw new Error("Empty reply from provider. Check Settings → provider URL, API key, and model.");
  }
  bubble.textContent = text;
  mainEl.scrollTop = mainEl.scrollHeight;
  return text;
}

async function completeStream(bubble) {
  const resp = await postChat(true);
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
  history.push({ role: "user", content: userText });
  appendMessage("user", userText);

  const { wrap, bubble } = appendMessage("assistant", "", { streaming: true });
  let full = "";

  try {
    // Companion app / Ingress WebViews often drop SSE → empty reply.
    // Use JSON there; stream on direct :8899.
    if (ON_INGRESS) {
      full = await completeNonStream(bubble);
    } else {
      try {
        full = await completeStream(bubble);
      } catch (e) {
        full = "";
        if (!String(e.message || "").includes("Empty reply")) {
          /* stream transport error — fall through */
        }
      }
      if (!full) {
        full = await completeNonStream(bubble);
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
    inputEl.focus();
  }
});

inputEl.focus();

(async () => {
  try {
    const info = await fetch(API + "/api/settings/info").then((r) => r.json());
    const el = document.getElementById("haStatus");
    if (!el) return;
    const ha = info && info.home_assistant;
    if (!ha) return;
    el.hidden = false;
    if (ha.connected) {
      el.textContent = "Connected to Home Assistant — you can ask about devices and control them here.";
    } else if (ha.available) {
      el.textContent = "Home Assistant token is present; Core ping failed (" + (ha.detail || "unknown") + "). Chat still works; retry in a moment.";
    } else {
      el.textContent = "Not running as a Home Assistant add-on — HA admin tools are off.";
    }
  } catch (_) {
    /* ignore */
  }
})();
