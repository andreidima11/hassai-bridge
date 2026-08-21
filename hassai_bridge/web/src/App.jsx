import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Composer } from "./components/Composer.jsx";
import { WelcomeHero } from "./components/WelcomeHero.jsx";
import { ChatWindowIcon, GearIcon } from "./components/Icons.jsx";
import { Messages } from "./components/Messages.jsx";
import { Sidebar } from "./components/Sidebar.jsx";
import {
  apiJson,
  apiUrl,
  cancelChat,
  clearPendingTrace,
  ensureFreshBuild,
  newId,
  persistPendingTrace,
  postChat,
  readError,
  readPendingTrace,
  waitForChatJob,
} from "./lib/api.js";
import { syncHaTheme } from "./lib/theme.js";
import { finishThinkingLabel, persistLang, readStoredLang, tr } from "./lib/i18n.js";
import {
  canSendMessage,
  clearDraftAttachments,
  persistDraftAttachments,
  persistDraftText,
  readDraftAttachments,
  readDraftText,
  MAX_CHAT_IMAGES,
} from "./lib/images.js";
import { pickGreeting } from "./lib/greetings.js";
import { applyActivity, emptyThinking } from "./lib/thinking.js";
import {
  defaultThinkingMode,
  hasThinkingCapability,
  persistThinkingMode,
  readStoredThinkingMode,
} from "./lib/providerCapabilities.js";

function sessionStoreKey(username) {
  return `hassai.chat.session.${username || "default"}`;
}

function sessionTitle(row, lang) {
  const raw = String(row.title || "").replace(/\s+/g, " ").trim();
  return raw ? raw.slice(0, 56) : tr(lang, "untitled");
}

function mapStoredAttachments(items) {
  return (items || []).map((item) => ({
    id: item.id,
    mime: item.mime,
    name: item.name || "",
    kind: item.kind || (String(item.mime || "").startsWith("image/") ? "image" : "document"),
    previewUrl: apiUrl(item.url),
    url: apiUrl(item.url),
  }));
}

export default function App() {
  const [lang, setLang] = useState(readStoredLang);
  const [atmosphere, setAtmosphere] = useState({});
  const [dynamicGreetings, setDynamicGreetings] = useState(true);
  const [greetingNonce, setGreetingNonce] = useState(() => Date.now() % 100000);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [input, setInput] = useState(() => readDraftText());
  const [attachments, setAttachments] = useState(() => readDraftAttachments());
  const [busy, setBusy] = useState(false);
  const [messages, setMessages] = useState([]);
  const [sessions, setSessions] = useState([]);
  const [sessionId, setSessionId] = useState("");
  const [user, setUser] = useState({ username: "default", display_name: "default" });
  const [chatCapabilities, setChatCapabilities] = useState({});
  const [providerInfo, setProviderInfo] = useState({ id: "", name: "", model: "" });
  const [thinkingMode, setThinkingMode] = useState(() => readStoredThinkingMode());
  const sessionIdRef = useRef("");
  const bootDone = useRef(false);
  const hiddenAt = useRef(0);
  const abortRef = useRef(null);
  const stopPollRef = useRef(null);
  const traceIdRef = useRef("");
  const messagesRef = useRef([]);
  const attachmentsRef = useRef([]);
  const pickerGuardUntil = useRef(0);

  useEffect(() => {
    syncHaTheme();
  }, []);

  useEffect(() => {
    sessionIdRef.current = sessionId;
  }, [sessionId]);

  useEffect(() => {
    messagesRef.current = messages;
  }, [messages]);

  useEffect(() => {
    attachmentsRef.current = attachments;
    persistDraftAttachments(attachments);
  }, [attachments]);

  // The Companion WebView can restart while a file picker is open — keep the typed message.
  useEffect(() => {
    persistDraftText(input);
  }, [input]);

  const t = useCallback((key, params) => tr(lang, key, params), [lang]);
  const settingsHref = `${window.HASSAI_BASE || ""}/settings`;
  const greeting = useMemo(() => {
    if (!dynamicGreetings) {
      return { title: t("welcome"), hint: t("welcomeHint") };
    }
    return pickGreeting(lang, atmosphere, new Date(), greetingNonce);
  }, [dynamicGreetings, lang, atmosphere, greetingNonce, t]);

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
      setAttachments([]);
      clearDraftAttachments();
      setSidebarOpen(false);
      if (persist && dynamicGreetings) setGreetingNonce((n) => n + 1);
    },
    [user.username, dynamicGreetings],
  );

  const openSession = useCallback(
    async (id, usernameOverride) => {
      const uname = usernameOverride || user.username;
      setSessionId(id);
      sessionIdRef.current = id;
      try {
        localStorage.setItem(sessionStoreKey(uname), id);
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
            createdAt: m.created_at || null,
            thinking: label ? next : emptyThinking(t("thinking")),
            ...(Array.isArray(m.attachments) && m.attachments.length
              ? { attachments: mapStoredAttachments(m.attachments) }
              : {}),
          });
        } else {
          const content = m.content === "(image)" ? "" : m.content || "";
          const row = { id: newId(), role: m.role, content, createdAt: m.created_at || null };
          if (Array.isArray(m.attachments) && m.attachments.length) {
            row.attachments = mapStoredAttachments(m.attachments);
          }
          msgs.push(row);
        }
      }
      setMessages(msgs);
      setAttachments([]);
      setSidebarOpen(false);
      return msgs;
    },
    [user.username, lang, t],
  );

  const finishAssistantMessage = useCallback(
    (assistantId, full, { error = false } = {}) => {
      setMessages((prev) =>
        prev.map((m) => {
          if (m.id !== assistantId) return m;
          const thinking = m.thinking || emptyThinking(t("thinking"));
          const label = finishThinkingLabel(lang, thinking);
          const content = error
            ? full || "Request failed"
            : full?.trim()
              ? full
              : m.content || "";
          return {
            ...m,
            content,
            error: Boolean(error),
            streaming: false,
            thinking: label
              ? { ...thinking, active: false, collapsed: true, visible: true, label }
              : { ...emptyThinking(t("thinking")), visible: false },
          };
        }),
      );
    },
    [lang, t],
  );

  const watchBackgroundJob = useCallback(
    async ({ traceId, sessionId: sid, assistantId, signal, username }) => {
      const seenActivity = new Set();
      const patchAssistant = (fn) => {
        setMessages((prev) => prev.map((m) => (m.id === assistantId ? fn(m) : m)));
      };
      const onActivity = (ev) => {
        if (typeof ev?.i === "number") {
          if (seenActivity.has(ev.i)) return;
          seenActivity.add(ev.i);
        }
        if (ev?.name === "assistant" && typeof ev.detail === "string" && ev.detail) {
          patchAssistant((m) => ({ ...m, content: ev.detail }));
          return;
        }
        patchAssistant((m) => ({
          ...m,
          thinking: applyActivity(m.thinking || emptyThinking(t("thinking")), ev, t("thinking")),
        }));
      };
      try {
        const full = await waitForChatJob(traceId, {
          onActivity,
          onDelta: (delta) => patchAssistant((m) => ({ ...m, content: delta })),
          signal,
        });
        if (signal?.aborted) return;
        finishAssistantMessage(assistantId, full);
        clearPendingTrace(username);
        if (sid) {
          try {
            await openSession(sid, username);
          } catch {
            /* keep live message */
          }
        }
        refreshSessions().catch(() => {});
      } catch (err) {
        if (err?.name === "AbortError" || signal?.aborted) {
          clearPendingTrace(username);
          return;
        }
        finishAssistantMessage(assistantId, err.message || "Request failed", { error: true });
        clearPendingTrace(username);
      } finally {
        if (abortRef.current && abortRef.current.signal === signal) abortRef.current = null;
        setBusy(false);
        if (traceIdRef.current === traceId) traceIdRef.current = "";
      }
    },
    [finishAssistantMessage, openSession, refreshSessions, t],
  );

  const openSessionRef = useRef(openSession);
  const watchJobRef = useRef(watchBackgroundJob);
  useEffect(() => {
    openSessionRef.current = openSession;
  }, [openSession]);
  useEffect(() => {
    watchJobRef.current = watchBackgroundJob;
  }, [watchBackgroundJob]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      let username = "default";
      try {
        const data = await apiJson("/api/me");
        if (cancelled) return;
        ensureFreshBuild(data.build);
        const nextLang = data.language === "ro" ? "ro" : "en";
        setLang(nextLang);
        persistLang(nextLang);
        const nextUser = data.user || { username: "default", display_name: "default" };
        username = nextUser.username || "default";
        setUser(nextUser);
        setDynamicGreetings(data.dynamic_greetings !== false);
        setAtmosphere(data.atmosphere && typeof data.atmosphere === "object" ? data.atmosphere : {});
        const chat = data.chat || {};
        const caps = chat.capabilities || {};
        setChatCapabilities(caps);
        setProviderInfo({
          id: chat.provider_id || "",
          name: chat.provider_name || "",
          model: chat.model || "",
        });
        if (hasThinkingCapability(caps)) {
          setThinkingMode((prev) => readStoredThinkingMode(defaultThinkingMode(caps) || prev));
        }
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
      if (cancelled) return;

      let sid = "";
      try {
        sid = localStorage.getItem(sessionStoreKey(username)) || "";
      } catch {
        sid = "";
      }
      const pending = readPendingTrace(username);

      if (sid) {
        try {
          await openSessionRef.current(sid, username);
        } catch {
          const id = newId();
          setSessionId(id);
          sessionIdRef.current = id;
          setMessages([]);
          sid = id;
        }
      } else {
        const id = newId();
        setSessionId(id);
        sessionIdRef.current = id;
        setMessages([]);
        sid = id;
      }

      if (pending?.traceId) {
        let job = null;
        try {
          job = await apiJson(`/v1/chat/jobs/${encodeURIComponent(pending.traceId)}`);
        } catch {
          job = null;
        }
        if (job && !job.done && !job.cancelled && job.status === "running") {
          const resumeSid = pending.sessionId || job.session_id || sid;
          if (resumeSid && resumeSid !== sessionIdRef.current) {
            try {
              await openSessionRef.current(resumeSid, username);
            } catch {
              /* keep current */
            }
          }
          let assistantId = newId();
          const existing = messagesRef.current[messagesRef.current.length - 1];
          if (existing?.role === "assistant") {
            assistantId = existing.id;
            setMessages((prev) =>
              prev.map((m) =>
                m.id === assistantId
                  ? {
                      ...m,
                      streaming: true,
                      thinking: {
                        ...(m.thinking || emptyThinking(tr(readStoredLang(), "thinking"))),
                        visible: true,
                        active: true,
                      },
                    }
                  : m,
              ),
            );
          } else {
            setMessages((prev) => [
              ...prev,
              {
                id: assistantId,
                role: "assistant",
                content: "",
                streaming: true,
                thinking: {
                  ...emptyThinking(tr(readStoredLang(), "thinking")),
                  visible: true,
                  active: true,
                },
              },
            ]);
          }
          traceIdRef.current = pending.traceId;
          setBusy(true);
          const controller = new AbortController();
          abortRef.current = controller;
          watchJobRef.current({
            traceId: pending.traceId,
            sessionId: resumeSid,
            assistantId,
            signal: controller.signal,
            username,
          });
        } else {
          clearPendingTrace(username);
          if (sid) {
            try {
              await openSessionRef.current(sid, username);
            } catch {
              /* ignore */
            }
          }
        }
      }

      bootDone.current = true;
    })();
    return () => {
      cancelled = true;
    };
  }, [refreshSessions]);

  useEffect(() => {
    const shouldSkipReset = () => Date.now() < pickerGuardUntil.current;
    const syncAfterReturn = async () => {
      if (busy || !bootDone.current) return;
      const pending = readPendingTrace(user.username);
      const sid = sessionIdRef.current;
      if (pending?.traceId) {
        try {
          const job = await apiJson(`/v1/chat/jobs/${encodeURIComponent(pending.traceId)}`);
          if (job?.done || job?.cancelled || job?.status === "error") {
            clearPendingTrace(user.username);
            if (sid) await openSession(sid, user.username);
            refreshSessions().catch(() => {});
          }
        } catch {
          /* job expired — reload session anyway */
          clearPendingTrace(user.username);
          if (sid) {
            try {
              await openSession(sid, user.username);
            } catch {
              /* ignore */
            }
          }
        }
        return;
      }
      if (sid && messagesRef.current.some((m) => m.streaming)) {
        try {
          await openSession(sid, user.username);
        } catch {
          /* ignore */
        }
      }
    };
    const onVis = () => {
      if (document.visibilityState === "hidden") {
        hiddenAt.current = Date.now();
        return;
      }
      if (shouldSkipReset()) {
        hiddenAt.current = 0;
        return;
      }
      syncAfterReturn().catch(() => {});
      if (!bootDone.current || busy) {
        hiddenAt.current = 0;
        return;
      }
      const hiddenMs = hiddenAt.current > 0 ? Date.now() - hiddenAt.current : 0;
      hiddenAt.current = 0;
      if (hiddenMs > 0 && hiddenMs < 3000) return;
      if (messagesRef.current.length > 0 || attachmentsRef.current.length > 0 || readDraftAttachments().length > 0 || input.trim()) return;
      startNewChat({ ephemeral: true });
    };
    const onFocus = () => {
      if (shouldSkipReset()) hiddenAt.current = 0;
    };
    const onPageShow = () => {
      const drafts = readDraftAttachments();
      if (drafts.length) setAttachments(drafts);
      syncAfterReturn().catch(() => {});
    };
    document.addEventListener("visibilitychange", onVis);
    window.addEventListener("focus", onFocus);
    window.addEventListener("pageshow", onPageShow);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("focus", onFocus);
      window.removeEventListener("pageshow", onPageShow);
    };
  }, [busy, input, openSession, refreshSessions, startNewChat, user.username]);

  const reuseMessage = useCallback((message) => {
    const text = String(message?.content || "").trim();
    if (text) setInput(text);
    const images = (Array.isArray(message?.attachments) ? message.attachments : [])
      .filter((img) => img?.previewUrl || img?.dataUrl || img?.url || img?.text)
      .slice(0, MAX_CHAT_IMAGES)
      .map((img) => ({
        id: img.id || newId(),
        mime: img.mime || "",
        name: img.name || "",
        kind: img.kind || (img.text ? "document" : "image"),
        previewUrl: img.previewUrl || img.url || img.dataUrl,
        dataUrl: img.dataUrl || "",
        url: img.url || "",
        text: img.text || "",
        chars: img.chars,
      }));
    if (images.length) setAttachments(images);
    window.requestAnimationFrame(() => {
      const el = document.querySelector("textarea");
      if (el && typeof el.focus === "function") {
        el.focus();
        const len = el.value.length;
        try {
          el.setSelectionRange(len, len);
        } catch {
          /* ignore */
        }
      }
    });
  }, []);

  const stopGeneration = useCallback(() => {
    const traceId = traceIdRef.current;
    if (traceId) cancelChat(traceId).catch(() => {});
    clearPendingTrace(user.username);
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
  }, [lang, t, user.username]);

  const send = async (event) => {
    event.preventDefault();
    const text = input.trim();
    const images = attachments;
    if (!canSendMessage(text, images) || busy) return;
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

    const now = Date.now() / 1000;
    const payload = { text, images };
    const userMsg = {
      id: newId(),
      role: "user",
      content: text,
      createdAt: now,
      attachments: images.map((img) => ({
        id: img.id,
        name: img.name || "",
        mime: img.mime || "",
        kind: img.kind || "image",
        previewUrl: img.previewUrl,
        dataUrl: img.dataUrl,
        text: img.text || "",
        chars: img.chars,
        url: img.url || "",
      })),
    };
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
        createdAt: now,
        model: providerInfo.model || providerInfo.name || "",
        streaming: true,
        thinking: { ...emptyThinking(t("thinking")), visible: true, active: true },
      },
    ]);
    setInput("");
    setAttachments([]);
    clearDraftAttachments();
    setBusy(true);
    persistPendingTrace(user.username, traceId, sid);

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    const { signal } = controller;

    const thinkingOverride = hasThinkingCapability(chatCapabilities) ? thinkingMode : undefined;

    try {
      const resp = await postChat(false, payload, sid, traceId, signal, thinkingOverride, {
        background: true,
      });
      if (!resp.ok) throw new Error(await readError(resp));
      await resp.json().catch(() => ({}));
    } catch (err) {
      if (err?.name === "AbortError" || signal.aborted) {
        clearPendingTrace(user.username);
        setBusy(false);
        return;
      }
      finishAssistantMessage(assistantId, err.message || "Request failed", { error: true });
      clearPendingTrace(user.username);
      setBusy(false);
      return;
    }

    // Job runs on the server; polling survives panel close / return.
    await watchBackgroundJob({
      traceId,
      sessionId: sid,
      assistantId,
      signal,
      username: user.username,
    });
  };

  const refreshChatProvider = useCallback(async () => {
    const data = await apiJson("/api/me");
    const chat = data.chat || {};
    const caps = chat.capabilities || {};
    setChatCapabilities(caps);
    setProviderInfo({
      id: chat.provider_id || "",
      name: chat.provider_name || "",
      model: chat.model || "",
    });
    if (hasThinkingCapability(caps)) {
      setThinkingMode((prev) => readStoredThinkingMode(defaultThinkingMode(caps) || prev));
    } else {
      setThinkingMode("off");
    }
  }, []);

  const updateProviderModel = useCallback(async (model) => {
    const providerId = providerInfo.id;
    if (!providerId || !model) return;
    await apiJson(`/api/settings/providers/${encodeURIComponent(providerId)}`, {
      method: "PUT",
      body: JSON.stringify({ model }),
    });
    setProviderInfo((prev) => ({ ...prev, model }));
  }, [providerInfo.id]);

  const changeProvider = useCallback(
    async (newId) => {
      if (!newId || newId === providerInfo.id) return;
      await apiJson(`/api/settings/providers/${encodeURIComponent(newId)}/activate`, { method: "PUT" });
      await refreshChatProvider();
    },
    [providerInfo.id, refreshChatProvider],
  );

  const deleteSession = async (id) => {
    if (!confirm(t("deleteConfirm"))) return;
    const inDb = sessions.some((s) => s.session_id === id);
    if (inDb) await apiJson(`/api/conversations/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (sessionId === id) startNewChat({ ephemeral: false });
    await refreshSessions();
  };

  const deleteAllSessions = async () => {
    if (!sessions.length) return;
    if (!confirm(t("deleteAllConfirm"))) return;
    await apiJson("/api/conversations", { method: "DELETE" });
    startNewChat({ ephemeral: false });
    await refreshSessions();
    setSidebarOpen(false);
  };

  return (
    <div className="flex h-full w-full overflow-hidden">
      <Sidebar
        deleteAllLabel={t("deleteAllChats")}
        emptyLabel={t("noChats")}
        newLabel={t("newChat")}
        open={sidebarOpen}
        sessionId={sessionId}
        sessions={listedSessions}
        title={t("chats")}
        userLabel={user.display_name || user.username || ""}
        onClose={() => setSidebarOpen(false)}
        onDelete={deleteSession}
        onDeleteAll={deleteAllSessions}
        onNew={() => startNewChat()}
        onOpen={openSession}
      />

      <div className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-background">
        <header className="flex shrink-0 items-center justify-between p-2 pt-[max(0.5rem,env(safe-area-inset-top))]">
          <button
            className="grid size-9 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={t("chats")}
            title={t("chats")}
          >
            <ChatWindowIcon />
          </button>
          <a
            className="grid size-9 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            href={settingsHref}
            aria-label={t("settings")}
            title={t("settings")}
          >
            <GearIcon />
          </a>
        </header>

        <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
          <Messages
            greeting={<WelcomeHero hint={greeting.hint} title={greeting.title} />}
            lang={lang}
            messages={messages}
            modelLabel={providerInfo.model || providerInfo.name || ""}
            userLabel={user.display_name || user.username || ""}
            onReuseMessage={reuseMessage}
          />
          <Composer
            attachDocLabel={t("attachDocument")}
            attachLabel={t("attachImage")}
            attachments={attachments}
            busy={busy}
            docTooLargeLabel={t("docTooLarge")}
            imageTooLargeLabel={t("imageTooLarge")}
            lang={lang}
            maxImagesLabel={t("maxImages")}
            placeholder={t("placeholder")}
            removeDocLabel={t("removeDocument")}
            removeImageLabel={t("removeImage")}
            providerCapabilities={chatCapabilities}
            providerId={providerInfo.id}
            providerModel={providerInfo.model}
            providerName={providerInfo.name}
            stopLabel={t("stop")}
            thinkingMode={thinkingMode}
            unsupportedDocLabel={t("unsupportedDocument")}
            unsupportedImageLabel={t("unsupportedImage")}
            value={input}
            onAttachmentsChange={setAttachments}
            onChange={setInput}
            onPickerOpen={() => {
              pickerGuardUntil.current = Date.now() + 120_000;
            }}
            onPickerSettled={() => {
              window.setTimeout(() => {
                pickerGuardUntil.current = 0;
              }, 10000);
            }}
            onProviderChange={changeProvider}
            onProviderModelChange={updateProviderModel}
            onStop={stopGeneration}
            onSubmit={send}
            onThinkingModeChange={(mode) => {
              setThinkingMode(mode);
              persistThinkingMode(mode);
            }}
          />
        </div>
      </div>
    </div>
  );
}
