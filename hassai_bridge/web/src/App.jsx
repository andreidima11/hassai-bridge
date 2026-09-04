import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Composer } from "./components/Composer.jsx";
import { AUTO_PROVIDER } from "./components/ProviderQuickSettings.jsx";
import { VoiceMode } from "./components/VoiceMode.jsx";
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
import * as voiceApi from "./lib/voice.js";
import { applyActivity, emptyThinking, mergeMessageSources } from "./lib/thinking.js";
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
  return (items || []).map((item) => {
    const mime = String(item.mime || "");
    let kind = item.kind;
    if (!kind) {
      if (mime.startsWith("image/")) kind = "image";
      else if (mime.startsWith("video/")) kind = "video";
      else if (mime.startsWith("audio/")) kind = "audio";
      else kind = "document";
    }
    return {
      id: item.id,
      mime: item.mime,
      name: item.name || "",
      kind,
      previewUrl: apiUrl(item.url),
      url: apiUrl(item.url),
    };
  });
}

export default function App() {
  const [lang, setLang] = useState(readStoredLang);
  const [atmosphere, setAtmosphere] = useState({});
  const [dynamicGreetings, setDynamicGreetings] = useState(true);
  const [greetingPool, setGreetingPool] = useState([]);
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
  const [voiceConfig, setVoiceConfig] = useState({
    enabled: false,
    tts: false,
    autoplay: true,
    controls: "both",
  });
  const [voiceMode, setVoiceMode] = useState(null);
  const spokenTurnRef = useRef(false);
  const handsFreeRef = useRef(false);
  const [providerInfo, setProviderInfo] = useState({
    id: "", name: "", model: "", auto: false, activePacks: [], toolProfile: "auto",
  });
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
    return pickGreeting(lang, atmosphere, new Date(), greetingNonce, greetingPool);
  }, [dynamicGreetings, lang, atmosphere, greetingNonce, greetingPool, t]);

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
      // New session → show Settings defaults (no session override yet).
      apiJson("/api/me")
        .then((data) => {
          const chat = data.chat || {};
          const caps = chat.capabilities || {};
          setChatCapabilities(caps);
          setProviderInfo({
            id: chat.provider_id || "",
            name: chat.provider_name || "",
            model: chat.model || "",
            auto: Boolean(chat.auto),
            activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : [],
            toolProfile: chat.tool_profile || "auto",
          });
        })
        .catch(() => {});
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
          const fromMeta = Array.isArray(m.sources) ? m.sources : [];
          const fromActivity = (m.activity || [])
            .filter((ev) => ev?.name === "sources" && Array.isArray(ev.sources))
            .flatMap((ev) => ev.sources);
          const sources = mergeMessageSources(fromMeta, fromActivity);
          msgs.push({
            id: newId(),
            role: m.role,
            content: m.content || "",
            createdAt: m.created_at || null,
            model: m.model || "",
            thinking: label ? next : emptyThinking(t("thinking")),
            ...(Array.isArray(m.attachments) && m.attachments.length
              ? { attachments: mapStoredAttachments(m.attachments) }
              : {}),
            ...(sources.length ? { sources } : {}),
          });
        } else {
          const content = m.content === "(image)" ? "" : m.content || "";
          const row = {
            id: newId(),
            role: m.role,
            content,
            createdAt: m.created_at || null,
            ...(m.role === "assistant" && m.model ? { model: m.model } : {}),
          };
          if (Array.isArray(m.attachments) && m.attachments.length) {
            row.attachments = mapStoredAttachments(m.attachments);
          }
          if (m.role === "assistant" && Array.isArray(m.sources) && m.sources.length) {
            row.sources = mergeMessageSources([], m.sources);
          }
          msgs.push(row);
        }
      }
      setMessages(msgs);
      setAttachments([]);
      setSidebarOpen(false);
      try {
        const me = await apiJson(`/api/me?session_id=${encodeURIComponent(id)}`);
        const chat = me.chat || {};
        const caps = chat.capabilities || {};
        setChatCapabilities(caps);
        setProviderInfo({
          id: chat.provider_id || "",
          name: chat.provider_name || "",
          model: chat.model || "",
          auto: Boolean(chat.auto),
            activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : [],
            toolProfile: chat.tool_profile || "auto",
        });
        if (hasThinkingCapability(caps)) {
          setThinkingMode((prev) => readStoredThinkingMode(defaultThinkingMode(caps) || prev));
        } else {
          setThinkingMode("off");
        }
      } catch {
        /* keep current provider chrome */
      }
      return msgs;
    },
    [user.username, lang, t],
  );

  const speakReply = useCallback(
    async (assistantId, text) => {
      const clean = String(text || "").trim();
      const handsFree = handsFreeRef.current;
      if (!clean || voiceConfig.tts === false) {
        if (handsFree) setVoiceMode((v) => (v ? { ...v, phase: "listening", audioUrl: "" } : v));
        return;
      }
      try {
        const data = await voiceApi.speak(clean);
        const url = data?.url ? apiUrl(data.url) : "";
        if (!url) throw new Error("no audio");
        setMessages((prev) =>
          prev.map((m) => (m.id === assistantId ? { ...m, audioUrl: url } : m)),
        );
        if (handsFree) {
          // The overlay owns playback so it can hand the mic back when done.
          setVoiceMode((v) => (v ? { ...v, phase: "speaking", audioUrl: url, error: "" } : v));
        } else if (voiceConfig.autoplay !== false) {
          voiceApi.playAudio(url);
        }
      } catch (err) {
        // A failed TTS call must not strand the conversation or the written reply.
        if (handsFree) {
          setVoiceMode((v) =>
            v ? { ...v, phase: "listening", audioUrl: "", error: String(err?.message || err) } : v,
          );
        }
      }
    },
    [voiceConfig.autoplay, voiceConfig.tts],
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
        if (ev?.name === "route") {
          const model = String(ev.detail || "").trim();
          if (model) patchAssistant((m) => ({ ...m, model }));
          return;
        }
        if (ev?.name === "assistant" && typeof ev.detail === "string") {
          patchAssistant((m) => ({ ...m, content: ev.detail }));
          return;
        }
        if (ev?.name === "sources" && Array.isArray(ev.sources)) {
          patchAssistant((m) => ({
            ...m,
            sources: mergeMessageSources(m.sources, ev.sources),
          }));
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
        if (spokenTurnRef.current) {
          spokenTurnRef.current = false;
          speakReply(assistantId, full);
        }
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
        if (handsFreeRef.current) {
          spokenTurnRef.current = false;
          setVoiceMode((v) =>
            v ? { ...v, phase: "listening", audioUrl: "", error: err.message || "" } : v,
          );
        }
        clearPendingTrace(username);
      } finally {
        if (abortRef.current && abortRef.current.signal === signal) abortRef.current = null;
        setBusy(false);
        if (traceIdRef.current === traceId) traceIdRef.current = "";
      }
    },
    [finishAssistantMessage, openSession, refreshSessions, speakReply, t],
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
        setGreetingPool(Array.isArray(data.greeting_pool) ? data.greeting_pool : []);
        setVoiceConfig(data.voice && typeof data.voice === "object" ? data.voice : { enabled: false });
        setAtmosphere(data.atmosphere && typeof data.atmosphere === "object" ? data.atmosphere : {});
        const chat = data.chat || {};
        const caps = chat.capabilities || {};
        setChatCapabilities(caps);
        setProviderInfo({
          id: chat.provider_id || "",
          name: chat.provider_name || "",
          model: chat.model || "",
          auto: Boolean(chat.auto),
            activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : [],
            toolProfile: chat.tool_profile || "auto",
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

  const send = async (event, options = {}) => {
    event?.preventDefault?.();
    const text = (options.text ?? input).trim();
    const images = options.text ? [] : attachments;
    // Returns false when the turn did not start, so hands-free can recover.
    if (!canSendMessage(text, images) || busy) return false;
    // Only a spoken question gets a spoken answer.
    spokenTurnRef.current = Boolean(options.spoken);
    handsFreeRef.current = Boolean(options.handsFree);
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
        // Prefer the configured model id — never fall back to provider name
        // (e.g. "OpenRouter"); the live route event / history meta fill the exact id.
        model: providerInfo.auto ? "" : (providerInfo.model || ""),
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
      const aborted = err?.name === "AbortError" || signal.aborted;
      if (!aborted) {
        finishAssistantMessage(assistantId, err.message || "Request failed", { error: true });
      }
      if (handsFreeRef.current) {
        // Never strand the overlay on "thinking" when the turn never started.
        spokenTurnRef.current = false;
        setVoiceMode((v) =>
          v ? { ...v, phase: "listening", audioUrl: "", error: aborted ? "" : err.message || "" } : v,
        );
      }
      clearPendingTrace(user.username);
      setBusy(false);
      return true;
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

  // VoiceMode keeps the microphone open across turns, so its callbacks must be
  // referentially stable — a new function each render would restart the stream.
  const sendRef = useRef(null);
  useEffect(() => {
    sendRef.current = send;
  });

  const handsFreeUtterance = useCallback((text) => {
    setVoiceMode((v) => (v ? { ...v, phase: "thinking", audioUrl: "", error: "" } : v));
    Promise.resolve(sendRef.current?.(null, { text, spoken: true, handsFree: true })).then(
      (started) => {
        if (started === false) {
          setVoiceMode((v) => (v ? { ...v, phase: "listening", audioUrl: "" } : v));
        }
      },
    );
  }, []);

  const handsFreeSpokenEnd = useCallback(() => {
    setVoiceMode((v) => (v ? { ...v, phase: "listening", audioUrl: "" } : v));
  }, []);

  const closeVoiceMode = useCallback(() => {
    handsFreeRef.current = false;
    voiceApi.stopAudio();
    setVoiceMode(null);
  }, []);

  const refreshChatProvider = useCallback(async (sid) => {
    const sessionQuery = sid || sessionIdRef.current;
    const path = sessionQuery
      ? `/api/me?session_id=${encodeURIComponent(sessionQuery)}`
      : "/api/me";
    const data = await apiJson(path);
    const chat = data.chat || {};
    const caps = chat.capabilities || {};
    setChatCapabilities(caps);
    setProviderInfo({
      id: chat.provider_id || "",
      name: chat.provider_name || "",
      model: chat.model || "",
      auto: Boolean(chat.auto),
            activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : [],
            toolProfile: chat.tool_profile || "auto",
    });
    if (hasThinkingCapability(caps)) {
      setThinkingMode((prev) => readStoredThinkingMode(defaultThinkingMode(caps) || prev));
    } else {
      setThinkingMode("off");
    }
  }, []);

  const ensureSessionId = useCallback(() => {
    let sid = sessionIdRef.current;
    if (!sid) {
      startNewChat({ ephemeral: false });
      sid = sessionIdRef.current;
    }
    return sid;
  }, [startNewChat]);

  const updateProviderModel = useCallback(async (model) => {
    const providerId = providerInfo.id;
    if (!providerId || !model) return;
    const sid = ensureSessionId();
    const data = await apiJson(`/api/conversations/${encodeURIComponent(sid)}/provider`, {
      method: "PUT",
      body: JSON.stringify({ provider_id: providerId, model, auto: false }),
    });
    const chat = data.chat || {};
    setProviderInfo({
      id: chat.provider_id || providerId,
      name: chat.provider_name || providerInfo.name,
      model: chat.model || model,
      auto: false,
        activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : providerInfo.activePacks || [],
        toolProfile: chat.tool_profile || providerInfo.toolProfile || "auto",
    });
    if (chat.capabilities) setChatCapabilities(chat.capabilities);
  }, [providerInfo.id, providerInfo.name, ensureSessionId]);

  const changeProvider = useCallback(
    async (newId) => {
      if (!newId) return;
      const sid = ensureSessionId();
      if (newId === AUTO_PROVIDER) {
        if (providerInfo.auto) return;
        const data = await apiJson(`/api/conversations/${encodeURIComponent(sid)}/provider`, {
          method: "PUT",
          body: JSON.stringify({ auto: true }),
        });
        const chat = data.chat || {};
        setChatCapabilities(chat.capabilities || {});
        setProviderInfo({
          id: chat.provider_id || "",
          name: chat.provider_name || "",
          model: chat.model || "",
          auto: true,
          activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : [],
          toolProfile: chat.tool_profile || providerInfo.toolProfile || "auto",
        });
        return;
      }
      if (newId === providerInfo.id && !providerInfo.auto) return;
      const data = await apiJson(`/api/conversations/${encodeURIComponent(sid)}/provider`, {
        method: "PUT",
        body: JSON.stringify({ provider_id: newId, auto: false }),
      });
      const chat = data.chat || {};
      setChatCapabilities(chat.capabilities || {});
      setProviderInfo({
        id: chat.provider_id || newId,
        name: chat.provider_name || "",
        model: chat.model || "",
        auto: false,
        activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : providerInfo.activePacks || [],
        toolProfile: chat.tool_profile || providerInfo.toolProfile || "auto",
      });
    },
    [providerInfo.id, providerInfo.auto, ensureSessionId],
  );

  const clearActivePacks = useCallback(async () => {
    const sid = sessionIdRef.current;
    if (!sid) return;
    const data = await apiJson(`/api/conversations/${encodeURIComponent(sid)}/toolkits`, {
      method: "DELETE",
    });
    const chat = data.chat || {};
    setProviderInfo((prev) => ({
      ...prev,
      activePacks: Array.isArray(chat.active_packs) ? chat.active_packs : [],
      toolProfile: chat.tool_profile || prev.toolProfile || "auto",
    }));
  }, []);

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
        <header className="flex shrink-0 items-center justify-between px-6 py-2 pt-[max(0.5rem,env(safe-area-inset-top))] md:px-2">
          <button
            className="-ml-2 grid size-9 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            type="button"
            onClick={() => setSidebarOpen((v) => !v)}
            aria-label={t("chats")}
            title={t("chats")}
          >
            <ChatWindowIcon />
          </button>
          <a
            className="-mr-2 grid size-9 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
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
            modelLabel={providerInfo.auto ? "" : (providerInfo.model || "")}
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
            providerAuto={providerInfo.auto}
            providerId={providerInfo.id}
            providerModel={providerInfo.model}
            providerName={providerInfo.name}
            activePacks={providerInfo.activePacks || []}
            toolProfile={providerInfo.toolProfile || "auto"}
            stopLabel={t("stop")}
            thinkingMode={thinkingMode}
            unsupportedDocLabel={t("unsupportedDocument")}
            unsupportedImageLabel={t("unsupportedImage")}
            value={input}
            onAttachmentsChange={setAttachments}
            onChange={setInput}
            onClearPacks={clearActivePacks}
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
            voiceEnabled={voiceConfig.enabled === true}
            voiceControls={voiceConfig.controls || "both"}
            voiceSpeaks={voiceConfig.tts !== false}
            onVoiceModeOpen={() => {
              voiceApi.unlockPlayback();
              setVoiceMode({ phase: "listening", audioUrl: "", error: "" });
            }}
            onVoiceTranscript={(text) => send(null, { text, spoken: true })}
          />
        </div>
      </div>

      {voiceMode ? (
        <VoiceMode
          error={voiceMode.error}
          lang={lang}
          phase={voiceMode.phase}
          replyAudioUrl={voiceMode.audioUrl}
          onClose={closeVoiceMode}
          onSpokenEnd={handsFreeSpokenEnd}
          onUtterance={handsFreeUtterance}
        />
      ) : null}
    </div>
  );
}
