"""song_lyrics tool tests."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from services import lyrics as ly
from services import secondary_routing as sr
from services import toolkits as tk


def test_tools_are_core():
    assert tk.is_core_tool("song_lyrics") is True
    assert tk.pack_for_tool("song_lyrics") is None
    assert sr.tool_use_for_category("song_lyrics") == "web_search"


def test_fetch_lyrics_mocked_youtube_first():
    async def _fake_get(path, params, *, base):
        assert "youtube" in path
        return {
            "data": {
                "artistName": "Alan Walker",
                "trackName": "Alone",
                "searchEngine": "YouTube",
                "lyrics": "Lost in your mind\nNever let me go",
            }
        }

    async def _run():
        with patch.object(ly, "_get", new=AsyncMock(side_effect=_fake_get)):
            text = await ly.fetch_lyrics(title="Alone", artist="Alan Walker")
            assert "Alone — Alan Walker" in text
            assert "Lost in your mind" in text

    asyncio.run(_run())


def test_fetch_lyrics_falls_back():
    calls = {"n": 0}

    async def _fake_get(path, params, *, base):
        calls["n"] += 1
        if "youtube" in path:
            raise RuntimeError("boom")
        return {
            "data": {
                "artistName": "X",
                "trackName": "Y",
                "searchEngine": "Musixmatch",
                "lyrics": "hello world",
            }
        }

    async def _run():
        with patch.object(ly, "_get", new=AsyncMock(side_effect=_fake_get)):
            text = await ly.fetch_lyrics(title="Y", artist="X")
            assert "hello world" in text
            assert calls["n"] == 2

    asyncio.run(_run())


def test_invoke_song_lyrics(monkeypatch):
    from routers import chat as chat_mod

    async def _fake(**kwargs):
        return f"lyrics {kwargs.get('title')} / {kwargs.get('artist')}"

    monkeypatch.setattr(chat_mod.lyrics_api, "fetch_lyrics", _fake)
    text, used = asyncio.run(
        chat_mod._invoke_internal_tool(
            "song_lyrics",
            {"title": "Alone", "artist": "Alan Walker"},
            search_enabled=False,
        )
    )
    assert used is False
    assert "Alone" in text
