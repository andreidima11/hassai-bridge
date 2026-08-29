import { useCallback, useEffect, useRef, useState } from "react";
import { MicIcon, XIcon } from "./Icons.jsx";
import { tr } from "../lib/i18n.js";
import { createVoiceSession, micBlockedReason, transcribe } from "../lib/voice.js";

/**
 * Hands-free conversation overlay.
 *
 * listening → (speech detected) recording → transcribing → thinking → speaking → listening
 *
 * The parent owns the chat turn: we hand it a transcript and it hands back a
 * phase plus the audio to play.
 */
export function VoiceMode({ lang, phase, replyAudioUrl, error, onUtterance, onSpokenEnd, onClose }) {
  const sessionRef = useRef(null);
  const audioRef = useRef(null);
  const [micPhase, setMicPhase] = useState("starting");
  const [level, setLevel] = useState(0);
  const [localError, setLocalError] = useState("");

  const stopPlayback = useCallback(() => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.pause();
    audio.currentTime = 0;
    audioRef.current = null;
  }, []);

  // ── Microphone session lives for the whole overlay ──
  useEffect(() => {
    let cancelled = false;
    const blocked = micBlockedReason();
    if (blocked) {
      setLocalError(tr(lang, blocked === "insecure" ? "voiceNeedsHttps" : "voiceUnsupported"));
      setMicPhase("error");
      return undefined;
    }

    (async () => {
      try {
        const session = await createVoiceSession({
          onLevel: (value) => !cancelled && setLevel(value),
          onSpeechStart: () => !cancelled && setMicPhase("recording"),
          onBargeIn: () => {
            // User talked over the reply — drop it and listen again.
            stopPlayback();
            onSpokenEnd?.();
          },
          onError: (err) => {
            if (cancelled) return;
            setLocalError(String(err?.message || err) || tr(lang, "voiceFailed"));
            setMicPhase("error");
          },
          onUtterance: async (blob) => {
            if (cancelled) return;
            setMicPhase("transcribing");
            session.setCapturing(false);
            try {
              const text = await transcribe(blob);
              if (cancelled) return;
              if (!text) {
                session.setCapturing(true);
                setMicPhase("listening");
                return;
              }
              onUtterance?.(text);
            } catch (err) {
              if (cancelled) return;
              setLocalError(String(err?.message || err));
              session.setCapturing(true);
              setMicPhase("listening");
            }
          },
        });
        if (cancelled) {
          session.close();
          return;
        }
        await session.resume?.();
        sessionRef.current = session;
        setMicPhase("listening");
      } catch {
        if (!cancelled) {
          setLocalError(tr(lang, "voiceNoPermission"));
          setMicPhase("error");
        }
      }
    })();

    return () => {
      cancelled = true;
      sessionRef.current?.close();
      sessionRef.current = null;
      stopPlayback();
    };
  }, [lang, onUtterance, onSpokenEnd, stopPlayback]);

  // ── Play the reply, then hand the mic back ──
  useEffect(() => {
    if (!replyAudioUrl) return undefined;
    const audio = new Audio(replyAudioUrl);
    audioRef.current = audio;
    const done = () => {
      audioRef.current = null;
      onSpokenEnd?.();
    };
    audio.onended = done;
    audio.onerror = done;
    audio.play().catch(done);
    return () => {
      audio.pause();
    };
  }, [replyAudioUrl, onSpokenEnd]);

  // The parent is ready for the next question — clear the per-turn mic state.
  useEffect(() => {
    if (phase !== "listening") return;
    setMicPhase((p) => (p === "starting" || p === "error" ? p : "listening"));
  }, [phase]);

  // Capture only while both sides are waiting for the user to talk.
  useEffect(() => {
    sessionRef.current?.setCapturing(
      phase === "listening" && (micPhase === "listening" || micPhase === "recording"),
    );
  }, [phase, micPhase]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.key === "Escape") onClose?.();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const state = (() => {
    if (micPhase === "error") return "error";
    if (micPhase === "starting") return "starting";
    if (phase === "thinking") return "thinking";
    if (phase === "speaking") return "speaking";
    if (micPhase === "transcribing") return "transcribing";
    if (micPhase === "recording") return "recording";
    return "listening";
  })();

  const statusLabel = tr(lang, {
    starting: "voiceModeStarting",
    listening: "voiceModeListening",
    recording: "voiceModeRecording",
    transcribing: "voiceModeTranscribing",
    thinking: "voiceModeThinking",
    speaking: "voiceModeSpeaking",
    error: "voiceModeError",
  }[state]);

  // Cap the growth so a loud room does not blow the orb off screen.
  const scale = state === "recording" ? 1 + Math.min(level * 4, 0.6) : 1;
  const shown = localError || error;

  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center gap-8 bg-background/95 backdrop-blur-sm">
      <button
        type="button"
        className="absolute right-4 top-[max(1rem,env(safe-area-inset-top))] grid size-10 place-items-center rounded-full text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
        aria-label={tr(lang, "voiceModeClose")}
        title={tr(lang, "voiceModeClose")}
        onClick={onClose}
      >
        <XIcon />
      </button>

      <div className="relative grid place-items-center">
        <div
          className={`absolute size-44 rounded-full transition-transform duration-100 ${
            state === "recording"
              ? "bg-emerald-400/20"
              : state === "speaking"
                ? "bg-sky-400/20 animate-pulse"
                : state === "thinking" || state === "transcribing"
                  ? "bg-white/10 animate-pulse"
                  : state === "error"
                    ? "bg-amber-400/20"
                    : "bg-white/5"
          }`}
          style={{ transform: `scale(${scale})` }}
        />
        <div
          className={`grid size-28 place-items-center rounded-full border ${
            state === "recording"
              ? "border-emerald-400/60 text-emerald-300"
              : state === "speaking"
                ? "border-sky-400/60 text-sky-300"
                : state === "error"
                  ? "border-amber-400/60 text-amber-300"
                  : "border-white/15 text-muted-foreground"
          }`}
        >
          <span className="scale-[2.2]">
            <MicIcon />
          </span>
        </div>
      </div>

      <div className="flex max-w-sm flex-col items-center gap-2 px-6 text-center">
        <div className="text-[15px] text-foreground">{statusLabel}</div>
        {shown ? (
          <div className="text-[13px] text-amber-400/90">{shown}</div>
        ) : (
          <div className="text-[13px] text-muted-foreground">{tr(lang, "voiceModeHint")}</div>
        )}
      </div>

      <button
        type="button"
        className="rounded-full border border-white/15 px-5 py-2 text-[14px] text-muted-foreground transition hover:bg-white/10 hover:text-foreground"
        onClick={onClose}
      >
        {tr(lang, "voiceModeEnd")}
      </button>
    </div>
  );
}
