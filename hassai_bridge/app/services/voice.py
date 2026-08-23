"""Voice layer: config resolution plus speak/transcribe on top of a backend.

Only Google (Chirp 3: HD) is wired today, but the config carries a `provider`
key so a local Piper/Whisper path can slot in without touching the routes.
"""

from __future__ import annotations

import logging
import re

from config import load_config
from services import chat_media as cm
from services import google_voice as gv

log = logging.getLogger("hassai.voice")

DEFAULT_MAX_REPLY_CHARS = 800
# What the chat composer shows when voice is enabled.
VOICE_CONTROLS = frozenset({"both", "mic", "conversation"})

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
        "google_api_key": str(raw.get("google_api_key") or "").strip(),
        "language": str(raw.get("language") or gv.DEFAULT_LANGUAGE),
        "voice": str(raw.get("voice") or gv.DEFAULT_VOICE),
        "speaking_rate": max(0.25, min(2.0, rate)),
        "autoplay": raw.get("autoplay") is not False,
        "max_reply_chars": max(100, min(gv.MAX_TTS_CHARS, max_chars)),
        "controls": controls,
    }


def is_configured(cfg: dict | None = None) -> bool:
    conf = settings(cfg)
    return bool(conf["enabled"] and conf["google_api_key"])


def public_status(cfg: dict | None = None) -> dict:
    """What the chat UI needs to decide whether to show voice controls."""
    conf = settings(cfg)
    return {
        "enabled": bool(conf["enabled"] and conf["google_api_key"]),
        "provider": conf["provider"],
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


async def speak(user_id: str, text: str, cfg: dict | None = None) -> dict:
    """Synthesize `text` and persist it as an audio attachment."""
    conf = settings(cfg)
    if not conf["enabled"]:
        raise gv.VoiceError("Voice is disabled in Settings → Voice.")
    clean = speakable_text(text, conf["max_reply_chars"])
    if not clean:
        raise gv.VoiceError("Nothing to speak.")
    audio = await gv.synthesize(
        conf["google_api_key"],
        clean,
        language=conf["language"],
        speaker=conf["voice"],
        speaking_rate=conf["speaking_rate"],
    )
    att = cm.persist_audio_bytes(user_id, audio, "audio/mpeg", name="reply.mp3")
    log.info("Spoke %s chars for %s (%s bytes)", len(clean), user_id, len(audio))
    return {
        "id": att["id"],
        "mime": att["mime"],
        "kind": "audio",
        "name": att.get("name") or "reply.mp3",
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
    return await gv.transcribe(
        conf["google_api_key"],
        pcm,
        language=conf["language"],
        sample_rate=wav_rate or sample_rate,
    )
