"""Human-like web pacing and search/fetch behaviour."""

from __future__ import annotations

import asyncio
import time

import pytest

from services import web_pace as pace
from services import web_scraper as ws


@pytest.fixture(autouse=True)
def _reset_pace():
    pace.reset_pace_for_tests()
    yield
    pace.reset_pace_for_tests()


def test_accept_language_ro():
    assert "ro-RO" in pace.accept_language_header({"language": "ro"})


def test_accept_language_en():
    assert pace.accept_language_header({"language": "en"}).startswith("en-US")


def test_browser_headers_referer():
    h = pace.browser_headers(referer="https://example.com/search", cfg={"language": "ro"})
    assert h["Referer"].startswith("https://example.com")
    assert h["Sec-Fetch-Site"] == "cross-site"
    assert "Cache-Control" not in h
    assert "ro-RO" in h["Accept-Language"]


def test_min_interval_clamps():
    assert pace.min_fetch_interval_ms({"searxng": {"min_fetch_interval_ms": -1}}) == 0
    assert pace.min_fetch_interval_ms({"searxng": {"min_fetch_interval_ms": 99_999}}) == 30_000
    assert pace.min_search_interval_ms({"searxng": {"min_search_interval_ms": 1500}}) == 1500


def test_pace_fetch_waits(monkeypatch):
    monkeypatch.setattr(pace, "min_fetch_interval_ms", lambda cfg=None: 50)
    monkeypatch.setattr(pace.random, "uniform", lambda a, b: 0.0)

    async def run():
        t0 = time.monotonic()
        await pace.pace_fetch({})
        await pace.pace_fetch({})
        return time.monotonic() - t0

    elapsed = asyncio.run(run())
    assert elapsed >= 0.045


def test_search_and_fetch_no_auto_fetch(monkeypatch):
    async def fake_search(query: str):
        return [{
            "title": "Example",
            "url": "https://example.com/a",
            "snippet": "Hello world snippet with enough words for display.",
            "confidence": 0.8,
            "authority": 0.5,
        }]

    called = {"n": 0}

    async def fake_fetch(url: str, *, referer=None):
        called["n"] += 1
        return "should not fetch"

    monkeypatch.setattr(ws, "load_config", lambda: {
        "language": "ro",
        "searxng": {
            "enabled": True,
            "fetch_page_content": False,
            "max_pages_to_fetch": 0,
            "base_url": "http://searx.local",
        },
    })
    import services.searxng as sx
    monkeypatch.setattr(sx, "search", fake_search)
    monkeypatch.setattr(ws, "fetch_page_text", fake_fetch)

    out = asyncio.run(ws.search_and_fetch("hello world"))
    assert "## Search hits" in out
    assert "URL: https://example.com/a" in out
    assert "snippets only" in out
    assert called["n"] == 0


def test_search_and_fetch_two_pages_max(monkeypatch):
    async def fake_search(query: str):
        return [
            {
                "title": "One",
                "url": "https://example.com/1",
                "snippet": "short",
                "confidence": 0.4,
                "authority": 0.4,
            },
            {
                "title": "Two",
                "url": "https://example.com/2",
                "snippet": "short",
                "confidence": 0.4,
                "authority": 0.4,
            },
            {
                "title": "Three",
                "url": "https://example.com/3",
                "snippet": "short",
                "confidence": 0.4,
                "authority": 0.4,
            },
        ]

    fetched = []

    async def fake_fetch(url: str, *, referer=None):
        fetched.append(url)
        return "Article body about the topic with enough text to pass." * 3

    monkeypatch.setattr(ws, "load_config", lambda: {
        "language": "en",
        "searxng": {
            "enabled": True,
            "fetch_page_content": True,
            "max_pages_to_fetch": 9,  # should clamp to 2
            "base_url": "http://searx.local",
            "max_page_chars": 4000,
        },
    })
    import services.searxng as sx
    monkeypatch.setattr(sx, "search", fake_search)
    monkeypatch.setattr(ws, "fetch_page_text", fake_fetch)

    out = asyncio.run(ws.search_and_fetch("topic"))
    assert len(fetched) == 2
    assert fetched[0] == "https://example.com/1"
    assert fetched[1] == "https://example.com/2"
    assert "## Opened pages" in out
    assert "Content: One" in out
    assert "Content: Two" in out
    assert "Content: Three" not in out


def test_search_and_fetch_fallback_on_error(monkeypatch):
    async def fake_search(query: str):
        return [
            {
                "title": "Blocked",
                "url": "https://example.com/blocked",
                "snippet": "nope",
                "confidence": 0.9,
                "authority": 0.9,
            },
            {
                "title": "Good",
                "url": "https://example.com/good",
                "snippet": "yes",
                "confidence": 0.5,
                "authority": 0.5,
            },
        ]

    async def fake_fetch(url: str, *, referer=None):
        if "blocked" in url:
            return ws._fetch_error("HTTP 403 (Cloudflare/WAF)")
        return "Useful article body about the topic here with enough characters." * 2

    monkeypatch.setattr(ws, "load_config", lambda: {
        "language": "en",
        "searxng": {
            "enabled": True,
            "fetch_page_content": True,
            "max_pages_to_fetch": 1,
            "base_url": "http://searx.local",
            "max_page_chars": 4000,
        },
    })
    import services.searxng as sx
    monkeypatch.setattr(sx, "search", fake_search)
    monkeypatch.setattr(ws, "fetch_page_text", fake_fetch)

    out = asyncio.run(ws.search_and_fetch("topic"))
    assert "## Opened pages" in out
    assert "Content: Good" in out
    assert "Page open notes" in out
    assert "blocked" in out.lower() or "403" in out


def test_max_searches_default_is_two():
    from services import searxng
    assert searxng.max_searches_per_prompt({}) == 2
    assert searxng.max_fetches_per_prompt({}) == 3
