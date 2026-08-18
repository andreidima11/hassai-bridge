import { PlusIcon } from "./Icons.jsx";

export function Sidebar({ open, onClose, title, newLabel, emptyLabel, userLabel, sessions, sessionId, onNew, onOpen, onDelete }) {
  return (
    <>
      <div
        className={`absolute inset-0 z-[34] bg-black/45 transition ${open ? "visible opacity-100" : "invisible opacity-0 pointer-events-none"}`}
        onClick={onClose}
      />
      <aside
        className={`absolute bottom-0 left-0 top-0 z-[36] flex w-[min(280px,86vw)] flex-col border-r border-border/80 bg-sidebar text-sidebar-foreground transition-transform duration-200 ease-spring ${
          open ? "visible translate-x-0" : "invisible -translate-x-[110%] pointer-events-none"
        }`}
      >
        <div className="flex items-center justify-between px-3.5 pb-2.5 pt-4 text-[13px]">
          <strong>{title}</strong>
          <button
            className="grid size-8 place-items-center rounded-lg text-sidebar-foreground hover:bg-white/5"
            type="button"
            onClick={onNew}
            aria-label={newLabel}
            title={newLabel}
          >
            <PlusIcon />
          </button>
        </div>
        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-2 pb-3">
          {!sessions.length ? (
            <div className="px-2 py-8 text-center text-[13px] text-sidebar-foreground/45">{emptyLabel}</div>
          ) : (
            sessions.map((s) => (
              <div
                key={s.session_id}
                className={`flex h-8 cursor-pointer items-center gap-2 px-2 text-[13px] ${
                  s.session_id === sessionId
                    ? "border-b border-dashed border-sidebar-foreground/50 font-medium text-sidebar-foreground"
                    : "text-sidebar-foreground/50 hover:text-sidebar-foreground"
                }`}
                onClick={() => onOpen(s.session_id)}
              >
                <span className="min-w-0 flex-1 truncate">{s.title}</span>
                <button
                  className="px-1 opacity-45 hover:text-destructive hover:opacity-100"
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(s.session_id);
                  }}
                >
                  ×
                </button>
              </div>
            ))
          )}
        </div>
        <div className="border-t border-border/70 px-3.5 py-3 text-[13px] text-sidebar-foreground/70">{userLabel}</div>
      </aside>
    </>
  );
}
