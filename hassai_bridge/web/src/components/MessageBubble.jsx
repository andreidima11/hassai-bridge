import { SparklesIcon } from "./Icons.jsx";
import { MarkdownBody } from "./MarkdownBody.jsx";
import { Thinking } from "./Thinking.jsx";
import { tr } from "../lib/i18n.js";

export function MessageBubble({ message, lang }) {
  const isUser = message.role === "user";

  if (isUser) {
    const images = Array.isArray(message.attachments) ? message.attachments : [];
    return (
      <div className="group/message w-full" data-role="user">
        <div className="flex flex-col items-end gap-2">
          {images.length ? (
            <div className="flex max-w-[min(80%,56ch)] flex-wrap justify-end gap-2">
              {images.map((img) => (
                <img
                  key={img.id || img.url || img.previewUrl}
                  alt=""
                  className="max-h-56 max-w-full rounded-[18px] border border-white/10 object-cover"
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
            <Thinking thinking={message.thinking} lang={lang} streaming={Boolean(message.streaming)} />
          ) : null}
          {Array.isArray(message.attachments) && message.attachments.length ? (
            <div className="flex max-w-full flex-wrap gap-2">
              {message.attachments.map((img) => (
                <img
                  key={img.id || img.url || img.previewUrl}
                  alt=""
                  className="max-h-80 max-w-full rounded-xl border border-white/10 object-cover"
                  src={img.previewUrl || img.url || img.dataUrl}
                />
              ))}
            </div>
          ) : null}
          {message.content ? (
            <MarkdownBody
              copiedLabel={tr(lang, "copied")}
              copyLabel={tr(lang, "copy")}
              cursor={message.streaming ? <span className="ml-0.5 animate-pulse text-muted-foreground">▍</span> : null}
              text={message.content}
            />
          ) : message.streaming && !message.thinking?.visible ? (
            <div className="flex min-h-7 items-center text-[15px] font-medium text-muted-foreground">…</div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
