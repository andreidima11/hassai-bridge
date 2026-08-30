import { useEffect, useRef, useState } from "react";
import { AttachMenu } from "./AttachMenu.jsx";
import { ChatImage } from "./ChatImage.jsx";
import { HaFileBrowser } from "./HaFileBrowser.jsx";
import { ArrowUpIcon, DocumentIcon, MicIcon, PlusIcon, StopIcon, WaveformIcon, XIcon } from "./Icons.jsx";
import { micBlockedReason, micSupported, startRecording, transcribe, unlockPlayback } from "../lib/voice.js";
import {
  documentAcceptAttr,
  isDocumentAttachment,
  isHaCompanionApp,
  looksLikeImage,
  MAX_CHAT_ATTACHMENTS,
  prepareDocumentFile,
  prepareImageFile,
} from "../lib/images.js";
import { tr } from "../lib/i18n.js";
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
  providerAuto = false,
  providerCapabilities = {},
  thinkingMode = "auto",
  onThinkingModeChange,
  onProviderModelChange,
  onProviderChange,
  lang = "en",
  onPickerOpen,
  onPickerSettled,
  voiceEnabled = false,
  voiceControls = "both",
  voiceSpeaks = true,
  onVoiceTranscript,
  onVoiceModeOpen,
}) {
  const ref = useRef(null);
  const processingRef = useRef(false);
  const recorderRef = useRef(null);
  const [tall, setTall] = useState(false);
  const [attachError, setAttachError] = useState("");
  const [uploading, setUploading] = useState(false);
  const [browseKind, setBrowseKind] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const companionApp = isHaCompanionApp();
  const micOk = voiceEnabled && micSupported();
  const controls = voiceControls === "mic" || voiceControls === "conversation" ? voiceControls : "both";
  // Hands-free has to speak back, so it needs a working text-to-speech engine.
  const showConversation = micOk && voiceSpeaks && (controls === "both" || controls === "conversation");
  const showMic = micOk && (controls === "both" || controls === "mic");

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

  useEffect(() => () => recorderRef.current?.cancel(), []);

  const startingRef = useRef(false);

  const toggleRecording = async () => {
    if (transcribing || startingRef.current) return;
    if (recording) {
      const handle = recorderRef.current;
      recorderRef.current = null;
      setRecording(false);
      if (!handle) return;
      setTranscribing(true);
      try {
        const blob = await handle.stop();
        if (!blob) {
          setAttachError(tr(lang, "voiceTooShort"));
          return;
        }
        const text = await transcribe(blob);
        if (!text) {
          setAttachError(tr(lang, "voiceNothingHeard"));
          return;
        }
        setAttachError("");
        onVoiceTranscript?.(text);
      } catch (err) {
        setAttachError(String(err?.message || err) || tr(lang, "voiceFailed"));
      } finally {
        setTranscribing(false);
      }
      return;
    }
    const blocked = micBlockedReason();
    if (blocked) {
      setAttachError(tr(lang, blocked === "insecure" ? "voiceNeedsHttps" : "voiceUnsupported"));
      return;
    }
    startingRef.current = true;
    // iOS Companion: unlock TTS on this tap so the reply can play after STT+chat.
    unlockPlayback();
    // Drop any orphaned previous handle (double-tap race).
    recorderRef.current?.cancel();
    recorderRef.current = null;
    try {
      const handle = await startRecording({
        onDead: () => {
          if (recorderRef.current !== handle) return;
          handle.cancel();
          recorderRef.current = null;
          setRecording(false);
          setAttachError(tr(lang, "voiceFailed"));
        },
      });
      // Tap again while getUserMedia was pending — discard this stream.
      if (!startingRef.current) {
        handle.cancel();
        return;
      }
      await handle.resume?.();
      recorderRef.current = handle;
      setAttachError("");
      setRecording(true);
    } catch {
      setAttachError(tr(lang, "voiceNoPermission"));
    } finally {
      startingRef.current = false;
    }
  };

  const addDocFiles = (files) =>
    addPrepared(files, prepareDocumentFile, {
      tooLarge: docTooLargeLabel || imageTooLargeLabel,
      unsupported: unsupportedDocLabel || unsupportedImageLabel,
    });

  const handleFileInput = async (event, kind) => {
    if (processingRef.current) return;
    const input = event.target;
    const picked = Array.from(input.files || []);
    if (!picked.length) {
      finishPicking();
      input.value = "";
      return;
    }
    processingRef.current = true;
    try {
      // The Companion picker uses a broad accept list, so trust the file, not the button.
      const images = picked.filter((file) => looksLikeImage(file));
      const docs = picked.filter((file) => !looksLikeImage(file));
      if (kind === "document" && !images.length) await addDocFiles(picked);
      else if (kind === "image" && !docs.length) await addImageFiles(picked);
      else {
        if (images.length) await addImageFiles(images);
        if (docs.length) await addDocFiles(docs);
      }
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

  const addAttachment = (attachment) => {
    if (!attachment || !onAttachmentsChange) return;
    onAttachmentsChange((current) => {
      const base = current || [];
      if (base.length >= MAX_CHAT_ATTACHMENTS) return base;
      return [...base, attachment];
    });
  };


  return (
    <div className="sticky bottom-0 z-[1] mx-auto flex w-full max-w-4xl flex-col bg-background px-3 pb-3 md:px-4 md:pb-4">
      {menuOpen ? (
        <AttachMenu
          // A long MIME list makes the Companion WebView open a separate file-manager app,
          // which tears down the Ingress panel; a plain wildcard keeps the in-app chooser.
          docAccept={companionApp ? "*/*" : documentAcceptAttr()}
          lang={lang}
          multiple={!companionApp}
          onBrowseHa={() => {
            setMenuOpen(false);
            setBrowseKind("any");
          }}
          onClose={() => setMenuOpen(false)}
          onFiles={async (event, kind) => {
            setMenuOpen(false);
            await handleFileInput(event, kind);
          }}
          onPickerOpen={() => onPickerOpen?.()}
        />
      ) : null}
      {browseKind ? (
        <HaFileBrowser
          kind={browseKind === "any" ? "" : browseKind}
          lang={lang}
          onAttached={addAttachment}
          onClose={() => setBrowseKind("")}
        />
      ) : null}
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
          <button
            type="button"
            className={`mb-0 grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition hover:bg-white/10 hover:text-foreground ${
              attachDisabled ? "cursor-not-allowed opacity-40" : ""
            } ${uploading ? "animate-pulse" : ""}`}
            aria-label={tr(lang, "attachTitle")}
            disabled={attachDisabled}
            title={tr(lang, "attachTitle")}
            onClick={() => setMenuOpen(true)}
          >
            <PlusIcon />
          </button>
          <textarea
            ref={ref}
            className="block max-h-40 min-h-6 w-full min-w-0 flex-1 resize-none bg-transparent py-1.5 text-[15px] leading-6 text-foreground placeholder:text-muted-foreground/50"
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
          {showConversation ? (
            <button
              type="button"
              className="mb-0 grid size-8 shrink-0 place-items-center rounded-full text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
              aria-label={tr(lang, "voiceModeStart")}
              disabled={busy || uploading || recording || transcribing}
              title={tr(lang, "voiceModeStart")}
              onClick={() => onVoiceModeOpen?.()}
            >
              <WaveformIcon />
            </button>
          ) : null}
          {showMic ? (
            <button
              type="button"
              className={`mb-0 grid size-8 shrink-0 place-items-center rounded-full transition ${
                recording
                  ? "bg-red-500/90 text-white animate-pulse"
                  : "text-muted-foreground hover:bg-white/10 hover:text-foreground"
              } ${transcribing ? "animate-pulse opacity-60" : ""}`}
              aria-label={tr(lang, recording ? "voiceStop" : "voiceStart")}
              aria-pressed={recording}
              disabled={busy || uploading || transcribing}
              title={tr(lang, recording ? "voiceStop" : "voiceStart")}
              onClick={toggleRecording}
            >
              <MicIcon />
            </button>
          ) : null}
          <ProviderQuickSettings
            auto={providerAuto}
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
