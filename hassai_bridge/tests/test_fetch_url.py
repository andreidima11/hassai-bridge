"""fetch_url tool — budget, routing, and invoke handler."""

from __future__ import annotations

import asyncio

import pytest

from routers import chat as chat_mod
from services import searxng, secondary_routing as sr, toolkits as tk


def test_max_fetches_default_and_clamp():
    assert searxng.max_fetches_per_prompt({}) == 3
    assert searxng.max_fetches_per_prompt({"searxng": {"max_fetches_per_prompt": 5}}) == 5
    assert searxng.max_fetches_per_prompt({"searxng": {"max_fetches_per_prompt": 0}}) == 1
    assert searxng.max_fetches_per_prompt({"searxng": {"max_fetches_per_prompt": 99}}) == 10
    assert searxng.max_fetches_per_prompt({"searxng": {"max_fetches_per_prompt": "x"}}) == 3


def test_fetch_url_secondary_and_core():
    assert sr.tool_use_for_category("fetch_url") == "web_search"
    assert sr.secondary_handles_tools(
        {"use_for": {"web_search": True}},
        ["fetch_url"],
    ) is True
    assert tk.is_core_tool("fetch_url") is True
    assert tk.pack_for_tool("fetch_url") is None


def test_fetch_url_tool_schema_includes_budget():
    tool = chat_mod._fetch_url_tool({"searxng": {"max_fetches_per_prompt": 2}})
    assert tool["function"]["name"] == "fetch_url"
    assert "2" in tool["function"]["description"]
    assert "url" in tool["function"]["parameters"]["properties"]


def test_invoke_fetch_url_success(monkeypatch):
    async def fake_fetch(url: str) -> str:
        assert url == "https://example.com/a"
        return "Hello from the page. " * 20

    monkeypatch.setattr(chat_mod, "fetch_page_text", fake_fetch)
    budget = {"used": 0, "max": 3}
    text, used = asyncio.run(chat_mod._invoke_internal_tool(
        "fetch_url",
        {"url": "https://example.com/a", "focus": "Hello"},
        search_enabled=True,
        fetch_budget=budget,
        cfg={"searxng": {"enabled": True}},
    ))
    assert used is True
    assert budget["used"] == 1
    assert "Fetched page" in text
    assert "Hello from the page" in text
    assert "fetch_url call(s) left" in text


def test_invoke_fetch_url_rejects_bad_scheme():
    text, used = asyncio.run(chat_mod._invoke_internal_tool(
        "fetch_url",
        {"url": "ftp://evil.example/x"},
        search_enabled=True,
        fetch_budget={"used": 0, "max": 3},
        cfg={},
    ))
    assert used is False
    assert "http(s)" in text.lower()


def test_invoke_fetch_url_budget_exhausted(monkeypatch):
    called = {"n": 0}

    async def fake_fetch(url: str) -> str:
        called["n"] += 1
        return "ok"

    monkeypatch.setattr(chat_mod, "fetch_page_text", fake_fetch)
    budget = {"used": 2, "max": 2}
    text, used = asyncio.run(chat_mod._invoke_internal_tool(
        "fetch_url",
        {"url": "https://example.com"},
        search_enabled=True,
        fetch_budget=budget,
        cfg={},
    ))
    assert used is False
    assert called["n"] == 0
    assert "Fetch limit" in text


def test_invoke_fetch_url_empty_page(monkeypatch):
    async def fake_fetch(url: str) -> str:
        return ""

    monkeypatch.setattr(chat_mod, "fetch_page_text", fake_fetch)
    text, used = asyncio.run(chat_mod._invoke_internal_tool(
        "fetch_url",
        {"url": "https://example.com"},
        search_enabled=True,
        fetch_budget={"used": 0, "max": 3},
        cfg={},
    ))
    assert used is True
    assert "Could not fetch" in text


def test_invoke_fetch_url_surfaces_block_reason(monkeypatch):
    async def fake_fetch(url: str) -> str:
        return "[Fetch error: HTTP 403 (Cloudflare/WAF) — site refused the request; try another URL]"

    monkeypatch.setattr(chat_mod, "fetch_page_text", fake_fetch)
    text, used = asyncio.run(chat_mod._invoke_internal_tool(
        "fetch_url",
        {"url": "https://blocked.example"},
        search_enabled=True,
        fetch_budget={"used": 0, "max": 3},
        cfg={},
    ))
    assert used is True
    assert "Fetch error" in text
    assert "403" in text
    assert "another URL" in text.lower() or "different URL" in text


def test_search_instruction_mentions_fetch():
    hint = chat_mod._build_search_instruction({
        "knowledge_cutoff": "2024-01",
        "searxng": {"max_searches_per_prompt": 3, "max_fetches_per_prompt": 2},
    })
    assert "fetch_url" in hint
    assert "2" in hint
