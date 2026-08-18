import { SparklesIcon } from "./Icons.jsx";
import { Thinking } from "./Thinking.jsx";

export function MessageBubble({ message, lang }) {
  const isUser = message.role === "user";
  const isAssistant = message.role === "assistant";

  if (isUser) {
    return (
      <div className="group/message w-full" data-role="user">
        <div className="flex flex-col items-end gap-2">
          <div className="w-fit max-w-[min(80%,56ch)] overflow-hidden break-words rounded-2xl rounded-br-lg border border-border/30 bg-gradient-to-br from-secondary to-muted px-3.5 py-2 text-[13px] leading-[1.65] shadow-card whitespace-pre-wrap">
            {message.content}
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className={`group/message w-full ${message.error ? "text-destructive" : ""}`} data-role="assistant">
      <div className="flex items-start gap-3">
        <div className="flex h-[calc(13px*1.65)] shrink-0 items-center">
          <div className="flex size-7 items-center justify-center rounded-lg bg-muted/60 text-muted-foreground ring-1 ring-border/50">
            <SparklesIcon size={13} />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col gap-2">
          {message.thinking?.visible ? <Thinking thinking={message.thinking} lang={lang} /> : null}
          {message.content ? (
            <div className="text-[13px] leading-[1.65] whitespace-pre-wrap break-words text-foreground">
              {message.content}
              {message.streaming ? <span className="ml-0.5 animate-pulse text-muted-foreground">▍</span> : null}
            </div>
          ) : message.streaming ? (
            <div className="flex min-h-[calc(13px*1.65)] items-center text-[13px] font-medium text-muted-foreground">
              {message.thinking?.label || "…"}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}
