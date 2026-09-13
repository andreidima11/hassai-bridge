"""Official Joke API tools."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from services import jokes as jk
from services import secondary_routing as sr
from services import toolkits as tk


def test_normalize_type_and_count():
    assert jk.normalize_type("Programming") == "programming"
    assert jk.normalize_type("knock knock") == "knock-knock"
    assert jk.normalize_type("any") == ""
    assert jk.normalize_count(3) == 3
    assert jk.normalize_count(99) == 10
    assert jk.normalize_count("x") == 1


def test_tools_are_core():
    assert tk.is_core_tool("tell_joke") is True
    assert tk.is_core_tool("joke_types") is True
    assert tk.pack_for_tool("tell_joke") is None
    assert sr.tool_use_for_category("joke_types") == "web_search"


def test_tell_joke_mocked():
    async def _run():
        with patch.object(
            jk,
            "_get_json",
            new=AsyncMock(
                return_value={
                    "type": "programming",
                    "setup": "Why do programmers prefer dark mode?",
                    "punchline": "Because light attracts bugs.",
                    "id": 1,
                }
            ),
        ):
            text = await jk.tell(joke_type="programming")
            assert "dark mode" in text
            assert "bugs" in text

    asyncio.run(_run())


def test_invoke_tell_joke(monkeypatch):
    from routers import chat as chat_mod

    async def _fake(*, joke_type=None, count=1):
        return f"joke {joke_type} x{count}"

    monkeypatch.setattr(chat_mod.jokes_api, "tell", _fake)
    text, used = asyncio.run(
        chat_mod._invoke_internal_tool(
            "tell_joke",
            {"type": "dad", "count": 2},
            search_enabled=False,
        )
    )
    assert used is False
    assert "joke dad x2" in text
