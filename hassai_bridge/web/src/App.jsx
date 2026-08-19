import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { WelcomeHero } from "./components/WelcomeHero.jsx";
import { ChatWindowIcon, GearIcon } from "./components/Icons.jsx";
import { Messages } from "./components/Messages.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import {
  apiJson,
  apiUrl,
  cancelChat,
  ensureFreshBuild,
  extractText,
  newId,
  ON_INGRESS,
  postChat,
  readError,
  startActivityPoll,
} from "./lib/api.js";
import { syncHaTheme } from "./lib/theme.js";
import { finishThinkingLabel, persistLang, readStoredLang, tr } from "./lib/i18n.js";
import { applyActivity, emptyThinking } from "./lib/thinking.js";

function sessionStoreKey(username) {
  return `hassai.chat.session.${username || "default"}`;
}

function sessionTitle(row, lang) {
  const raw = String(row.title || "").replace(/\s+/g, " ").trim();
  return raw ? raw.slice(0, 56) : tr(lang, "untitled");
}

async function completeNonStream(userText, sessionId, traceId, onActivity, signal) {
  const resp = await postChat(false, userText, sessionId, traceId, signal);
  if (!resp.ok) throw new Error(await readError(resp));
  const data = await resp.json();
  if (data.hassai_cancelled) throw new DOMException("Aborted", "AbortError");
  if (Array.isArray(data.hassai_activity)) data.hassai_activity.forEach(onActivity);
  const text = extractText(data);
  if (!text) throw new Error("empty");
  return text;
}

async function completeStream(userText, sessionId, traceId, onActivity, onDelta, signal) {
  const resp = await postChat(true, userText, sessionId, traceId, signal);
  if (!resp.ok) throw new Error(await readError(resp));
  if (!resp.body) throw new Error("No stream body");
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let full = "";
  while (true) {
    if (signal?.aborted) {
      await reader.cancel().catch(() => {});
      throw new DOMException("Aborted", "AbortError");
    }
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
          onActivity(chunk);
          continue;
        }
        const delta = extractText(chunk);
        if (delta) {
          full += delta;
          onDelta(full);
        }
      } catch {
        /* keepalive */
      }
    }
  }
  return full;
}

export default function App() {
  const [lang, setLang] = useState(readStoredLang);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [user, setUser] = useState({ username: "default", display_name: "default" });
  const sessionIdRef = useRef("");
  const bootDone = useRef(false);
  const hiddenAt = useRef(0);
  const abortRef = useRef(null);
  const stopPollRef = useRef(null);
  const traceIdRef = useRef("");

  useEffect(() => {
    syncHaTheme();
  }, []);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  const t = useCallback((key, params) => tr(lang, key, params), [lang]);
  const settingsHref = `${window.HASSAI_BASE || ""}/settings`;

  const listedSessions = useMemo(() => {
    const inDb = sessions.some((s) => s.session_id === sessionId);
    const rows = [];
    if (sessionId && !inDb) rows.push({ session_id: sessionId, title: t("untitled") });
    rows.push(...sessions.map((s) => ({ ...s, title: sessionTitle(s, lang) })));
    return rows;
  }, [sessions, sessionId, lang, t]);

  const refreshSessions = useCallback(async () => {
    const data = await apiJson("/api/conversations?limit=80");
    setSessions(data.sessions || []);
  }, []);

  const startNewChat = useCallback(
    (options = {}) => {
      const persist = options.ephemeral !== true;
      const id = newId();
      setSessionId(id);
      sessionIdRef.current = id;
      if (persist) {
        try {
          localStorage.setItem(sessionStoreKey(user.username), id);
        } catch {
          /* ignore */
        }
      } else {
        try {
          localStorage.removeItem(sessionStoreKey(user.username));
        } catch {
          /* ignore */
        }
      }
      setMessages([]);
      setSidebarOpen(false);
    },
    [user.username],
  );

  const openSession = useCallback(
    async (id) => {
      setSessionId(id);
      sessionIdRef.current = id;
      try {
        localStorage.setItem(sessionStoreKey(user.username), id);
      } catch {
        /* ignore */
      }
      const data = await apiJson(`/api/conversations/${encodeURIComponent(id)}`);
      const msgs = [];
      for (const m of data.messages || []) {
        if (m.role !== "user" && m.role !== "assistant") continue;
        const thinking = emptyThinking(t("thinking"));
        if (m.role === "assistant" && Array.isArray(m.activity)) {
          let next = thinking;
          for (const ev of m.activity) next = applyActivity(next, ev, t("thinking"));
          const label = finishThinkingLabel(lang, next);
          next = { ...next, active: false, collapsed: true, visible: !!label, label: label || next.label };
          msgs.push({
            id: newId(),
            role: m.role,
            content: m.content || "",
            thinking: label ? next : emptyThinking(t("thinking")),
          });
        } else {
          msgs.push({ id: newId(), role: m.role, content: m.content || "" });
        }
      }
      setMessages(msgs);
      setSidebarOpen(false);
    },
    [user.username, lang, t],
  );

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const data = await apiJson("/api/me");
        if (cancelled) return;
        ensureFreshBuild(data.build);
        const nextLang = data.language === "ro" ? "ro" : "en";
        setLang(nextLang);
        persistLang(nextLang);
        setUser(data.user || { username: "default", display_name: "default" });
        await refreshSessions();
      } catch {
        try {
          const info = await fetch(apiUrl("/api/settings/info")).then((r) => r.json());
          if (info?.build) ensureFreshBuild(info.build);
          if (info?.language) {
            const nextLang = info.language === "ro" ? "ro" : "en";
            setLang(nextLang);
            persistLang(nextLang);
          }
        } catch {
          /* ignore */
        }
      }
      if (!cancelled) {
        const id = newId();
        setSessionId(id);
        sessionIdRef.current = id;
        setMessages([]);
        bootDone.current = true;
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshSessions]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState === "hidden") {
        hiddenAt.current = Date.now();
        return;
      }
      if (bootDone.current && !busy && hiddenAt.current > 0) startNewChat({ ephemeral: true });
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [busy, startNewChat]);

  const stopGeneration = useCallback(() => {
    const traceId = traceIdRef.current;
    if (traceId) cancelChat(traceId).catch(() => {});
    abortRef.current?.abort();
    stopPollRef.current?.();
    stopPollRef.current = null;
    setBusy(false);
    setMessages((prev) =>
      prev.map((m) => {
        if (!m.streaming) return m;
        const thinking = m.thinking || emptyThinking(t("thinking"));
        const label = finishThinkingLabel(lang, thinking);
        const content = m.content?.trim() ? m.content : t("stopped");
        return {
          ...m,
          content,
          streaming: false,
          thinking: label
            ? { ...thinking, active: false, collapsed: true, visible: true, label }
            : { ...thinking, active: false, collapsed: true, visible: true },
        };
      }),
    );
  }, [lang, t]);

  const send = async (event) => {
    event.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    let sid = sessionIdRef.current;
    if (!sid) {
      startNewChat({ ephemeral: false });
      sid = sessionIdRef.current;
    } else {
      try {
        localStorage.setItem(sessionStoreKey(user.username), sid);
      } catch {
        /* ignore */
      }
    }

    const userMsg = { id: newId(), role: "user", content: text };
    const assistantId = newId();
    const traceId = `${newId()}${newId()}`;
    traceIdRef.current = traceId;
    setMessages((prev) => [
      ...prev,
      userMsg,
      {
        id: assistantId,
        role: "assistant",
        content: "",
        streaming: true,
        thinking: { ...emptyThinking(t("thinking")), visible: true, active: true },
      },
    ]);
    setInput("");
    setBusy(true);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    const seenActivity = new Set();
    const patchAssistant = (fn) => {
      setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));
    };
    const onActivity = (ev) => {
      if (typeof ev?.i === "number") {
        if (seenActivity.has(ev.i)) return;
        seenActivity.add(ev.i);
      }
      patchAssistant((m) => ({
        ...m,
        thinking: applyActivity(m.thinking || emptyThinking(t("thinking")), ev, t("thinking")),
      }));
    };
    const stopPoll = startActivityPoll(traceId, onActivity);
    stopPollRef.current = stopPoll;

    try {
      let full = "";
      if (ON_INGRESS) {
        full = await completeNonStream(text, sid, traceId, onActivity, signal);
      } else {
        try {
          full = await completeStream(text, sid, traceId, onActivity, (delta) => {
            patchAssistant((m) => ({ ...m, content: delta }));
          }, signal);
        } catch (err) {
          if (err?.name === "AbortError") throw err;
          full = "";
        }
        if (!full && !signal.aborted) full = await completeNonStream(text, sid, traceId, onActivity, signal);
      }
      if (signal.aborted) return;
      patchAssistant((m) => {
        const thinking = m.thinking || emptyThinking(t("thinking"));
        const label = finishThinkingLabel(lang, thinking);
        return {
          ...m,
          content: full,
          streaming: false,
          thinking: label
            ? { ...thinking, active: false, collapsed: true, visible: true, label }
            : { ...emptyThinking(t("thinking")), visible: false },
        };
      });
      refreshSessions().catch(() => {});
    } catch (err) {
      if (err?.name === "AbortError" || signal.aborted) return;
      const msg = String(err.message || "") === "empty" ? t("emptyReply") : err.message || "Request failed";
      patchAssistant((m) => ({ ...m, content: msg, error: true, streaming: false }));
    } finally {
      stopPoll();
      stopPollRef.current = null;
      if (abortRef.current === controller) abortRef.current = null;
      setBusy(false);
    }
  };

  const deleteSession = async (id) => {
    if (!confirm(t("deleteConfirm"))) return;
    const inDb = sessions.some((s) => s.session_id === id);
    if (inDb) await apiJson(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (sessionId === id) startNewChat({ ephemeral: false });
    await refreshSessions();
  };

  return (
    <div className="flex h-full w-full overflow-hidden">
      <Sidebar
        emptyLabel={t("noChats")}
        newLabel={t("newChat")}
        open={sidebarOpen}
        sessionId={sessionId}
        sessions={listedSessions}
        title={t("chats")}
        userLabel={user.display_name || user.username || ""}
        onClose={() => setSidebarOpen(false)}
        onDelete={deleteSession}
        onNew={() => startNewChat()}
        onOpen={openSession}
      />

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
        <div className="pointer-events-none absolute inset-x-0 top-0 z-10 flex items-start justify-between p-2">
          <button
            className="pointer-events-auto grid size-9 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={t("chats")}
            title={t("chats")}
          >
            <ChatWindowIcon />
          </button>
          <a
            className="pointer-events-auto grid size-9 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            href={settingsHref}
            aria-label={t("settings")}
            title={t("settings")}
          >
            <GearIcon />
          </a>
        </div>

        <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
          <Messages
            greeting={<WelcomeHero hint={t("welcomeHint")} title={t("welcome")} />}
            lang={lang}
            messages={messages}
          />
          <Composer
            busy={busy}
            placeholder={t("placeholder")}
            stopLabel={t("stop")}
            value={input}
            onChange={setInput}
            onStop={stopGeneration}
            onSubmit={send}
          />
        </div>
      </div>
    </div>
  );
}
