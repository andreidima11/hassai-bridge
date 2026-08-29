import { useEffect, useMemo, useRef, useState } from "react";
import { ChatImage } from "./ChatImage.jsx";
import { MessageActions } from "./MessageActions.jsx";
import { DocumentIcon, SparklesIcon, SpeakerIcon } from "./Icons.jsx";
import { MarkdownBody } from "./MarkdownBody.jsx";
import { Thinking } from "./Thinking.jsx";
import { isDocumentAttachment, isVideoAttachment, isImageAttachment } from "../lib/images.js";
import { tr } from "../lib/i18n.js";
import { useSmoothStreamText } from "../lib/smoothStream.js";

function escapeRegExp(value) {
  return String(value || "").replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Remove markdown images that already appear in the attachments gallery (avoids double images). */
export function stripDuplicateAttachmentMarkdown(text, attachments) {
  let out = String(text || "");
  if (!out || !attachments?.length) return out;
  for (const att of attachments) {
    const id = String(att?.id || "").trim();
    const urls = [att?.previewUrl, att?.url, att?.dataUrl].filter(Boolean).map(String);
    if (id) {
      out = out.replace(new RegExp(`!\\[[^\\]]*\\]\\([^\\)]*${escapeRegExp(id)}[^\\)]*\\)`, "gi"), "");
    }
    for (const url of urls) {
      out = out.replace(new RegExp(`!\\[[^\\]]*\\]\\(\\s*${escapeRegExp(url)}\\s*\\)`, "gi"), "");
    }
  }
  return out.replace(/[ \t]+\n/g, "\n").replace(/\n{3,}/g, "\n\n").trim();
}

function AttachmentGallery({ attachments, align = "start", lang = "en" }) {
  if (!attachments?.length) return null;
  const images = attachments.filter((item) => isImageAttachment(item));
  const videos = attachments.filter((item) => isVideoAttachment(item));
  const docs = attachments.filter((item) => isDocumentAttachment(item));
  return (
    <div
      className={`flex max-w-full flex-col gap-2 ${
        align === "end" ? "items-end" : "items-start"
      }`}
    >
      {videos.length ? (
        <div className={`flex max-w-full flex-col gap-2 ${align === "end" ? "items-end" : "items-start"}`}>
          {videos.map((vid) => {
            const src = vid.previewUrl || vid.url || vid.dataUrl;
            if (!src) return null;
            return (
              <video
                key={vid.id || src}
                controls
                playsInline
                preload="metadata"
                className={
                  align === "end"
                    ? "max-h-56 max-w-full rounded-[18px] border border-white/10 bg-black"
                    : "max-h-80 max-w-full rounded-xl border border-white/10 bg-black"
                }
                src={src}
              >
                {tr(lang, "videoUnsupported") || "Video not supported"}
              </video>
            );
          })}
        </div>
      ) : null}
      {images.length ? (
        <div className={`flex max-w-full flex-wrap gap-2 ${align === "end" ? "justify-end" : ""}`}>
          {images.map((img) => (
            <ChatImage
              key={img.id || img.url || img.previewUrl}
              alt={img.name || ""}
              className={
                align === "end"
                  ? "max-h-56 max-w-full rounded-[18px] border border-white/10 object-cover"
                  : "max-h-80 max-w-full rounded-xl border border-white/10 object-cover"
              }
              filename={img.name || ""}
              lang={lang}
              mime={img.mime || ""}
              src={img.previewUrl || img.url || img.dataUrl}
            />
          ))}
        </div>
      ) : null}
      {docs.length ? (
        <div className={`flex max-w-full flex-wrap gap-2 ${align === "end" ? "justify-end" : ""}`}>
          {docs.map((doc) => (
            <div
              key={doc.id || doc.name}
              className="flex max-w-[16rem] items-center gap-2 rounded-xl border border-white/10 bg-white/[0.04] px-3 py-2"
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/10">
                <DocumentIcon size={15} />
              </span>
              <span className="min-w-0">
                <span className="block truncate text-[13px] text-foreground/90">{doc.name || "document"}</span>
                <span className="block truncate text-[11px] text-muted-foreground">{doc.mime || "document"}</span>
              </span>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function isInteractiveTarget(target) {
  return Boolean(
    target?.closest?.(
      "a, button, input, textarea, select, summary, [role='button'], [role='toolbar'], .group\\/code",
    ),
  );
}

function ReplyAudio({ url, lang }) {
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef(null);

  useEffect(() => {
    return () => audioRef.current?.pause();
  }, []);

  const toggle = () => {
    if (playing) {
      audioRef.current?.pause();
      setPlaying(false);
      return;
    }
    const audio = audioRef.current || new Audio(url);
    audioRef.current = audio;
    audio.onended = () => setPlaying(false);
    audio.play().then(() => setPlaying(true)).catch(() => setPlaying(false));
  };

  return (
    <button
      type="button"
      className="inline-flex w-fit items-center gap-1.5 rounded-full border border-white/10 px-2.5 py-1 text-[12px] text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
      aria-label={tr(lang, playing ? "voiceStopPlayback" : "voicePlay")}
      title={tr(lang, playing ? "voiceStopPlayback" : "voicePlay")}
      onClick={toggle}
    >
      <SpeakerIcon />
      {tr(lang, playing ? "voiceStopPlayback" : "voicePlay")}
    </button>
  );
}

export function MessageBubble({
  message,
  lang,
  selected = false,
  onSelect,
  onReuse,
  userLabel = "",
  modelLabel = "",
}) {
  const isUser = message.role === "user";
  const streaming = Boolean(message.streaming);
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];
  const rawContent = useMemo(
    () => (isUser ? message.content : stripDuplicateAttachmentMarkdown(message.content, attachments)),
    [isUser, message.content, attachments],
  );
  const content = useSmoothStreamText(rawContent, !isUser && streaming);
  const canSelect = !streaming;

  const handleSelect = (event) => {
    if (!canSelect) return;
    if (isInteractiveTarget(event.target)) return;
    // Ignore accidental text selection drags
    const sel = typeof window.getSelection === "function" ? window.getSelection() : null;
    if (sel && String(sel.toString() || "").trim()) return;
    onSelect?.(selected ? null : message.id);
  };

  const actions =
    selected && canSelect ? (
      <MessageActions
        lang={lang}
        message={{ ...message, content: rawContent }}
        modelLabel={modelLabel}
        userLabel={userLabel}
        onClose={() => onSelect?.(null)}
        onReuse={onReuse}
      />
    ) : null;

  if (isUser) {
    return (
      <div
        className={`group/message w-full rounded-2xl outline-none transition ${
          selected ? "bg-white/[0.03] ring-1 ring-white/10" : ""
        } ${canSelect ? "cursor-pointer" : ""}`}
        data-role="user"
        data-selected={selected ? "true" : undefined}
        onClick={handleSelect}
      >
        <div className="flex flex-col items-end gap-2 px-1 py-1">
          <AttachmentGallery attachments={attachments} align="end" lang={lang} />
          {message.content ? (
            <div className="w-fit max-w-[min(80%,56ch)] overflow-hidden break-words rounded-[22px] bg-secondary px-5 py-2.5 text-[15px] leading-7 whitespace-pre-wrap">
              {message.content}
            </div>
          ) : null}
          {actions}
        </div>
      </div>
    );
  }

  return (
    <div
      className={`group/message w-full rounded-2xl outline-none transition ${
        message.error ? "text-destructive" : ""
      } ${selected ? "bg-white/[0.03] ring-1 ring-white/10" : ""} ${canSelect ? "cursor-pointer" : ""}`}
      data-role="assistant"
      data-selected={selected ? "true" : undefined}
      onClick={handleSelect}
    >
      <div className="flex items-start gap-3 px-1 py-1">
        <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-white/10 text-foreground">
          <SparklesIcon size={13} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2 pt-0.5">
          {message.thinking?.visible ? (
            <Thinking thinking={message.thinking} lang={lang} streaming={streaming} />
          ) : null}
          <AttachmentGallery attachments={attachments} align="start" lang={lang} />
          {content ? (
            <MarkdownBody
              className={streaming ? "is-streaming" : ""}
              copiedLabel={tr(lang, "copied")}
              copyLabel={tr(lang, "copy")}
              cursor={streaming ? <span className="stream-cursor" aria-hidden="true" /> : null}
              lang={lang}
              text={content}
            />
          ) : streaming && !message.thinking?.visible ? (
            <div className="flex min-h-7 items-center gap-1 text-[15px] text-muted-foreground">
              <span className="stream-cursor stream-cursor--alone" aria-hidden="true" />
            </div>
          ) : null}
          {message.audioUrl ? <ReplyAudio lang={lang} url={message.audioUrl} /> : null}
          {actions}
        </div>
      </div>
    </div>
  );
}
