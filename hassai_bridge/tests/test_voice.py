"""Tests for the voice layer (Google Chirp 3: HD)."""

from __future__ import annotations

import base64
import struct

import pytest

from services import google_voice as gv
from services import voice as vc


def _wav(pcm: bytes, rate: int = 16000) -> bytes:
    return (
        b"RIFF" + struct.pack("<I", 36 + len(pcm)) + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 1, rate, rate * 2, 2, 16)
        + b"data" + struct.pack("<I", len(pcm)) + pcm
    )


# ── Voice ids ──────────────────────────────────────

def test_voice_name_builds_chirp_id():
    assert gv.voice_name("ro-RO", "Kore") == "ro-RO-Chirp3-HD-Kore"
    assert gv.voice_name("en-US", "Puck") == "en-US-Chirp3-HD-Puck"


def test_voice_name_passes_through_full_id():
    assert gv.voice_name("ro-RO", "ro-RO-Wavenet-A") == "ro-RO-Wavenet-A"


def test_voice_name_defaults():
    assert gv.voice_name("", "") == "ro-RO-Chirp3-HD-Kore"


# ── Settings ───────────────────────────────────────

def test_settings_defaults_to_romanian_and_disabled():
    conf = vc.settings({})
    assert conf["enabled"] is False
    assert conf["language"] == "ro-RO"
    assert conf["voice"] == "Kore"
    assert conf["autoplay"] is True
    assert conf["controls"] == "both"


def test_settings_clamps_rate_and_length():
    conf = vc.settings({"voice": {"speaking_rate": 9, "max_reply_chars": 999999}})
    assert conf["speaking_rate"] == 2.0
    assert conf["max_reply_chars"] == gv.MAX_TTS_CHARS


def test_settings_survives_garbage_values():
    conf = vc.settings({"voice": {"speaking_rate": "fast", "max_reply_chars": None}})
    assert conf["speaking_rate"] == 1.0
    assert conf["max_reply_chars"] == vc.DEFAULT_MAX_REPLY_CHARS


def test_settings_normalizes_controls():
    assert vc.settings({"voice": {"controls": "mic"}})["controls"] == "mic"
    assert vc.settings({"voice": {"controls": "conversation"}})["controls"] == "conversation"
    assert vc.settings({"voice": {"controls": "BOTH"}})["controls"] == "both"
    assert vc.settings({"voice": {"controls": "nope"}})["controls"] == "both"


def test_public_status_needs_key_and_toggle():
    assert vc.public_status({"voice": {"enabled": True}})["enabled"] is False
    on = vc.public_status({"voice": {"enabled": True, "google_api_key": "AIza", "controls": "mic"}})
    assert on["enabled"] is True
    assert on["language"] == "ro-RO"
    assert on["controls"] == "mic"


# ── Text cleanup ───────────────────────────────────

def test_speakable_strips_markdown_and_emoji():
    out = vc.speakable_text(
        "## Gata\n\n- **Am aprins** lumina 🔥 din [bucătărie](http://x)\n"
        "- `switch.bucatarie` este `on`\n\n```yaml\nfoo: bar\n```"
    )
    assert "**" not in out and "#" not in out and "```" not in out
    assert "http" not in out
    assert "🔥" not in out
    assert "Am aprins lumina" in out
    assert "bucătărie" in out


def test_speakable_cuts_on_sentence_boundary():
    text = "Am aprins lumina din bucătărie și am pornit termostatul. " + ("cuvant " * 200)
    out = vc.speakable_text(text, limit=80)
    assert out == "Am aprins lumina din bucătărie și am pornit termostatul."


def test_speakable_falls_back_to_word_boundary():
    # No sentence end in the first half of the budget — cut on a word instead of
    # throwing away most of what we are allowed to say.
    out = vc.speakable_text("cuvant " * 100, limit=40)
    assert out.endswith("…")
    assert len(out) <= 41
    assert "cuvan…" not in out


def test_speakable_handles_empty():
    assert vc.speakable_text("") == ""
    assert vc.speakable_text(None) == ""


def test_speakable_says_hassai_as_a_word():
    """ALL-CAPS HASSAI is spelled letter-by-letter by Chirp; speak it as Hassai."""
    out = vc.speakable_text("Salut! Sunt HASSAI, asistentul tău.")
    assert "HASSAI" not in out
    assert "Hassai" in out
    assert vc.speakable_text("Hi! I am hassai.") == "Hi! I am Hassai."
    assert "Hassai Bridge" in vc.speakable_text("Open HASSAI Bridge from the sidebar.")
    # Do not rewrite substrings of other words.
    assert vc.speakable_text("hassailing") == "hassailing"


# ── WAV unwrapping ─────────────────────────────────

def test_pcm_from_wav_reads_rate_and_payload():
    pcm = b"\x01\x02" * 50
    data, rate = vc.pcm_from_wav(_wav(pcm, 16000))
    assert rate == 16000
    assert data == pcm


def test_pcm_from_wav_passes_through_non_wav():
    raw = b"not a wav file at all"
    data, rate = vc.pcm_from_wav(raw)
    assert data == raw
    assert rate == 0


# ── HTTP layer ─────────────────────────────────────

class _Resp:
    def __init__(self, status=200, payload=None, text=""):
        self.status_code = status
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _Client:
    def __init__(self, resp):
        self._resp = resp
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._resp


@pytest.mark.parametrize("status,fragment", [
    (403, "API key"),
    (429, "rate-limited"),
    (500, "HTTP 500"),
])
def test_error_messages_are_actionable(status, fragment):
    assert fragment in gv._friendly_error(status, "boom")


def test_disabled_api_error_explains_the_fix():
    msg = gv._friendly_error(403, '{"error":{"status":"SERVICE_DISABLED"}}')
    assert "Enable Cloud Text-to-Speech" in msg


def test_referrer_restriction_error_explains_the_fix():
    msg = gv._friendly_error(403, "API_KEY_HTTP_REFERRER_BLOCKED")
    assert "referrer" in msg.lower() or "referrer restriction" in msg.lower()


def test_synthesize_sends_chirp_voice(monkeypatch):
    audio = b"\xff\xfbfake-mp3"
    client = _Client(_Resp(200, {"audioContent": base64.b64encode(audio).decode()}))
    monkeypatch.setattr(gv.httpx, "AsyncClient", lambda **kw: client)

    import asyncio

    out = asyncio.run(gv.synthesize("AIza", "Salut", language="ro-RO", speaker="Kore"))
    assert out == audio
    sent = client.calls[0]["json"]
    assert sent["voice"] == {"languageCode": "ro-RO", "name": "ro-RO-Chirp3-HD-Kore"}
    assert sent["audioConfig"]["audioEncoding"] == "MP3"
    # Default rate must not be sent — it is Google's own default.
    assert "speakingRate" not in sent["audioConfig"]
    assert client.calls[0]["headers"]["X-Goog-Api-Key"] == "AIza"


def test_synthesize_includes_custom_rate(monkeypatch):
    client = _Client(_Resp(200, {"audioContent": base64.b64encode(b"x").decode()}))
    monkeypatch.setattr(gv.httpx, "AsyncClient", lambda **kw: client)

    import asyncio

    asyncio.run(gv.synthesize("AIza", "Salut", speaking_rate=1.25))
    assert client.calls[0]["json"]["audioConfig"]["speakingRate"] == 1.25


def test_synthesize_requires_key():
    import asyncio

    with pytest.raises(gv.VoiceError, match="No Google API key"):
        asyncio.run(gv.synthesize("", "Salut"))


def test_synthesize_rejects_empty_text():
    import asyncio

    with pytest.raises(gv.VoiceError, match="Nothing to speak"):
        asyncio.run(gv.synthesize("AIza", "   "))


def test_transcribe_sends_linear16(monkeypatch):
    payload = {"results": [{"alternatives": [{"transcript": "aprinde lumina"}]}]}
    client = _Client(_Resp(200, payload))
    monkeypatch.setattr(gv.httpx, "AsyncClient", lambda **kw: client)

    import asyncio

    text = asyncio.run(gv.transcribe("AIza", b"\x00\x01" * 100, language="ro-RO"))
    assert text == "aprinde lumina"
    config = client.calls[0]["json"]["config"]
    assert config["encoding"] == "LINEAR16"
    assert config["languageCode"] == "ro-RO"
    assert config["sampleRateHertz"] == 16000


def test_transcribe_joins_multiple_results(monkeypatch):
    payload = {"results": [
        {"alternatives": [{"transcript": "aprinde lumina"}]},
        {"alternatives": [{"transcript": "din bucătărie"}]},
    ]}
    monkeypatch.setattr(gv.httpx, "AsyncClient", lambda **kw: _Client(_Resp(200, payload)))

    import asyncio

    assert asyncio.run(gv.transcribe("AIza", b"x")) == "aprinde lumina din bucătărie"


def test_transcribe_rejects_oversized_audio():
    import asyncio

    with pytest.raises(gv.VoiceError, match="too long"):
        asyncio.run(gv.transcribe("AIza", b"0" * (gv.MAX_STT_BYTES + 1)))


def test_speak_disabled_when_voice_off():
    import asyncio

    with pytest.raises(gv.VoiceError, match="disabled"):
        asyncio.run(vc.speak("alice", "Salut", cfg={"voice": {"enabled": False}}))
