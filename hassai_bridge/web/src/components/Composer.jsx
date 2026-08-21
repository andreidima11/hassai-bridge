import { useEffect, useId, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { ChatImage } from "./ChatImage.jsx";
import { ArrowUpIcon, DocumentIcon, ImageIcon, StopIcon, XIcon } from "./Icons.jsx";
import {
  documentAcceptAttr,
  isDocumentAttachment,
  isHaCompanionApp,
  MAX_CHAT_ATTACHMENTS,
  prepareDocumentFile,
  prepareImageFile,
} from "../lib/images.js";
import { ProviderQuickSettings } from "./ProviderQuickSettings.jsx";

export function Composer({
  value,
  onChange,
  onSubmit,
  onStop,
  busy,
  placeholder,
  stopLabel,
  attachments,
  onAttachmentsChange,
  attachLabel,
  attachDocLabel,
  removeImageLabel,
  removeDocLabel,
  imageTooLargeLabel,
  docTooLargeLabel,
  maxImagesLabel,
  unsupportedImageLabel,
  unsupportedDocLabel,
  providerId = "",
  providerName = "",
  providerModel = "",
  providerCapabilities = {},
  thinkingMode = "auto",
  onThinkingModeChange,
  onProviderModelChange,
  onProviderChange,
  lang = "en",
  onPickerOpen,
  onPickerSettled,
}) {
  const attachInputId = useId();
  const docInputId = useId();
  const ref = useRef(null);
  const fileRef = useRef(null);
  const docRef = useRef(null);
  const processingRef = useRef(false);
  const [tall, setTall] = useState(false);
  const [attachError, setAttachError] = useState("");
  const [uploading, setUploading] = useState(false);
  const companionApp = isHaCompanionApp();

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(Math.max(el.scrollHeight, 24), 160);
    el.style.height = `${next}px`;
    setTall(next > 28 || (attachments?.length || 0) > 0);
  }, [value, attachments]);

  const canSend = Boolean(value.trim()) || (attachments?.length || 0) > 0;
  const attachDisabled = busy || uploading || (attachments?.length || 0) >= MAX_CHAT_ATTACHMENTS;

  const finishPicking = () => {
    onPickerSettled?.();
  };

  const addPrepared = async (files, prepare, labels) => {
    if (!files?.length || !onAttachmentsChange) {
      finishPicking();
      return;
    }
    setAttachError("");
    setUploading(true);
    let added = 0;
    for (const file of files) {
      try {
        const prepared = await prepare(file);
        onAttachmentsChange((current) => {
          const base = current || [];
          if (base.length >= MAX_CHAT_ATTACHMENTS) return base;
          return [...base, prepared];
        });
        added += 1;
      } catch (err) {
        const code = String(err?.message || "");
        if (code === "too_large") setAttachError(labels.tooLarge);
        else setAttachError(labels.unsupported);
      }
    }
    if (added >= MAX_CHAT_ATTACHMENTS) setAttachError(maxImagesLabel);
    setUploading(false);
    finishPicking();
  };

  const addImageFiles = (files) =>
    addPrepared(files, prepareImageFile, {
      tooLarge: imageTooLargeLabel,
      unsupported: unsupportedImageLabel,
    });

  const addDocFiles = (files) =>
    addPrepared(files, prepareDocumentFile, {
      tooLarge: docTooLargeLabel || imageTooLargeLabel,
      unsupported: unsupportedDocLabel || unsupportedImageLabel,
    });

  const handleFileInput = async (event, kind) => {
    if (processingRef.current) return;
    const input = event.currentTarget;
    const picked = Array.from(input.files || []);
    if (!picked.length) {
      finishPicking();
      input.value = "";
      return;
    }
    processingRef.current = true;
    try {
      if (kind === "document") await addDocFiles(picked);
      else await addImageFiles(picked);
    } finally {
      processingRef.current = false;
      input.value = "";
    }
  };

  const removeAttachment = (id) => {
    if (!onAttachmentsChange) return;
    onAttachmentsChange((attachments || []).filter((item) => item.id !== id));
    setAttachError("");
  };

  const imageInput = (
    <input
      ref={fileRef}
      id={attachInputId}
      type="file"
      accept="image/*"
      multiple={!companionApp}
      tabIndex={-1}
      aria-hidden="true"
      style={{ position: "fixed", top: "-10000px", left: 0, width: 1, height: 1, opacity: 0 }}
      disabled={attachDisabled}
      onChange={(e) => handleFileInput(e, "image")}
    />
  );

  const docInput = (
    <input
      ref={docRef}
      id={docInputId}
      type="file"
      accept={documentAcceptAttr()}
      multiple={!companionApp}
      tabIndex={-1}
      aria-hidden="true"
      style={{ position: "fixed", top: "-10000px", left: 0, width: 1, height: 1, opacity: 0 }}
      disabled={attachDisabled}
      onChange={(e) => handleFileInput(e, "document")}
    />
  );

  return (
    <div className="sticky bottom-0 z-[1] mx-auto flex w-full max-w-4xl flex-col bg-background px-3 pb-3 md:px-4 md:pb-4">
      {typeof document !== "undefined" ? createPortal(imageInput, document.body) : imageInput}
      {typeof document !== "undefined" ? createPortal(docInput, document.body) : docInput}
      <form
        className={`flex w-full flex-col gap-2 border border-white/[0.08] bg-composer px-3 shadow-composer transition-[border-radius] duration-200 focus-within:border-white/15 ${
          tall ? "rounded-3xl py-2" : "rounded-full py-1"
        }`}
        onSubmit={onSubmit}
      >
        {attachments?.length ? (
          <div className="flex flex-wrap gap-2 pt-1">
            {attachments.map((item) => {
              const isDoc = isDocumentAttachment(item);
              return (
                <div
                  key={item.id}
                  className={`relative overflow-hidden rounded-xl border border-white/10 bg-black/20 ${
                    isDoc ? "flex h-16 min-w-[9.5rem] max-w-[14rem] items-center gap-2 px-2.5" : "size-16"
                  }`}
                >
                  {isDoc ? (
                    <>
                      <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-white/10 text-foreground">
                        <DocumentIcon size={16} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12px] text-foreground/90">{item.name || "document"}</span>
                        <span className="block truncate text-[11px] text-muted-foreground">
                          {item.chars ? `${item.chars} chars` : item.mime || "document"}
                        </span>
                      </span>
                    </>
                  ) : (
                    <ChatImage
                      alt={item.name || ""}
                      className="size-full object-cover"
                      filename={item.name || ""}
                      lang={lang}
                      mime={item.mime || ""}
                      src={item.previewUrl || item.dataUrl}
                      wrapperClassName="size-full"
                    />
                  )}
                  {!busy && !uploading ? (
                    <button
                      type="button"
                      className="absolute right-1 top-1 z-10 grid size-5 place-items-center rounded-full bg-black/60 text-white/90 hover:bg-black/80"
                      aria-label={isDoc ? removeDocLabel || removeImageLabel : removeImageLabel}
                      title={isDoc ? removeDocLabel || removeImageLabel : removeImageLabel}
                      onClick={() => removeAttachment(item.id)}
                    >
                      <XIcon size={10} />
                    </button>
                  ) : null}
                </div>
              );
            })}
          </div>
        ) : null}
        <div className={`flex w-full gap-1.5 ${tall ? "items-end" : "items-center"}`}>
          <label
            htmlFor={attachInputId}
            className={`relative mb-0 grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition hover:bg-white/10 hover:text-foreground ${
              attachDisabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"
            } ${uploading ? "animate-pulse" : ""}`}
            aria-label={attachLabel}
            title={attachLabel}
            onClick={() => {
              if (attachDisabled) return;
              onPickerOpen?.();
            }}
          >
            <ImageIcon />
          </label>
          <label
            htmlFor={docInputId}
            className={`relative mb-0 grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition hover:bg-white/10 hover:text-foreground ${
              attachDisabled ? "cursor-not-allowed opacity-40" : "cursor-pointer"
            } ${uploading ? "animate-pulse" : ""}`}
            aria-label={attachDocLabel || "Attach document"}
            title={attachDocLabel || "Attach document"}
            onClick={() => {
              if (attachDisabled) return;
              onPickerOpen?.();
            }}
          >
            <DocumentIcon />
          </label>
          <textarea
            ref={ref}
            className="block max-h-40 min-h-6 w-full flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-6 text-foreground placeholder:text-muted-foreground/50"
            enterKeyHint="send"
            placeholder={placeholder}
            rows={1}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onPaste={(e) => {
              const files = Array.from(e.clipboardData?.files || []).filter((f) => f.type.startsWith("image/"));
              if (!files.length) return;
              e.preventDefault();
              addImageFiles(files);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (busy || !canSend) return;
                e.currentTarget.form?.requestSubmit();
              }
            }}
          />
          <ProviderQuickSettings
            capabilities={providerCapabilities}
            disabled={busy || uploading}
            lang={lang}
            model={providerModel}
            providerId={providerId}
            providerName={providerName}
            thinkingMode={thinkingMode}
            onModelChange={onProviderModelChange}
            onProviderChange={onProviderChange}
            onThinkingModeChange={onThinkingModeChange}
          />
          {busy ? (
            <button
              className="mb-0 grid size-8 shrink-0 place-items-center rounded-full bg-white text-black transition hover:opacity-90 active:scale-95"
              type="button"
              aria-label={stopLabel}
              title={stopLabel}
              onClick={onStop}
            >
              <StopIcon />
            </button>
          ) : (
            <button
              className="mb-0 grid size-8 shrink-0 place-items-center rounded-full bg-white text-black transition hover:opacity-90 active:scale-95 disabled:cursor-not-allowed disabled:bg-white/15 disabled:text-white/35"
              disabled={!canSend}
              type="submit"
            >
              <ArrowUpIcon />
            </button>
          )}
        </div>
        {attachError ? <div className="pb-1 text-[12px] text-amber-400/90">{attachError}</div> : null}
      </form>
    </div>
  );
}
