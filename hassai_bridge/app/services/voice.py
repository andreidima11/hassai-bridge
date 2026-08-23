"""Voice layer: config resolution plus speak/transcribe on top of a backend.

Speech-to-text and text-to-speech are chosen independently, so Google Chirp 3:
HD and a local Whisper/Piper server can be mixed in either direction — local
Whisper for the microphone with a Google voice for the reply, or the reverse.
"""

from __future__ import annotations

import logging
import re

from config import load_config
from services import chat_media as cm
from services import google_voice as gv
from services import local_voice as lv

log = logging.getLogger("hassai.voice")

DEFAULT_MAX_REPLY_CHARS = 800
# What the chat composer shows when voice is enabled.
VOICE_CONTROLS = frozenset({"both", "mic", "conversation"})
# Where speech is processed: Google's cloud API or a local Whisper/Piper server.
SPEECH_ENGINES = frozenset({"google", "local"})

# Markdown / decorations that should not be read out loud.
_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`([^`]*)`")
_IMAGE_MD = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_MD = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s*", re.MULTILINE)
_BULLET = re.compile(r"^\s{0,3}[-*+]\s+", re.MULTILINE)
_EMPHASIS = re.compile(r"(\*\*|__|\*|_|~~)")
_HR = re.compile(r"^\s*([-*_]\s*){3,}$", re.MULTILINE)
_EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2190-\u21FF\u2B00-\u2BFF]"
)
# Chirp (and most TTS) spells ALL-CAPS brands letter by letter. Speak the name
# as a word instead of "H A S S A I".
_BRAND_SAY = re.compile(r"\bHASSAI\b", re.IGNORECASE)
_BRAND_SPOKEN = "Hassai"


def _engine(raw: dict, key: str) -> str:
    value = str(raw.get(key) or "").strip().lower()
    return value if value in SPEECH_ENGINES else "google"


def _local_section(raw: dict, key: str, default_url: str) -> dict:
    section = raw.get(key) if isinstance(raw.get(key), dict) else {}
    try:
        timeout = float(section.get("timeout", lv.DEFAULT_TIMEOUT))
    except (TypeError, ValueError):
        timeout = lv.DEFAULT_TIMEOUT
    # An absent URL means "never configured" and falls back to the Home Assistant
    # add-on address; an empty one means the user cleared it on purpose.
    raw_url = section.get("url")
    return {
        "url": str(default_url if raw_url is None else raw_url).strip(),
        "model": str(section.get("model") or "").strip(),
        "voice": str(section.get("voice") or "").strip(),
        "speaker": str(section.get("speaker") or "").strip(),
        "timeout": max(5.0, min(600.0, timeout)),
    }


def settings(cfg: dict | None = None) -> dict:
    if cfg is None:
        cfg = load_config()
    raw = cfg.get("voice") if isinstance(cfg.get("voice"), dict) else {}
    try:
        rate = float(raw.get("speaking_rate", 1.0))
    except (TypeError, ValueError):
        rate = 1.0
    try:
        max_chars = int(raw.get("max_reply_chars", DEFAULT_MAX_REPLY_CHARS))
    except (TypeError, ValueError):
        max_chars = DEFAULT_MAX_REPLY_CHARS
    controls = str(raw.get("controls") or "both").strip().lower()
    if controls not in VOICE_CONTROLS:
        controls = "both"
    return {
        "enabled": bool(raw.get("enabled")),
        "provider": str(raw.get("provider") or "google"),
        "stt_engine": _engine(raw, "stt_engine"),
        "tts_engine": _engine(raw, "tts_engine"),
        "google_api_key": str(raw.get("google_api_key") or "").strip(),
        "language": str(raw.get("language") or gv.DEFAULT_LANGUAGE),
        "voice": str(raw.get("voice") or gv.DEFAULT_VOICE),
        "speaking_rate": max(0.25, min(2.0, rate)),
        "autoplay": raw.get("autoplay") is not False,
        "max_reply_chars": max(100, min(gv.MAX_TTS_CHARS, max_chars)),
        "controls": controls,
        "local_stt": _local_section(raw, "local_stt", lv.DEFAULT_STT_URL),
        "local_tts": _local_section(raw, "local_tts", lv.DEFAULT_TTS_URL),
    }


def stt_ready(conf: dict) -> bool:
    """Can the microphone produce text with the current settings?"""
    if conf["stt_engine"] == "local":
        return bool(conf["local_stt"]["url"])
    return bool(conf["google_api_key"])


def tts_ready(conf: dict) -> bool:
    """Can a reply be spoken with the current settings?"""
    if conf["tts_engine"] == "local":
        return bool(conf["local_tts"]["url"])
    return bool(conf["google_api_key"])


def is_configured(cfg: dict | None = None) -> bool:
    conf = settings(cfg)
    return bool(conf["enabled"] and (stt_ready(conf) or tts_ready(conf)))


def public_status(cfg: dict | None = None) -> dict:
    """What the chat UI needs to decide whether to show voice controls."""
    conf = settings(cfg)
    on = bool(conf["enabled"])
    return {
        "enabled": on and stt_ready(conf),
        "tts": on and tts_ready(conf),
        "provider": conf["provider"],
        "stt_engine": conf["stt_engine"],
        "tts_engine": conf["tts_engine"],
        "language": conf["language"],
        "voice": conf["voice"],
        "autoplay": conf["autoplay"],
        "controls": conf["controls"],
    }


def speakable_text(text: str, limit: int = DEFAULT_MAX_REPLY_CHARS) -> str:
    """Strip markdown so the voice reads prose, not asterisks and URLs."""
    raw = str(text or "")
    raw = _CODE_BLOCK.sub(" ", raw)
    raw = _IMAGE_MD.sub(" ", raw)
    raw = _LINK_MD.sub(r"\1", raw)
    raw = _INLINE_CODE.sub(r"\1", raw)
    raw = _HR.sub(" ", raw)
    raw = _HEADING.sub("", raw)
    raw = _BULLET.sub("", raw)
    raw = _EMPHASIS.sub("", raw)
    raw = _EMOJI.sub(" ", raw)
    # Brand first so a truncated reply does not cut mid-"HASSAI".
    raw = _BRAND_SAY.sub(_BRAND_SPOKEN, raw)
    clean = " ".join(raw.split())
    if len(clean) <= limit:
        return clean
    # Cut on a sentence boundary so the reply does not stop mid-word.
    head = clean[:limit]
    for sep in (". ", "! ", "? "):
        idx = head.rfind(sep)
        if idx > limit * 0.5:
            return head[: idx + 1]
    return head.rsplit(" ", 1)[0] + "…"


async def synthesize(text: str, conf: dict) -> tuple[bytes, str]:
    """Text → (audio bytes, mime) with whichever TTS engine is selected."""
    if conf["tts_engine"] == "local":
        local = conf["local_tts"]
        return await lv.synthesize(
            local["url"],
            text,
            voice=local["voice"],
            speaker=local["speaker"],
            model=local["model"],
            timeout=local["timeout"],
        )
    audio = await gv.synthesize(
        conf["google_api_key"],
        text,
        language=conf["language"],
        speaker=conf["voice"],
        speaking_rate=conf["speaking_rate"],
    )
    return audio, "audio/mpeg"


async def speak(user_id: str, text: str, cfg: dict | None = None) -> dict:
    """Synthesize `text` and persist it as an audio attachment."""
    conf = settings(cfg)
    if not conf["enabled"]:
        raise gv.VoiceError("Voice is disabled in Settings → Voice.")
    clean = speakable_text(text, conf["max_reply_chars"])
    if not clean:
        raise gv.VoiceError("Nothing to speak.")
    audio, mime = await synthesize(clean, conf)
    name = "reply.wav" if mime == "audio/wav" else "reply.mp3"
    att = cm.persist_audio_bytes(user_id, audio, mime, name=name)
    log.info(
        "Spoke %s chars for %s via %s (%s bytes)",
        len(clean), user_id, conf["tts_engine"], len(audio),
    )
    return {
        "id": att["id"],
        "mime": att["mime"],
        "kind": "audio",
        "name": att.get("name") or name,
        "url": cm.attachment_public_url(att["id"]),
        "text": clean,
        "chars": len(clean),
    }


def pcm_from_wav(raw: bytes) -> tuple[bytes, int]:
    """Return (raw PCM, sample rate) from a RIFF/WAVE blob.

    Google accepts LINEAR16 as bare PCM; unwrapping here keeps the request valid
    whatever header the browser produced.
    """
    if len(raw) < 44 or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        return raw, 0
    sample_rate = 0
    pos = 12
    data = b""
    while pos + 8 <= len(raw):
        chunk_id = raw[pos:pos + 4]
        size = int.from_bytes(raw[pos + 4:pos + 8], "little")
        body = raw[pos + 8:pos + 8 + size]
        if chunk_id == b"fmt " and len(body) >= 8:
            sample_rate = int.from_bytes(body[4:8], "little")
        elif chunk_id == b"data":
            data = body
        pos += 8 + size + (size % 2)
    if not data:
        return raw, sample_rate
    return data, sample_rate


async def transcribe(audio: bytes, sample_rate: int = 16000, cfg: dict | None = None) -> str:
    conf = settings(cfg)
    if not conf["enabled"]:
        raise gv.VoiceError("Voice is disabled in Settings → Voice.")
    pcm, wav_rate = pcm_from_wav(audio)
    rate = wav_rate or sample_rate
    if conf["stt_engine"] == "local":
        local = conf["local_stt"]
        return await lv.transcribe(
            local["url"],
            audio,
            pcm,
            sample_rate=rate,
            language=conf["language"],
            model=local["model"],
            timeout=local["timeout"],
        )
    return await gv.transcribe(
        conf["google_api_key"],
        pcm,
        language=conf["language"],
        sample_rate=rate,
    )
