import { useMemo } from "react";
import { ChatImage } from "./ChatImage.jsx";
import { SparklesIcon } from "./Icons.jsx";
import { MarkdownBody } from "./MarkdownBody.jsx";
import { Thinking } from "./Thinking.jsx";
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

export function MessageBubble({ message, lang }) {
  const isUser = message.role === "user";
  const streaming = Boolean(message.streaming);
  const attachments = Array.isArray(message.attachments) ? message.attachments : [];
  const rawContent = useMemo(
    () => (isUser ? message.content : stripDuplicateAttachmentMarkdown(message.content, attachments)),
    [isUser, message.content, attachments],
  );
  const content = useSmoothStreamText(rawContent, !isUser && streaming);

  if (isUser) {
    return (
      <div className="group/message w-full" data-role="user">
        <div className="flex flex-col items-end gap-2">
          {attachments.length ? (
            <div className="flex max-w-[min(80%,56ch)] flex-wrap justify-end gap-2">
              {attachments.map((img) => (
                <ChatImage
                  key={img.id || img.url || img.previewUrl}
                  alt={img.name || ""}
                  className="max-h-56 max-w-full rounded-[18px] border border-white/10 object-cover"
                  filename={img.name || ""}
                  lang={lang}
                  mime={img.mime || ""}
                  src={img.previewUrl || img.url || img.dataUrl}
                />
              ))}
            </div>
          ) : null}
          {message.content ? (
            <div className="w-fit max-w-[min(80%,56ch)] overflow-hidden break-words rounded-[22px] bg-secondary px-5 py-2.5 text-[15px] leading-7 whitespace-pre-wrap">
              {message.content}
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  return (
    <div className={`group/message w-full ${message.error ? "text-destructive" : ""}`} data-role="assistant">
      <div className="flex items-start gap-3">
        <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-full bg-white/10 text-foreground">
          <SparklesIcon size={13} />
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2 pt-0.5">
          {message.thinking?.visible ? (
            <Thinking thinking={message.thinking} lang={lang} streaming={streaming} />
          ) : null}
          {attachments.length ? (
            <div className="flex max-w-full flex-wrap gap-2">
              {attachments.map((img) => (
                <ChatImage
                  key={img.id || img.url || img.previewUrl}
                  alt={img.name || ""}
                  className="max-h-80 max-w-full rounded-xl border border-white/10 object-cover"
                  filename={img.name || ""}
                  lang={lang}
                  mime={img.mime || ""}
                  src={img.previewUrl || img.url || img.dataUrl}
                />
              ))}
            </div>
          ) : null}
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
        </div>
      </div>
    </div>
  );
}
