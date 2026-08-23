"""Local speech engines — Wyoming (Whisper / Piper) plus OpenAI-compatible HTTP.

Home Assistant ships Whisper and Piper as add-ons that speak the Wyoming
protocol on plain TCP (`core_whisper:10300`, `core_piper:10200`), so that is the
default path and needs no extra dependency: Wyoming is newline-delimited JSON
headers followed by optional data and payload bytes.

Anything served over http(s) is treated as an OpenAI-compatible speech server
(`/v1/audio/transcriptions`, `/v1/audio/speech`), which covers speaches,
faster-whisper-server, openedai-speech and friends.

STT and TTS are resolved independently, so Whisper can transcribe while Google
speaks the reply, or the other way around.
"""

from __future__ import annotations

import asyncio
import json
import logging
import struct

import httpx

# One error type for the whole voice layer so routers keep a single except.
from services.google_voice import VoiceError

log = logging.getLogger("hassai.voice.local")

DEFAULT_STT_URL = "core_whisper:10300"
DEFAULT_TTS_URL = "core_piper:10200"
DEFAULT_STT_PORT = 10300
DEFAULT_TTS_PORT = 10200

CONNECT_TIMEOUT = 10.0
DEFAULT_TIMEOUT = 60.0
# Wyoming servers expect modest audio chunks rather than one huge frame.
_CHUNK_BYTES = 8192
_MAX_AUDIO_BYTES = 20_000_000


# ── Endpoint parsing ───────────────────────────────

def parse_endpoint(url: str, default_port: int) -> tuple[str, str, int]:
    """Return ("http", url, 0) or ("wyoming", host, port).

    Bare `host` / `host:port` / `tcp://host:port` all mean Wyoming, which is what
    the Home Assistant Whisper and Piper add-ons expose.
    """
    raw = str(url or "").strip()
    if not raw:
        raise VoiceError("No local speech server URL configured.")
    low = raw.lower()
    if low.startswith(("http://", "https://")):
        return "http", raw.rstrip("/"), 0
    if low.startswith("tcp://"):
        raw = raw[6:]
    raw = raw.strip("/")
    host, _, port_txt = raw.partition(":")
    host = host.strip()
    if not host:
        raise VoiceError(f"Could not read a host from '{url}'.")
    try:
        port = int(port_txt) if port_txt else default_port
    except ValueError as exc:
        raise VoiceError(f"Invalid port in '{url}'.") from exc
    return "wyoming", host, port


def short_language(language: str) -> str:
    """Whisper and Piper want `ro`, not `ro-RO`."""
    return str(language or "").strip().replace("_", "-").split("-", 1)[0].lower()


# ── WAV helpers ────────────────────────────────────

def wav_from_pcm(pcm: bytes, rate: int = 22050, width: int = 2, channels: int = 1) -> bytes:
    rate = int(rate or 22050)
    width = int(width or 2)
    channels = int(channels or 1)
    block = width * channels
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, channels, rate, rate * block, block, width * 8)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


# ── Wyoming wire format ────────────────────────────

async def _write_event(writer, event_type: str, data: dict | None = None, payload: bytes = b"") -> None:
    header: dict = {"type": event_type}
    data_bytes = b""
    if data is not None:
        data_bytes = json.dumps(data, ensure_ascii=False).encode("utf-8")
        header["data_length"] = len(data_bytes)
    if payload:
        header["payload_length"] = len(payload)
    writer.write(json.dumps(header, ensure_ascii=False).encode("utf-8") + b"\n")
    if data_bytes:
        writer.write(data_bytes)
    if payload:
        writer.write(payload)
    await writer.drain()


async def _read_event(reader) -> tuple[str, dict, bytes] | None:
    line = await reader.readline()
    if not line:
        return None
    try:
        header = json.loads(line)
    except ValueError as exc:
        raise VoiceError(f"Local speech server sent a malformed event: {exc}") from exc
    data = header.get("data") or {}
    data_length = header.get("data_length")
    if data_length:
        data = json.loads(await reader.readexactly(int(data_length)))
    payload = b""
    payload_length = header.get("payload_length")
    if payload_length:
        payload = await reader.readexactly(int(payload_length))
    return str(header.get("type") or ""), (data if isinstance(data, dict) else {}), payload


async def _connect(host: str, port: int):
    try:
        return await asyncio.wait_for(asyncio.open_connection(host, port), timeout=CONNECT_TIMEOUT)
    except asyncio.TimeoutError as exc:
        raise VoiceError(f"Timed out connecting to {host}:{port}.") from exc
    except OSError as exc:
        raise VoiceError(f"Could not reach {host}:{port} — {exc}") from exc


async def _close(writer) -> None:
    try:
        writer.close()
        await writer.wait_closed()
    except Exception:  # pragma: no cover - best effort
        pass


# ── Wyoming: describe ──────────────────────────────

async def _wyoming_info(host: str, port: int, timeout: float) -> dict:
    reader, writer = await _connect(host, port)
    try:
        await _write_event(writer, "describe", {})
        while True:
            event = await asyncio.wait_for(_read_event(reader), timeout=timeout)
            if event is None:
                raise VoiceError(f"{host}:{port} closed the connection without describing itself.")
            event_type, data, _ = event
            if event_type == "info":
                return data
    except asyncio.TimeoutError as exc:
        raise VoiceError(f"{host}:{port} did not answer in time.") from exc
    finally:
        await _close(writer)


async def describe(url: str, kind: str = "tts", timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Ask a Wyoming server what it is and which voices/models it has."""
    default_port = DEFAULT_STT_PORT if kind == "stt" else DEFAULT_TTS_PORT
    mode, host, port = parse_endpoint(url, default_port)
    if mode == "http":
        raise VoiceError("Only Wyoming servers can be described; HTTP servers have no describe call.")
    return await _wyoming_info(host, port, timeout)


def voices_from_info(info: dict) -> list[dict]:
    """Flatten a Wyoming `info` event into a Piper voice picker list."""
    out: list[dict] = []
    for program in info.get("tts") or []:
        for voice in program.get("voices") or []:
            name = str(voice.get("name") or "").strip()
            if not name:
                continue
            languages = [str(x) for x in (voice.get("languages") or []) if x]
            speakers = [
                str(s.get("name") or "").strip()
                for s in (voice.get("speaker_id_map") or voice.get("speakers") or [])
                if isinstance(s, dict) and s.get("name")
            ]
            out.append({
                "id": name,
                "speaker": name,
                "language": languages[0] if languages else "",
                "description": str(voice.get("description") or ""),
                "speakers": speakers,
            })
    out.sort(key=lambda v: (v.get("language") or "", v["id"]))
    return out


def models_from_info(info: dict) -> list[str]:
    """Whisper model names advertised by a Wyoming ASR server."""
    out: list[str] = []
    for program in info.get("asr") or []:
        for model in program.get("models") or []:
            name = str(model.get("name") or "").strip()
            if name:
                out.append(name)
    return out


# ── Speech to text ─────────────────────────────────

async def _wyoming_transcribe(
    host: str, port: int, pcm: bytes, rate: int, language: str, model: str, timeout: float
) -> str:
    reader, writer = await _connect(host, port)
    try:
        request: dict = {}
        if language:
            request["language"] = language
        if model:
            request["name"] = model
        await _write_event(writer, "transcribe", request)

        audio_meta = {"rate": int(rate), "width": 2, "channels": 1}
        await _write_event(writer, "audio-start", {**audio_meta, "timestamp": 0})
        for offset in range(0, len(pcm), _CHUNK_BYTES):
            chunk = pcm[offset:offset + _CHUNK_BYTES]
            await _write_event(writer, "audio-chunk", audio_meta, chunk)
        await _write_event(writer, "audio-stop", {"timestamp": len(pcm)})

        while True:
            event = await asyncio.wait_for(_read_event(reader), timeout=timeout)
            if event is None:
                raise VoiceError(f"{host}:{port} closed the connection before answering.")
            event_type, data, _ = event
            if event_type == "transcript":
                return str(data.get("text") or "").strip()
            if event_type == "error":
                raise VoiceError(f"Whisper returned an error: {data.get('text') or data}")
    except asyncio.TimeoutError as exc:
        raise VoiceError(
            f"Whisper at {host}:{port} did not transcribe in {int(timeout)}s. "
            "A larger model on CPU can be slow — raise the timeout or pick a smaller model."
        ) from exc
    finally:
        await _close(writer)


async def _http_transcribe(base: str, wav: bytes, language: str, model: str, timeout: float) -> str:
    url = base if "/audio/" in base else f"{base}/v1/audio/transcriptions"
    files = {"file": ("speech.wav", wav, "audio/wav")}
    form = {"model": model or "whisper-1"}
    if language:
        form["language"] = language
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, files=files, data=form)
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach the speech-to-text server at {url} — {exc}") from exc
    if resp.status_code >= 400:
        raise VoiceError(f"Speech-to-text server returned HTTP {resp.status_code}: {resp.text[:300]}")
    try:
        return str(resp.json().get("text") or "").strip()
    except ValueError:
        return resp.text.strip()


async def transcribe(
    url: str,
    wav: bytes,
    pcm: bytes,
    *,
    sample_rate: int = 16000,
    language: str = "",
    model: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> str:
    """Recorded audio → text via Whisper (Wyoming) or an HTTP speech server."""
    if not pcm and not wav:
        raise VoiceError("No audio recorded.")
    if len(wav or pcm) > _MAX_AUDIO_BYTES:
        raise VoiceError("Recording is too long for the local speech server.")
    mode, host, port = parse_endpoint(url, DEFAULT_STT_PORT)
    lang = short_language(language)
    if mode == "http":
        return await _http_transcribe(host, wav or pcm, lang, model, timeout)
    return await _wyoming_transcribe(host, port, pcm or wav, sample_rate, lang, model, timeout)


# ── Text to speech ─────────────────────────────────

async def _wyoming_synthesize(
    host: str, port: int, text: str, voice: str, speaker: str, timeout: float
) -> tuple[bytes, str]:
    reader, writer = await _connect(host, port)
    try:
        request: dict = {"text": text}
        if voice:
            voice_data: dict = {"name": voice}
            if speaker:
                voice_data["speaker"] = speaker
            request["voice"] = voice_data
        await _write_event(writer, "synthesize", request)

        rate, width, channels = 22050, 2, 1
        chunks: list[bytes] = []
        while True:
            event = await asyncio.wait_for(_read_event(reader), timeout=timeout)
            if event is None:
                raise VoiceError(f"{host}:{port} closed the connection before speaking.")
            event_type, data, payload = event
            if event_type == "audio-start":
                rate = int(data.get("rate") or rate)
                width = int(data.get("width") or width)
                channels = int(data.get("channels") or channels)
            elif event_type == "audio-chunk":
                if payload:
                    chunks.append(payload)
                rate = int(data.get("rate") or rate)
                width = int(data.get("width") or width)
                channels = int(data.get("channels") or channels)
            elif event_type == "audio-stop":
                break
            elif event_type == "error":
                raise VoiceError(f"Piper returned an error: {data.get('text') or data}")
        pcm = b"".join(chunks)
        if not pcm:
            raise VoiceError("Piper returned no audio.")
        return wav_from_pcm(pcm, rate, width, channels), "audio/wav"
    except asyncio.TimeoutError as exc:
        raise VoiceError(f"Piper at {host}:{port} did not answer in {int(timeout)}s.") from exc
    finally:
        await _close(writer)


async def _http_synthesize(base: str, text: str, voice: str, model: str, timeout: float) -> tuple[bytes, str]:
    url = base if "/audio/" in base else f"{base}/v1/audio/speech"
    payload = {
        "model": model or "tts-1",
        "input": text,
        "voice": voice or "alloy",
        "response_format": "mp3",
    }
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise VoiceError(f"Could not reach the text-to-speech server at {url} — {exc}") from exc
    if resp.status_code >= 400:
        raise VoiceError(f"Text-to-speech server returned HTTP {resp.status_code}: {resp.text[:300]}")
    audio = resp.content
    if not audio:
        raise VoiceError("The text-to-speech server returned no audio.")
    mime = (resp.headers.get("content-type") or "audio/mpeg").split(";", 1)[0].strip().lower()
    if not mime.startswith("audio/"):
        mime = "audio/mpeg"
    return audio, mime


async def synthesize(
    url: str,
    text: str,
    *,
    voice: str = "",
    speaker: str = "",
    model: str = "",
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[bytes, str]:
    """Text → (audio bytes, mime) via Piper (Wyoming) or an HTTP speech server."""
    clean = " ".join(str(text or "").split())
    if not clean:
        raise VoiceError("Nothing to speak.")
    mode, host, port = parse_endpoint(url, DEFAULT_TTS_PORT)
    if mode == "http":
        return await _http_synthesize(host, clean, voice, model, timeout)
    return await _wyoming_synthesize(host, port, clean, voice, speaker, timeout)
