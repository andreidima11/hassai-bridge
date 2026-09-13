import { useEffect, useState } from "react";
import { useScrollToBottom } from "../hooks/useScrollToBottom.js";
import { BackgroundTaskCard, isActiveBgTask } from "./BackgroundTaskCard.jsx";
import { MessageBubble } from "./MessageBubble.jsx";

export function Messages({
  messages,
  lang,
  greeting,
  activeBgTasks = [],
  onReuseMessage,
  onPickFollowup,
  onManageFollowup,
  onApproveTool = null,
  onBgTaskCancelled = null,
  userLabel = "",
  modelLabel = "",
}) {
  const { containerRef, endRef } = useScrollToBottom();
  const [selectedId, setSelectedId] = useState(null);
  const empty = messages.length === 0;
  const lastId = messages.length ? messages[messages.length - 1]?.id : null;
  const shownIds = new Set(
    messages.map((m) => m.backgroundTask?.task_id).filter(Boolean),
  );
  const floating = (activeBgTasks || []).filter(
    (t) => isActiveBgTask(t) && !shownIds.has(t.task_id),
  );

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
      if (node?.closest?.("[data-role='user'], [data-role='assistant'], [role='toolbar'], [data-bg-task]")) return;
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
              modelLabel={modelLabel}
              selected={selectedId === message.id}
              showFollowups={message.id === lastId && message.role === "assistant" && !message.streaming}
              userLabel={userLabel}
              onReuse={onReuseMessage}
              onPickFollowup={onPickFollowup}
              onManageFollowup={onManageFollowup}
              onApproveTool={onApproveTool}
              onBgTaskCancelled={onBgTaskCancelled}
              onSelect={setSelectedId}
            />
          ))}
          {floating.length ? (
            <div className="flex flex-col gap-2 pl-10">
              {floating.map((task) => (
                <BackgroundTaskCard
                  key={task.task_id}
                  task={task}
                  lang={lang}
                  onCancelled={onBgTaskCancelled}
                />
              ))}
            </div>
          ) : null}
          <div ref={endRef} className="min-h-6 min-w-6 shrink-0" />
        </div>
      </div>
    </div>
  );
}
