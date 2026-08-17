/* HASSAI Bridge — Agentic chat client */

const API = (typeof window.HASSAI_BASE === "string" ? window.HASSAI_BASE : "").replace(/\/$/, "");

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
  inputEl.style.height = "auto";
  inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + "px";
}

inputEl.addEventListener("input", autosize);

inputEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    formEl.requestSubmit();
  }
});

async function streamChat(userText) {
  history.push({ role: "user", content: userText });
  appendMessage("user", userText);

  const { wrap, bubble } = appendMessage("assistant", "", { streaming: true });
  let full = "";

  const resp = await fetch(API + "/v1/chat/completions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      messages: history.map((m) => ({ role: m.role, content: m.content })),
      stream: true,
      user: "webui",
    }),
  });

  if (!resp.ok) {
    const errText = await resp.text().catch(() => "");
    let detail = `HTTP ${resp.status}`;
    try {
      const j = JSON.parse(errText);
      detail = j?.error?.message || j?.detail || detail;
    } catch (_) {
      if (errText) detail = errText.slice(0, 200);
    }
    wrap.classList.add("msg-error");
    wrap.classList.remove("streaming");
    bubble.textContent = detail;
    history.pop(); // drop failed user turn from memory context
    throw new Error(detail);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

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
        const delta = chunk?.choices?.[0]?.delta?.content;
        if (delta) {
          full += delta;
          bubble.textContent = full;
          mainEl.scrollTop = mainEl.scrollHeight;
        }
      } catch (_) {
        /* ignore keepalive / partial JSON */
      }
    }
  }

  wrap.classList.remove("streaming");
  if (!full) {
    bubble.textContent = "(empty response)";
  }
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
