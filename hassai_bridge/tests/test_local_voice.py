"""Tests for the local speech layer (Wyoming Whisper/Piper + HTTP servers)."""

from __future__ import annotations

import asyncio
import json
import struct

import pytest

from services import google_voice as gv
from services import local_voice as lv
from services import voice as vc


# ── Minimal, independent Wyoming implementation for the fake servers ──

async def _read_event(reader):
    line = await reader.readline()
    if not line:
        return None
    header = json.loads(line)
    data = {}
    if header.get("data_length"):
        data = json.loads(await reader.readexactly(int(header["data_length"])))
    payload = b""
    if header.get("payload_length"):
        payload = await reader.readexactly(int(header["payload_length"]))
    return header["type"], data, payload


async def _write_event(writer, event_type, data=None, payload=b""):
    header = {"type": event_type}
    body = b""
    if data is not None:
        body = json.dumps(data).encode()
        header["data_length"] = len(body)
    if payload:
        header["payload_length"] = len(payload)
    writer.write(json.dumps(header).encode() + b"\n")
    if body:
        writer.write(body)
    if payload:
        writer.write(payload)
    await writer.drain()


async def _with_server(handler, run):
    """Run `run(port)` against a throwaway Wyoming server on localhost."""
    server = await asyncio.start_server(handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        return await run(port)
    finally:
        server.close()


def _wav_body(raw: bytes) -> tuple[bytes, int]:
    rate = struct.unpack("<I", raw[24:28])[0]
    return raw[44:], rate


# ── Endpoint parsing ───────────────────────────────

def test_parse_endpoint_defaults_to_wyoming():
    assert lv.parse_endpoint("core_whisper", lv.DEFAULT_STT_PORT) == ("wyoming", "core_whisper", 10300)
    assert lv.parse_endpoint("core_piper:10200", lv.DEFAULT_TTS_PORT) == ("wyoming", "core_piper", 10200)
    assert lv.parse_endpoint("tcp://192.168.1.5:1234", lv.DEFAULT_TTS_PORT) == ("wyoming", "192.168.1.5", 1234)


def test_parse_endpoint_detects_http():
    mode, url, port = lv.parse_endpoint("http://nas:8000/", lv.DEFAULT_STT_PORT)
    assert (mode, url, port) == ("http", "http://nas:8000", 0)


def test_parse_endpoint_rejects_empty_and_bad_port():
    with pytest.raises(gv.VoiceError):
        lv.parse_endpoint("", lv.DEFAULT_STT_PORT)
    with pytest.raises(gv.VoiceError):
        lv.parse_endpoint("host:abc", lv.DEFAULT_STT_PORT)


def test_short_language_strips_region():
    assert lv.short_language("ro-RO") == "ro"
    assert lv.short_language("en_US") == "en"
    assert lv.short_language("") == ""


# ── Wyoming speech to text ─────────────────────────

def test_wyoming_transcribe_round_trip():
    seen: dict = {}

    async def handler(reader, writer):
        audio = bytearray()
        while True:
            event = await _read_event(reader)
            if event is None:
                break
            event_type, data, payload = event
            if event_type == "transcribe":
                seen["request"] = data
            elif event_type == "audio-start":
                seen["rate"] = data.get("rate")
            elif event_type == "audio-chunk":
                audio += payload
            elif event_type == "audio-stop":
                seen["audio"] = bytes(audio)
                await _write_event(writer, "transcript", {"text": "aprinde lumina"})
                break
        writer.close()

    pcm = b"\x01\x02" * 9000

    async def run(port):
        return await lv.transcribe(
            f"127.0.0.1:{port}", b"", pcm, sample_rate=16000, language="ro-RO", timeout=10
        )

    text = asyncio.run(_with_server(handler, run))
    assert text == "aprinde lumina"
    assert seen["request"] == {"language": "ro"}
    assert seen["rate"] == 16000
    assert seen["audio"] == pcm


def test_wyoming_transcribe_surfaces_server_error():
    async def handler(reader, writer):
        while True:
            event = await _read_event(reader)
            if event is None:
                break
            if event[0] == "audio-stop":
                await _write_event(writer, "error", {"text": "model missing"})
                break
        writer.close()

    async def run(port):
        return await lv.transcribe(f"127.0.0.1:{port}", b"", b"\x00\x00", timeout=10)

    with pytest.raises(gv.VoiceError, match="model missing"):
        asyncio.run(_with_server(handler, run))


# ── Wyoming text to speech ─────────────────────────

def test_wyoming_synthesize_wraps_pcm_in_wav():
    seen: dict = {}

    async def handler(reader, writer):
        event = await _read_event(reader)
        seen["request"] = event[1]
        await _write_event(writer, "audio-start", {"rate": 22050, "width": 2, "channels": 1})
        await _write_event(writer, "audio-chunk", {"rate": 22050, "width": 2, "channels": 1}, b"\x05\x06" * 100)
        await _write_event(writer, "audio-stop", {})
        writer.close()

    async def run(port):
        return await lv.synthesize(f"127.0.0.1:{port}", "Salut", voice="ro_RO-mihai-medium", timeout=10)

    audio, mime = asyncio.run(_with_server(handler, run))
    body, rate = _wav_body(audio)
    assert mime == "audio/wav"
    assert rate == 22050
    assert body == b"\x05\x06" * 100
    assert seen["request"] == {"text": "Salut", "voice": {"name": "ro_RO-mihai-medium"}}


def test_wyoming_synthesize_without_audio_is_an_error():
    async def handler(reader, writer):
        await _read_event(reader)
        await _write_event(writer, "audio-start", {"rate": 22050})
        await _write_event(writer, "audio-stop", {})
        writer.close()

    async def run(port):
        return await lv.synthesize(f"127.0.0.1:{port}", "Salut", timeout=10)

    with pytest.raises(gv.VoiceError, match="no audio"):
        asyncio.run(_with_server(handler, run))


def test_describe_returns_voices():
    info = {"tts": [{"name": "piper", "voices": [
        {"name": "ro_RO-mihai-medium", "languages": ["ro_RO"]},
        {"name": "en_US-amy-low", "languages": ["en_US"]},
    ]}]}

    async def handler(reader, writer):
        await _read_event(reader)
        await _write_event(writer, "info", info)
        writer.close()

    async def run(port):
        return await lv.describe(f"127.0.0.1:{port}", kind="tts", timeout=10)

    voices = lv.voices_from_info(asyncio.run(_with_server(handler, run)))
    assert [v["id"] for v in voices] == ["en_US-amy-low", "ro_RO-mihai-medium"]
    assert voices[1]["language"] == "ro_RO"


def test_models_from_info_reads_asr_names():
    info = {"asr": [{"name": "whisper", "models": [{"name": "base-int8"}, {"name": "small"}]}]}
    assert lv.models_from_info(info) == ["base-int8", "small"]


def test_wav_from_pcm_header_matches_payload():
    wav = lv.wav_from_pcm(b"\x01\x02" * 10, rate=16000)
    body, rate = _wav_body(wav)
    assert rate == 16000
    assert body == b"\x01\x02" * 10


# ── Engine selection ───────────────────────────────

def test_settings_defaults_both_engines_to_google():
    conf = vc.settings({})
    assert conf["stt_engine"] == "google"
    assert conf["tts_engine"] == "google"
    assert conf["local_stt"]["url"] == lv.DEFAULT_STT_URL
    assert conf["local_tts"]["url"] == lv.DEFAULT_TTS_URL


def test_settings_allows_mixed_engines():
    conf = vc.settings({"voice": {
        "stt_engine": "local",
        "tts_engine": "google",
        "local_stt": {"url": "whisper:10300", "model": "small", "timeout": 5000},
    }})
    assert conf["stt_engine"] == "local"
    assert conf["tts_engine"] == "google"
    assert conf["local_stt"]["model"] == "small"
    assert conf["local_stt"]["timeout"] == 600.0


def test_settings_rejects_unknown_engine():
    conf = vc.settings({"voice": {"stt_engine": "ibm", "tts_engine": ""}})
    assert conf["stt_engine"] == "google"
    assert conf["tts_engine"] == "google"


def test_readiness_follows_the_selected_engine():
    local_stt_only = vc.settings({"voice": {
        "enabled": True,
        "stt_engine": "local",
        "local_stt": {"url": "whisper:10300"},
    }})
    assert vc.stt_ready(local_stt_only) is True
    # Google is still the TTS engine, and there is no key for it.
    assert vc.tts_ready(local_stt_only) is False

    no_local_url = vc.settings({"voice": {"enabled": True, "tts_engine": "local", "local_tts": {"url": ""}}})
    assert vc.tts_ready(no_local_url) is False


def test_public_status_reports_each_side():
    status = vc.public_status({"voice": {
        "enabled": True,
        "stt_engine": "local",
        "tts_engine": "google",
        "google_api_key": "AIza",
        "local_stt": {"url": "whisper:10300"},
    }})
    assert status["enabled"] is True
    assert status["tts"] is True
    assert status["stt_engine"] == "local"
    assert status["tts_engine"] == "google"


def test_public_status_off_when_voice_disabled():
    status = vc.public_status({"voice": {
        "enabled": False,
        "stt_engine": "local",
        "local_stt": {"url": "whisper:10300"},
    }})
    assert status["enabled"] is False
    assert status["tts"] is False


# ── Routing ────────────────────────────────────────

def test_transcribe_routes_to_local_engine(monkeypatch):
    seen: dict = {}

    async def fake(url, wav, pcm, *, sample_rate, language, model, timeout):
        seen.update(url=url, pcm=pcm, sample_rate=sample_rate, language=language, model=model)
        return "salut"

    monkeypatch.setattr(lv, "transcribe", fake)
    cfg = {"voice": {
        "enabled": True,
        "stt_engine": "local",
        "local_stt": {"url": "whisper:10300", "model": "base-int8"},
    }}
    out = asyncio.run(vc.transcribe(b"\x09\x09", sample_rate=16000, cfg=cfg))
    assert out == "salut"
    assert seen["url"] == "whisper:10300"
    assert seen["model"] == "base-int8"
    assert seen["language"] == "ro-RO"


def test_speak_routes_to_local_engine(monkeypatch, tmp_path):
    from services import chat_media as cm

    async def fake(url, text, *, voice, speaker, model, timeout):
        return lv.wav_from_pcm(b"\x00\x01" * 50, rate=22050), "audio/wav"

    monkeypatch.setattr(lv, "synthesize", fake)
    monkeypatch.setattr(cm, "MEDIA_DIR", tmp_path, raising=False)
    saved: dict = {}

    def fake_persist(user_id, raw, mime, *, name):
        saved.update(mime=mime, name=name, size=len(raw))
        return {"id": "abc123", "mime": mime, "name": name}

    monkeypatch.setattr(cm, "persist_audio_bytes", fake_persist)
    monkeypatch.setattr(cm, "attachment_public_url", lambda att_id: f"/api/chat/files/{att_id}")

    cfg = {"voice": {"enabled": True, "tts_engine": "local", "local_tts": {"url": "piper:10200"}}}
    out = asyncio.run(vc.speak("alice", "Salut lume", cfg=cfg))
    assert out["mime"] == "audio/wav"
    assert out["name"] == "reply.wav"
    assert saved["name"] == "reply.wav"
