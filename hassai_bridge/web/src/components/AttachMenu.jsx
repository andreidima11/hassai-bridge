import { useEffect } from "react";
import { createPortal } from "react-dom";
import { DocumentIcon, FolderIcon, ImageIcon, PhoneIcon, XIcon } from "./Icons.jsx";
import { tr } from "../lib/i18n.js";

function Row({ icon, title, hint, children, onClick }) {
  const body = (
    <>
      <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-white/10 text-foreground">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-[15px] text-foreground">{title}</span>
        <span className="block text-[12.5px] leading-5 text-muted-foreground">{hint}</span>
      </span>
    </>
  );
  if (onClick) {
    return (
      <button
        type="button"
        className="flex w-full items-center gap-3 rounded-2xl px-3 py-3 text-left transition hover:bg-white/[0.06] active:bg-white/[0.09]"
        onClick={onClick}
      >
        {body}
      </button>
    );
  }
  return (
    <span className="relative flex w-full cursor-pointer items-center gap-3 overflow-hidden rounded-2xl px-3 py-3 text-left transition hover:bg-white/[0.06] active:bg-white/[0.09]">
      {body}
      {children}
    </span>
  );
}

/** Transparent input over the row — the picker the Companion WebView actually opens. */
function RowInput({ accept, multiple, label, onOpen, onChange }) {
  return (
    <input
      type="file"
      accept={accept}
      multiple={multiple}
      aria-label={label}
      className="absolute inset-0 size-full cursor-pointer opacity-0"
      style={{ fontSize: 64 }}
      onClick={onOpen}
      onChange={onChange}
    />
  );
}

export function AttachMenu({
  lang,
  photoAccept = "image/*",
  docAccept = "*/*",
  multiple = false,
  showBrowserUpload = false,
  onBrowseHa,
  onBrowserUpload,
  onClose,
  onFiles,
  onPickerOpen,
}) {
  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="fixed inset-0 z-[90] flex items-end justify-center bg-black/70 sm:items-center sm:p-4">
      <button
        type="button"
        aria-label={tr(lang, "closeImage")}
        className="absolute inset-0 size-full cursor-default"
        tabIndex={-1}
        onClick={onClose}
      />
      <div className="relative w-full max-w-md rounded-t-3xl border border-white/10 bg-composer p-2 pb-[max(0.5rem,env(safe-area-inset-bottom))] shadow-composer sm:rounded-3xl sm:pb-2">
        <div className="flex items-center gap-2 px-3 pb-1 pt-2">
          <div className="flex-1 text-[14px] font-medium text-foreground">{tr(lang, "attachTitle")}</div>
          <button
            type="button"
            className="grid size-8 place-items-center rounded-full text-muted-foreground hover:bg-white/10 hover:text-foreground"
            aria-label={tr(lang, "closeImage")}
            onClick={onClose}
          >
            <XIcon size={14} />
          </button>
        </div>

        <Row hint={tr(lang, "attachPhotoHint")} icon={<ImageIcon />} title={tr(lang, "attachImage")}>
          <RowInput
            accept={photoAccept}
            label={tr(lang, "attachImage")}
            multiple={multiple}
            onChange={(e) => onFiles(e, "image")}
            onOpen={onPickerOpen}
          />
        </Row>

        <Row hint={tr(lang, "attachDocHint")} icon={<DocumentIcon size={18} />} title={tr(lang, "attachDocument")}>
          <RowInput
            accept={docAccept}
            label={tr(lang, "attachDocument")}
            multiple={multiple}
            onChange={(e) => onFiles(e, "document")}
            onOpen={onPickerOpen}
          />
        </Row>

        <Row
          hint={tr(lang, "haFilesMenuHint")}
          icon={<FolderIcon size={18} />}
          title={tr(lang, "haFiles")}
          onClick={onBrowseHa}
        />

        {showBrowserUpload ? (
          <Row
            hint={tr(lang, "browserUploadHint")}
            icon={<PhoneIcon size={18} />}
            title={tr(lang, "browserUpload")}
            onClick={onBrowserUpload}
          />
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
