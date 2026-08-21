import { useEffect, useState } from "react";
import { useScrollToBottom } from "../hooks/useScrollToBottom.js";
import { MessageBubble } from "./MessageBubble.jsx";

export function Messages({ messages, lang, greeting, onReuseMessage }) {
  const { containerRef, endRef } = useScrollToBottom();
  const [selectedId, setSelectedId] = useState(null);
  const empty = messages.length === 0;

  useEffect(() => {
    if (!selectedId) return undefined;
    if (!messages.some((m) => m.id === selectedId)) setSelectedId(null);
  }, [messages, selectedId]);

  useEffect(() => {
    if (!selectedId) return undefined;
    const onKey = (event) => {
      if (event.key === "Escape") setSelectedId(null);
    };
    const onPointer = (event) => {
      const node = event.target;
      if (node?.closest?.("[data-role='user'], [data-role='assistant'], [role='toolbar']")) return;
      setSelectedId(null);
    };
    window.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => {
      window.removeEventListener("keydown", onKey);
      document.removeEventListener("pointerdown", onPointer);
    };
  }, [selectedId]);

  return (
    <div className="relative min-h-0 flex-1 bg-background">
      {empty ? (
        <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center overflow-visible px-2">
          {greeting}
        </div>
      ) : null}
      <div
        ref={containerRef}
        className="absolute inset-0 touch-pan-y overflow-y-auto"
        style={{ WebkitOverflowScrolling: "touch" }}
      >
        <div className="mx-auto flex min-h-full min-w-0 max-w-4xl flex-col gap-6 px-3 py-6 md:gap-8 md:px-4">
          {messages.map((message) => (
            <MessageBubble
              key={message.id}
              lang={lang}
              message={message}
              selected={selectedId === message.id}
              onReuse={onReuseMessage}
              onSelect={setSelectedId}
            />
          ))}
          <div ref={endRef} className="min-h-6 min-w-6 shrink-0" />
        </div>
      </div>
    </div>
  );
}
