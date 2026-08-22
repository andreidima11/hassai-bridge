"""Tests for Frigate camera tools."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from services import chat_files as cf
from services import frigate_tools as ft


def test_normalize_camera_entity_id():
    assert ft._normalize_camera("camera.front_yard") == "front_yard"
    assert ft._normalize_camera("Front Door") == "Front_Door"


def test_events_from_media_folder(tmp_path: Path):
    media = tmp_path / "media"
    clips = media / "frigate" / "clips"
    clips.mkdir(parents=True)
    img = clips / "driveway-1234567890.1-abc.jpg"
    img.write_bytes(b"\xff\xd8\xfffakejpeg")

    cf.set_roots_for_test((str(media),))
    try:
        result = asyncio.run(ft._events_from_media("driveway", 5, include_snapshot=True))
        assert "driveway-1234567890.1-abc.jpg" in result["text"]
        assert result["image"] is not None
        assert result["image"]["bytes"].startswith(b"\xff\xd8")
    finally:
        cf.set_roots_for_test(None)


def test_list_events_api_with_snapshot():
    events = [
        {
            "id": "evt-1",
            "camera": "front",
            "label": "person",
            "top_score": 0.91,
            "start_time": 1_700_000_000.0,
            "end_time": 1_700_000_010.0,
            "has_snapshot": True,
        },
        {
            "id": "evt-2",
            "camera": "front",
            "label": "person",
            "top_score": 0.88,
            "start_time": 1_699_999_000.0,
            "end_time": 1_699_999_020.0,
            "has_snapshot": True,
        },
    ]

    async def fake_json(path, params=None):
        assert path == "/api/events"
        return events

    async def fake_bytes(path, params=None):
        assert "/snapshot.jpg" in path
        return b"\xff\xd8\xffsnap", "image/jpeg"

    async def _run():
        with (
            patch.object(ft, "_get_json", side_effect=fake_json),
            patch.object(ft, "_get_bytes", side_effect=fake_bytes),
        ):
            return await ft.list_events(camera="front", include_snapshot=True, limit=3)

    result = asyncio.run(_run())
    assert "person" in result["text"]
    assert len(result["images"]) == 1
    assert result["image"]["filename"].startswith("frigate-front-")
    assert result["image"]["bytes"].startswith(b"\xff\xd8")


def test_list_events_snapshot_only_one_even_with_many_events():
    events = [
        {"id": "evt-1", "camera": "front", "label": "person", "has_snapshot": True, "start_time": 1.0},
        {"id": "evt-2", "camera": "front", "label": "car", "has_snapshot": True, "start_time": 2.0},
    ]

    async def fake_json(path, params=None):
        return events

    calls = []

    async def fake_bytes(path, params=None):
        calls.append(path)
        return b"\xff\xd8\xff", "image/jpeg"

    async def _run():
        with (
            patch.object(ft, "_get_json", side_effect=fake_json),
            patch.object(ft, "_get_bytes", side_effect=fake_bytes),
        ):
            return await ft.list_events(include_snapshot=True, limit=5)

    result = asyncio.run(_run())
    assert len(result["images"]) == 1
    assert len(calls) == 1
    assert "evt-1" in calls[0]


def test_system_hint_mentions_no_imagine():
    with patch.object(ft, "is_enabled", return_value=True):
        hint = ft.system_hint()
    assert "generate_image" in hint
    assert "include_snapshot=false" in hint


def test_snapshot_latest_jpg():
    async def fake_bytes(path, params=None):
        assert path == "/api/gate/latest.jpg"
        return b"jpegdata", "image/jpeg"

    async def fake_json(path, params=None):
        return [
            {
                "id": "e2",
                "camera": "gate",
                "label": "car",
                "top_score": 0.8,
                "start_time": 1_700_000_100.0,
                "has_snapshot": True,
            }
        ]

    async def _run():
        with (
            patch.object(ft, "_get_bytes", side_effect=fake_bytes),
            patch.object(ft, "_get_json", side_effect=fake_json),
        ):
            return await ft.snapshot(camera="gate")

    result = asyncio.run(_run())
    assert "gate" in result["text"]
    assert "car" in result["text"]
    assert result["image"]["bytes"] == b"jpegdata"


def test_system_hint_when_enabled():
    with patch.object(ft, "is_enabled", return_value=True):
        hint = ft.system_hint()
        assert "frigate_events" in hint
        assert "frigate_snapshot" in hint


def test_health_status_media_fallback(tmp_path: Path):
    media = tmp_path / "media"
    (media / "frigate" / "clips").mkdir(parents=True)

    cf.set_roots_for_test((str(media),))
    try:
        async def boom():
            raise RuntimeError("no api")

        async def _run():
            with (
                patch.object(ft, "_cfg", return_value={"enabled": True, "base_url": "http://frigate:5000", "timeout": 12}),
                patch("httpx.AsyncClient") as client_cls,
            ):
                # Make httpx client raise on get
                instance = client_cls.return_value
                instance.__aenter__.return_value = instance
                instance.__aexit__.return_value = None
                instance.get = AsyncMock(side_effect=RuntimeError("down"))
                return await ft.health_status(probe_timeout=0.5)

        result = asyncio.run(_run())
        assert result["status"] == "connected"
        assert result["via"] == "media"
        assert result["enabled"] is True
    finally:
        cf.set_roots_for_test(None)


def test_health_status_disabled():
    async def _run():
        with patch.object(ft, "_cfg", return_value={"enabled": False, "base_url": "http://x"}):
            return await ft.health_status(probe_timeout=0.2)

    result = asyncio.run(_run())
    assert result["status"] == "disabled"
    assert result["enabled"] is False
