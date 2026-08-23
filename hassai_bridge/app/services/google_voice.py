"""Google Cloud speech services — Chirp 3: HD text-to-speech and speech-to-text.

Both REST endpoints accept a plain API key, so the add-on only needs one key in
Settings instead of a service-account JSON. Kept separate from the LLM provider
list: voice is orthogonal to which model answers, so DeepSeek can stay primary
and still speak.
"""

from __future__ import annotations

import base64
import logging

import httpx

log = logging.getLogger("hassai.voice.google")

TTS_URL = "https://texttospeech.googleapis.com/v1/text:synthesize"
STT_URL = "https://speech.googleapis.com/v1/speech:recognize"
VOICES_URL = "https://texttospeech.googleapis.com/v1/voices"

# Chirp 3: HD speakers. Voice id is "<locale>-Chirp3-HD-<name>".
CHIRP_VOICES: dict[str, str] = {
    "Achernar": "female", "Achird": "male", "Algenib": "male", "Algieba": "male",
    "Alnilam": "male", "Aoede": "female", "Autonoe": "female", "Callirrhoe": "female",
    "Charon": "male", "Despina": "female", "Enceladus": "male", "Erinome": "female",
    "Fenrir": "male", "Gacrux": "female", "Iapetus": "male", "Kore": "female",
    "Laomedeia": "female", "Leda": "female", "Orus": "male", "Pulcherrima": "female",
    "Puck": "male", "Rasalgethi": "male", "Sadachbia": "male", "Sadaltager": "male",
    "Schedar": "male", "Sulafat": "female",
}

DEFAULT_LANGUAGE = "ro-RO"
DEFAULT_VOICE = "Kore"
MODEL_CHIRP3 = "Chirp3-HD"

# Guardrail: one spoken reply should not silently burn the monthly free tier.
MAX_TTS_CHARS = 3000
# 16 kHz mono 16-bit ≈ 32 KB/s, so this is ~60 s of speech.
MAX_STT_BYTES = 2_000_000

_TIMEOUT = 30.0


class VoiceError(RuntimeError):
    """Raised when Google returns an error we want to surface to the user."""


def voice_name(language: str = DEFAULT_LANGUAGE, speaker: str = DEFAULT_VOICE) -> str:
    """Build a Chirp 3: HD voice id, e.g. ro-RO-Chirp3-HD-Kore."""
    lang = (language or DEFAULT_LANGUAGE).strip() or DEFAULT_LANGUAGE
    name = (speaker or DEFAULT_VOICE).strip() or DEFAULT_VOICE
    # Already a full voice id (any model) — pass through untouched.
    if name.lower().startswith(lang.lower() + "-"):
        return name
    return f"{lang}-{MODEL_CHIRP3}-{name}"


def _friendly_error(status: int, body: str) -> str:
    text = (body or "")[:400]
    if status in (401, 403):
        if "SERVICE_DISABLED" in text or "has not been used" in text:
            return (
                "Google rejected the request: the API is not enabled for this key's "
                "project. Enable Cloud Text-to-Speech / Speech-to-Text in Google Cloud."
            )
        if "API_KEY_HTTP_REFERRER" in text or "referer" in text.lower():
            return (
                "Google rejected the API key because of its restrictions. Allow it for "
                "server use (no HTTP referrer restriction) or restrict it by IP."
            )
        return "Google rejected the API key (403). Check the key and its restrictions."
    if status == 400 and "quota" in text.lower():
        return "Google rejected the request: quota or billing problem on the project."
    if status == 429:
        return "Google rate-limited the request. Try again in a moment."
    return f"Google returned HTTP {status}: {text}"


async def _post(url: str, api_key: str, payload: dict) -> dict:
    headers = {
        "X-Goog-Api-Key": api_key,
        "Content-Type": "application/json; charset=utf-8",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code >= 400:
        raise VoiceError(_friendly_error(resp.status_code, resp.text))
    try:
        return resp.json()
    except ValueError as exc:
        raise VoiceError(f"Google returned a malformed response: {exc}") from exc


async def synthesize(
    api_key: str,
    text: str,
    *,
    language: str = DEFAULT_LANGUAGE,
    speaker: str = DEFAULT_VOICE,
    speaking_rate: float = 1.0,
) -> bytes:
    """Text → MP3 bytes using a Chirp 3: HD voice."""
    if not api_key:
        raise VoiceError("No Google API key configured for voice.")
    clean = " ".join(str(text or "").split())
    if not clean:
        raise VoiceError("Nothing to speak.")
    if len(clean) > MAX_TTS_CHARS:
        clean = clean[:MAX_TTS_CHARS].rsplit(" ", 1)[0] + "…"

    audio_config: dict = {"audioEncoding": "MP3"}
    try:
        rate = float(speaking_rate)
    except (TypeError, ValueError):
        rate = 1.0
    if abs(rate - 1.0) > 0.01:
        audio_config["speakingRate"] = max(0.25, min(2.0, rate))

    payload = {
        "input": {"text": clean},
        "voice": {
            "languageCode": (language or DEFAULT_LANGUAGE),
            "name": voice_name(language, speaker),
        },
        "audioConfig": audio_config,
    }
    data = await _post(TTS_URL, api_key, payload)
    content = data.get("audioContent")
    if not content:
        raise VoiceError("Google returned no audio.")
    try:
        return base64.b64decode(content)
    except Exception as exc:  # pragma: no cover - defensive
        raise VoiceError(f"Could not decode Google audio: {exc}") from exc


async def transcribe(
    api_key: str,
    audio: bytes,
    *,
    language: str = DEFAULT_LANGUAGE,
    sample_rate: int = 16000,
) -> str:
    """16 kHz mono LINEAR16 WAV bytes → transcript text."""
    if not api_key:
        raise VoiceError("No Google API key configured for voice.")
    if not audio:
        raise VoiceError("No audio recorded.")
    if len(audio) > MAX_STT_BYTES:
        raise VoiceError("Recording is too long — keep it under about a minute.")

    payload = {
        "config": {
            "encoding": "LINEAR16",
            "sampleRateHertz": int(sample_rate or 16000),
            "languageCode": (language or DEFAULT_LANGUAGE),
            "enableAutomaticPunctuation": True,
            "model": "latest_short",
        },
        "audio": {"content": base64.b64encode(audio).decode("ascii")},
    }
    data = await _post(STT_URL, api_key, payload)
    parts = []
    for result in data.get("results") or []:
        alternatives = result.get("alternatives") or []
        if alternatives:
            parts.append(str(alternatives[0].get("transcript") or "").strip())
    return " ".join(p for p in parts if p).strip()


async def list_voices(api_key: str, language: str = DEFAULT_LANGUAGE) -> list[dict]:
    """Chirp 3: HD voices available for a language (used by the Settings picker)."""
    if not api_key:
        raise VoiceError("No Google API key configured for voice.")
    headers = {"X-Goog-Api-Key": api_key}
    params = {"languageCode": language or DEFAULT_LANGUAGE}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(VOICES_URL, headers=headers, params=params)
    if resp.status_code >= 400:
        raise VoiceError(_friendly_error(resp.status_code, resp.text))
    out = []
    for entry in resp.json().get("voices") or []:
        name = str(entry.get("name") or "")
        if MODEL_CHIRP3 not in name:
            continue
        speaker = name.rsplit("-", 1)[-1]
        out.append({
            "id": name,
            "speaker": speaker,
            "gender": str(entry.get("ssmlGender") or CHIRP_VOICES.get(speaker, "")).lower(),
        })
    out.sort(key=lambda v: v["speaker"])
    return out
