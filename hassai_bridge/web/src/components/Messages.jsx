import { useScrollToBottom } from "../hooks/useScrollToBottom.js";
import { MessageBubble } from "./MessageBubble.jsx";

export function Messages({ messages, lang, greeting }) {
  const { containerRef, endRef } = useScrollToBottom();
  const empty = messages.length === 0;

  return (
    <div className="relative min-h-0 flex-1 bg-background">
      {empty ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center">
          {greeting}
        </div>
      ) : null}
      <div
        ref={containerRef}
        className="absolute inset-0 touch-pan-y overflow-y-auto"
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        <div className="mx-auto flex min-h-full min-w-0 max-w-4xl flex-col gap-5 px-2 py-6 md:gap-7 md:px-4">
          {messages.map((message) => (
            <MessageBubble key={message.id} lang={lang} message={message} />
          ))}
          <div ref={endRef} className="min-h-6 min-w-6 shrink-0" />
        </div>
      </div>
    </div>
  );
}
