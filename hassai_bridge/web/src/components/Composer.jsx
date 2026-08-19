import { useEffect, useRef, useState } from "react";
import { ArrowUpIcon, ImageIcon, StopIcon, XIcon } from "./Icons.jsx";
import { MAX_CHAT_IMAGES, prepareImageFile } from "../lib/images.js";
import { ThinkingMode } from "./ThinkingMode.jsx";

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
  removeImageLabel,
  imageTooLargeLabel,
  maxImagesLabel,
  unsupportedImageLabel,
  showThinking = false,
  thinkingMode = "auto",
  onThinkingModeChange,
  lang = "en",
  onPickerOpen,
  onPickerSettled,
}) {
  const ref = useRef(null);
  const fileRef = useRef(null);
  const [tall, setTall] = useState(false);
  const [attachError, setAttachError] = useState("");

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "0px";
    const next = Math.min(Math.max(el.scrollHeight, 24), 160);
    el.style.height = `${next}px`;
    setTall(next > 28 || (attachments?.length || 0) > 0);
  }, [value, attachments]);

  const canSend = Boolean(value.trim()) || (attachments?.length || 0) > 0;

  const addFiles = async (files) => {
    if (!files?.length || !onAttachmentsChange) return;
    setAttachError("");
    let added = 0;
    for (const file of files) {
      try {
        const prepared = await prepareImageFile(file);
        onAttachmentsChange((current) => {
          const base = current || [];
          if (base.length >= MAX_CHAT_IMAGES) return base;
          return [...base, prepared];
        });
        added += 1;
      } catch (err) {
        const code = String(err?.message || "");
        if (code === "too_large") setAttachError(imageTooLargeLabel);
        else if (code === "unsupported") setAttachError(unsupportedImageLabel);
        else setAttachError(unsupportedImageLabel);
      }
    }
    if (added >= MAX_CHAT_IMAGES) setAttachError(maxImagesLabel);
    onPickerSettled?.();
  };

  const removeAttachment = (id) => {
    if (!onAttachmentsChange) return;
    onAttachmentsChange((attachments || []).filter((item) => item.id !== id));
    setAttachError("");
  };

  return (
    <div className="sticky bottom-0 z-[1] mx-auto flex w-full max-w-4xl flex-col bg-background px-3 pb-3 md:px-4 md:pb-4">
      <form
        className={`flex w-full flex-col gap-2 overflow-hidden border border-white/[0.08] bg-composer px-3 shadow-composer transition-[border-radius] duration-200 focus-within:border-white/15 ${
          tall ? "rounded-3xl py-2" : "rounded-full py-1"
        }`}
        onSubmit={onSubmit}
      >
        {attachments?.length ? (
          <div className="flex flex-wrap gap-2 pt-1">
            {attachments.map((item) => (
              <div key={item.id} className="relative size-16 overflow-hidden rounded-xl border border-white/10 bg-black/20">
                <img alt="" className="size-full object-cover" src={item.previewUrl || item.dataUrl} />
                {!busy ? (
                  <button
                    type="button"
                    className="absolute right-1 top-1 grid size-5 place-items-center rounded-full bg-black/60 text-white/90 hover:bg-black/80"
                    aria-label={removeImageLabel}
                    title={removeImageLabel}
                    onClick={() => removeAttachment(item.id)}
                  >
                    <XIcon size={10} />
                  </button>
                ) : null}
              </div>
            ))}
          </div>
        ) : null}
        <div className={`flex w-full gap-2 ${tall ? "items-end" : "items-center"}`}>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,image/webp,image/gif,image/heic,image/heif,.heic,.heif"
            multiple
            className="hidden"
            onChange={(e) => {
              const picked = Array.from(e.target.files || []);
              e.target.value = "";
              if (picked.length) addFiles(picked);
              else onPickerSettled?.();
            }}
          />
          <button
            type="button"
            className="mb-0 grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition hover:bg-white/10 hover:text-foreground disabled:cursor-not-allowed disabled:opacity-40"
            aria-label={attachLabel}
            title={attachLabel}
            disabled={busy || (attachments?.length || 0) >= MAX_CHAT_IMAGES}
            onClick={() => {
              onPickerOpen?.();
              fileRef.current?.click();
            }}
          >
            <ImageIcon />
          </button>
          {showThinking ? (
            <ThinkingMode
              disabled={busy}
              lang={lang}
              mode={thinkingMode}
              onChange={onThinkingModeChange}
            />
          ) : null}
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
              addFiles(files);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (busy || !canSend) return;
                e.currentTarget.form?.requestSubmit();
              }
            }}
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
