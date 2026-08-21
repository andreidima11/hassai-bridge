import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { DocumentIcon, FolderIcon, ImageIcon, XIcon } from "./Icons.jsx";
import { attachChatFile, baseName, listChatFiles } from "../lib/chatFiles.js";
import { tr } from "../lib/i18n.js";

function formatSize(bytes) {
  const n = Number(bytes) || 0;
  if (n >= 1_000_000) return `${(n / 1_048_576).toFixed(1)} MB`;
  if (n >= 1000) return `${Math.round(n / 1024)} KB`;
  return `${n} B`;
}

export function HaFileBrowser({ lang, kind = "", onClose, onAttached }) {
  const [path, setPath] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [busyPath, setBusyPath] = useState("");

  const load = useCallback(
    async (next) => {
      setLoading(true);
      setError("");
      try {
        const out = await listChatFiles(next, kind);
        setData(out);
        setPath(out.path || "");
      } catch (err) {
        setError(String(err?.message || err));
      } finally {
        setLoading(false);
      }
    },
    [kind],
  );

  useEffect(() => {
    load("");
  }, [load]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const pick = async (file) => {
    setBusyPath(file.path);
    setError("");
    try {
      const attachment = await attachChatFile(file.path);
      onAttached(attachment);
      onClose();
    } catch (err) {
      setError(String(err?.message || err));
    } finally {
      setBusyPath("");
    }
  };

  if (typeof document === "undefined") return null;

  const dirs = data?.dirs || [];
  const files = data?.files || [];
  const empty = !loading && !dirs.length && !files.length;

  return createPortal(
    <div className="fixed inset-0 z-[70] flex items-end justify-center bg-black/70 p-0 sm:items-center sm:p-4">
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col overflow-hidden rounded-t-2xl border border-white/10 bg-composer sm:rounded-2xl">
        <div className="flex items-center gap-2 border-b border-white/10 px-4 py-3">
          <div className="min-w-0 flex-1">
            <div className="text-[14px] font-medium text-foreground">{tr(lang, "haFilesTitle")}</div>
            <div className="truncate text-[12px] text-muted-foreground">{path || tr(lang, "haFilesRoots")}</div>
          </div>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            aria-label={tr(lang, "closeImage")}
            onClick={onClose}
          >
            <XIcon size={14} />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2">
          {loading ? (
            <div className="px-3 py-6 text-center text-[13px] text-muted-foreground">{tr(lang, "haFilesLoading")}</div>
          ) : null}
          {error ? <div className="px-3 py-2 text-[13px] text-amber-400/90">{error}</div> : null}

          {!loading && data?.parent !== undefined && path ? (
            <button
              type="button"
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-white/[0.06]"
              onClick={() => load(data.parent || "")}
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/10 text-muted-foreground">
                <FolderIcon size={16} />
              </span>
              <span className="text-[14px] text-foreground/90">{tr(lang, "haFilesUp")}</span>
            </button>
          ) : null}

          {dirs.map((dir) => (
            <button
              key={dir.path}
              type="button"
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-white/[0.06]"
              onClick={() => load(dir.path)}
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/10 text-muted-foreground">
                <FolderIcon size={16} />
              </span>
              <span className="truncate text-[14px] text-foreground/90">{baseName(dir.name) || dir.name}</span>
            </button>
          ))}

          {files.map((file) => (
            <button
              key={file.path}
              type="button"
              className="flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left hover:bg-white/[0.06] disabled:opacity-50"
              disabled={Boolean(busyPath)}
              onClick={() => pick(file)}
            >
              <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/10 text-muted-foreground">
                {file.kind === "image" ? <ImageIcon /> : <DocumentIcon size={16} />}
              </span>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] text-foreground/90">{file.name}</span>
                <span className="block text-[12px] text-muted-foreground">
                  {busyPath === file.path ? tr(lang, "haFilesAttaching") : formatSize(file.size)}
                </span>
              </span>
            </button>
          ))}

          {empty ? (
            <div className="px-3 py-6 text-center text-[13px] text-muted-foreground">{tr(lang, "haFilesEmpty")}</div>
          ) : null}
        </div>

        <div className="border-t border-white/10 px-4 py-2.5 text-[12px] text-muted-foreground">
          {tr(lang, "haFilesHint")}
        </div>
      </div>
    </div>,
    document.body,
  );
}
