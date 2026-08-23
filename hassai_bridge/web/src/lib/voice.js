import { apiUrl, readError } from "./api.js";

// Google speech-to-text wants LINEAR16; 16 kHz mono is the sweet spot for
// speech and keeps a spoken command well under the upload limit.
const TARGET_RATE = 16000;
const MAX_SECONDS = 60;

export function micSupported() {
  return Boolean(
    typeof window !== "undefined" &&
      window.isSecureContext &&
      navigator.mediaDevices &&
      navigator.mediaDevices.getUserMedia,
  );
}

export function micBlockedReason() {
  if (typeof window === "undefined") return "unsupported";
  if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return "unsupported";
  if (!window.isSecureContext) return "insecure";
  return "";
}

function downsample(input, fromRate, toRate) {
  if (toRate >= fromRate) return input;
  const ratio = fromRate / toRate;
  const out = new Float32Array(Math.floor(input.length / ratio));
  let outIdx = 0;
  let inIdx = 0;
  while (outIdx < out.length) {
    const next = Math.round((outIdx + 1) * ratio);
    // Average the source window instead of picking one sample — avoids aliasing
    // that makes the transcript worse.
    let sum = 0;
    let count = 0;
    for (let i = inIdx; i < next && i < input.length; i += 1) {
      sum += input[i];
      count += 1;
    }
    out[outIdx] = count ? sum / count : 0;
    outIdx += 1;
    inIdx = next;
  }
  return out;
}

function encodeWav(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeText = (offset, text) => {
    for (let i = 0; i < text.length; i += 1) view.setUint8(offset + i, text.charCodeAt(i));
  };
  writeText(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeText(8, "WAVE");
  writeText(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeText(36, "data");
  view.setUint32(40, samples.length * 2, true);
  let offset = 44;
  for (let i = 0; i < samples.length; i += 1) {
    const clamped = Math.max(-1, Math.min(1, samples[i]));
    view.setInt16(offset, clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff, true);
    offset += 2;
  }
  return new Blob([view], { type: "audio/wav" });
}

/**
 * Start recording from the microphone.
 * Resolves to a handle with stop() → WAV blob, cancel(), and a live level.
 */
export async function startRecording({ onLevel } = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
  });
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const source = ctx.createMediaStreamSource(stream);
  const processor = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  let total = 0;
  let stopped = false;

  processor.onaudioprocess = (event) => {
    if (stopped) return;
    const data = event.inputBuffer.getChannelData(0);
    chunks.push(new Float32Array(data));
    total += data.length;
    if (onLevel) {
      let peak = 0;
      for (let i = 0; i < data.length; i += 64) peak = Math.max(peak, Math.abs(data[i]));
      onLevel(peak);
    }
    if (total / ctx.sampleRate > MAX_SECONDS) stopped = true;
  };

  source.connect(processor);
  // Safari will not run a ScriptProcessor that is not connected to a sink.
  const silent = ctx.createGain();
  silent.gain.value = 0;
  processor.connect(silent);
  silent.connect(ctx.destination);

  const teardown = () => {
    stopped = true;
    try {
      processor.disconnect();
      silent.disconnect();
      source.disconnect();
    } catch {
      /* already torn down */
    }
    stream.getTracks().forEach((track) => track.stop());
    ctx.close().catch(() => {});
  };

  return {
    cancel: teardown,
    async stop() {
      const rate = ctx.sampleRate;
      teardown();
      if (!total) return null;
      const merged = new Float32Array(total);
      let offset = 0;
      for (const chunk of chunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      const resampled = downsample(merged, rate, TARGET_RATE);
      if (resampled.length < TARGET_RATE * 0.25) return null; // < 0.25 s, a mis-tap
      return encodeWav(resampled, TARGET_RATE);
    },
  };
}

// ── Hands-free session ─────────────────────────────
//
// One long-lived microphone stream with energy-based voice activity detection.
// A fresh getUserMedia per turn would re-prompt on some browsers and add a
// noticeable gap, so the stream stays open and only capture is gated.

const VAD = {
  // Frames are ~85 ms at 4096 samples / 48 kHz.
  calibrationFrames: 8,
  // Speech must clear the measured noise floor by this factor.
  floorMultiplier: 2.5,
  minThreshold: 0.012,
  // Consecutive loud frames before we call it speech (kills keyboard clicks).
  startFrames: 2,
  // Silence before the turn is considered finished.
  silenceMs: 1100,
  // Keep a little audio from before the trigger so the first word survives.
  prerollFrames: 4,
  maxUtteranceMs: 30000,
  minUtteranceMs: 350,
  // Barge-in must be clearly louder — the mic also hears the reply.
  bargeInMultiplier: 4,
  bargeInFrames: 4,
};

function rms(frame) {
  let sum = 0;
  for (let i = 0; i < frame.length; i += 2) sum += frame[i] * frame[i];
  return Math.sqrt(sum / (frame.length / 2));
}

/**
 * Open the mic and emit one WAV blob per detected utterance.
 *
 * States: "idle" (waiting for speech) → "speech" (capturing) → emit → "idle".
 * While `setCapturing(false)` the stream keeps running so `onBargeIn` can fire
 * when the user talks over the assistant.
 */
export async function createVoiceSession({
  onUtterance,
  onSpeechStart,
  onLevel,
  onBargeIn,
  onError,
} = {}) {
  const stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      channelCount: 1,
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: true,
    },
  });
  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  const source = ctx.createMediaStreamSource(stream);
  const processor = ctx.createScriptProcessor(4096, 1, 1);

  let closed = false;
  let capturing = true;
  let noiseFloor = 0;
  let calibrated = 0;
  let loudRun = 0;
  let quietMs = 0;
  let speaking = false;
  let bargeRun = 0;
  const preroll = [];
  let captured = [];
  let capturedSamples = 0;

  const frameMs = (4096 / ctx.sampleRate) * 1000;

  const threshold = () => Math.max(VAD.minThreshold, noiseFloor * VAD.floorMultiplier);

  const finish = () => {
    const frames = captured;
    captured = [];
    capturedSamples = 0;
    speaking = false;
    quietMs = 0;
    loudRun = 0;
    if (!frames.length) return;
    const durationMs = (capturedSamplesOf(frames) / ctx.sampleRate) * 1000;
    if (durationMs < VAD.minUtteranceMs) return;
    const merged = mergeFrames(frames);
    const resampled = downsample(merged, ctx.sampleRate, TARGET_RATE);
    onUtterance?.(encodeWav(resampled, TARGET_RATE));
  };

  processor.onaudioprocess = (event) => {
    if (closed) return;
    const frame = new Float32Array(event.inputBuffer.getChannelData(0));
    const level = rms(frame);
    onLevel?.(level);

    if (calibrated < VAD.calibrationFrames) {
      noiseFloor = noiseFloor ? (noiseFloor * 3 + level) / 4 : level;
      calibrated += 1;
      return;
    }

    if (!capturing) {
      // Assistant is talking: only watch for the user cutting in.
      if (level > Math.max(VAD.minThreshold * 2, noiseFloor * VAD.bargeInMultiplier)) {
        bargeRun += 1;
        if (bargeRun >= VAD.bargeInFrames) {
          bargeRun = 0;
          onBargeIn?.();
        }
      } else {
        bargeRun = 0;
      }
      return;
    }

    const loud = level > threshold();

    if (!speaking) {
      // Track the room while it is quiet so the threshold follows the noise.
      if (!loud) noiseFloor = noiseFloor * 0.95 + level * 0.05;
      preroll.push(frame);
      if (preroll.length > VAD.prerollFrames) preroll.shift();
      loudRun = loud ? loudRun + 1 : 0;
      if (loudRun >= VAD.startFrames) {
        speaking = true;
        quietMs = 0;
        captured = preroll.splice(0, preroll.length);
        capturedSamples = capturedSamplesOf(captured);
        onSpeechStart?.();
      }
      return;
    }

    captured.push(frame);
    capturedSamples += frame.length;
    quietMs = loud ? 0 : quietMs + frameMs;
    if (quietMs >= VAD.silenceMs) {
      finish();
      return;
    }
    if ((capturedSamples / ctx.sampleRate) * 1000 >= VAD.maxUtteranceMs) finish();
  };

  source.connect(processor);
  const silent = ctx.createGain();
  silent.gain.value = 0;
  processor.connect(silent);
  silent.connect(ctx.destination);

  processor.onerror = () => onError?.(new Error("audio_pipeline"));

  return {
    setCapturing(value) {
      if (capturing === value) return;
      capturing = value;
      bargeRun = 0;
      loudRun = 0;
      quietMs = 0;
      speaking = false;
      captured = [];
      capturedSamples = 0;
      preroll.length = 0;
    },
    close() {
      if (closed) return;
      closed = true;
      try {
        processor.disconnect();
        silent.disconnect();
        source.disconnect();
      } catch {
        /* already torn down */
      }
      stream.getTracks().forEach((track) => track.stop());
      ctx.close().catch(() => {});
    },
  };
}

function capturedSamplesOf(frames) {
  let n = 0;
  for (const f of frames) n += f.length;
  return n;
}

function mergeFrames(frames) {
  const merged = new Float32Array(capturedSamplesOf(frames));
  let offset = 0;
  for (const f of frames) {
    merged.set(f, offset);
    offset += f.length;
  }
  return merged;
}

export async function transcribe(blob) {
  const form = new FormData();
  form.append("file", blob, "speech.wav");
  const resp = await fetch(apiUrl("/api/chat/voice/transcribe?sample_rate=16000"), {
    method: "POST",
    credentials: "same-origin",
    body: form,
  });
  if (!resp.ok) throw new Error(await readError(resp));
  const data = await resp.json();
  return String(data.text || "").trim();
}

export async function speak(text) {
  const resp = await fetch(apiUrl("/api/chat/voice/speak"), {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!resp.ok) throw new Error(await readError(resp));
  return resp.json();
}

let current = null;

export function playAudio(url) {
  stopAudio();
  const audio = new Audio(url);
  current = audio;
  const done = audio.play();
  if (done && typeof done.catch === "function") {
    // Autoplay can be refused until the user interacts with the page.
    done.catch(() => {});
  }
  return audio;
}

export function stopAudio() {
  if (!current) return;
  try {
    current.pause();
    current.currentTime = 0;
  } catch {
    /* nothing playing */
  }
  current = null;
}
