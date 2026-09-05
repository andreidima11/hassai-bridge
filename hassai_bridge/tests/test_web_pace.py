"""Human-like web pacing and search/fetch behaviour."""

from __future__ import annotations

import asyncio
import time

import pytest

from services import web_pace as pace
from services import web_scraper as ws
from services import searxng as sx


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


def test_rewrite_who_query():
    from services import searxng as sx
    assert sx.rewrite_search_query("cine e presedintele Romaniei") == "presedintele Romaniei"
    assert sx.rewrite_search_query("Who is the president of Romania?") == "the president of Romania"
    assert sx.is_who_query("cine este prim-ministrul")


def test_junk_youtube_demoted():
    from services import searxng as sx
    junk = {
        "title": "CINE ESTE Preşedintele României? (ep.1) - YouTube",
        "url": "https://www.youtube.com/watch?v=NYsaAMXboFM",
        "snippet": "16. 9. 2014248 tis. zhlédnutí comedy sketch",
    }
    good = {
        "title": "Președintele României",
        "url": "https://www.presidency.ro/",
        "snippet": "Președintele României, Nicușor Dan, a susținut joi o declarație.",
    }
    assert sx.is_junk_result(junk)
    assert not sx.is_junk_result(good)
    ranked = sx._rank_results([junk, good], "cine e presedintele Romaniei")
    assert ranked[0]["url"].startswith("https://www.presidency.ro")
    sat = sx.calculate_search_satisfaction(ranked, query="cine e presedintele Romaniei")
    assert sat >= 0.7


def test_parse_instant_answers():
    data = {
        "answers": ["Nicușor Dan is the President of Romania."],
        "infoboxes": [{
            "infobox": "Romania",
            "content": "Country in Europe",
            "urls": [{"url": "https://en.wikipedia.org/wiki/Romania", "title": "Wikipedia"}],
            "attributes": [{"label": "President", "value": "Nicușor Dan"}],
        }],
    }
    instant = sx._parse_instant_answers(data)
    assert instant
    assert any("Nicușor" in (i.get("text") or "") for i in instant)


def test_satisfaction_skips_open_with_instant():
    score = sx.calculate_search_satisfaction(
        [{"url": "https://example.com", "snippet": "x"}],
        instant=[{"text": "Answer here"}],
        query="who",
    )
    assert score >= 1.0


def test_satisfaction_high_for_answer_snippet():
    results = [{
        "title": "President of Romania",
        "url": "https://en.wikipedia.org/wiki/President_of_Romania",
        "snippet": "Nicușor Dan is the current President of Romania.",
        "authority": 0.87,
    }]
    score = sx.calculate_search_satisfaction(results, query="cine e presedintele Romaniei")
    assert score >= 0.7


def test_search_and_fetch_no_auto_fetch(monkeypatch):
    async def fake_bundle(query: str, categories: str = "general"):
        return {
            "instant": [],
            "results": [{
                "title": "Example",
                "url": "https://example.com/a",
                "snippet": "Hello world snippet with enough words for display.",
                "confidence": 0.8,
                "authority": 0.5,
            }],
        }

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
    monkeypatch.setattr(sx, "search_bundle", fake_bundle)
    monkeypatch.setattr(ws, "fetch_page_text", fake_fetch)

    out, sources = asyncio.run(ws.search_and_fetch("hello world"))
    assert "## Search hits" in out
    assert "URL: https://example.com/a" in out
    assert "Instant answers" not in out or "Call fetch_url" in out
    assert called["n"] == 0
    assert sources and sources[0]["site"] == "example.com"


def test_search_and_fetch_skips_open_when_snippet_enough(monkeypatch):
    async def fake_bundle(query: str, categories: str = "general"):
        return {
            "instant": [{"text": "Nicușor Dan is President of Romania.", "url": "https://wiki.example/p"}],
            "results": [{
                "title": "President",
                "url": "https://wiki.example/p",
                "snippet": "Nicușor Dan is the current President of Romania since 2025.",
                "confidence": 0.9,
                "authority": 0.87,
            }],
        }

    fetched = []

    async def fake_fetch(url: str, *, referer=None):
        fetched.append(url)
        return "body"

    monkeypatch.setattr(ws, "load_config", lambda: {
        "language": "ro",
        "searxng": {
            "enabled": True,
            "fetch_page_content": True,
            "max_pages_to_fetch": 2,
            "base_url": "http://searx.local",
        },
    })
    monkeypatch.setattr(sx, "search_bundle", fake_bundle)
    monkeypatch.setattr(ws, "fetch_page_text", fake_fetch)

    out, sources = asyncio.run(ws.search_and_fetch("cine e presedintele Romaniei"))
    assert "## Instant answers" in out
    assert "were not auto-opened" in out or "sufficient" in out
    assert fetched == []
    assert any(s["site"] == "wiki.example" for s in sources)


def test_search_and_fetch_two_pages_max(monkeypatch):
    async def fake_bundle(query: str, categories: str = "general"):
        return {
            "instant": [],
            "results": [
                {
                    "title": "One",
                    "url": "https://example.com/1",
                    "snippet": "x",
                    "confidence": 0.4,
                    "authority": 0.4,
                },
                {
                    "title": "Two",
                    "url": "https://example.com/2",
                    "snippet": "y",
                    "confidence": 0.4,
                    "authority": 0.4,
                },
                {
                    "title": "Three",
                    "url": "https://example.com/3",
                    "snippet": "z",
                    "confidence": 0.4,
                    "authority": 0.4,
                },
            ],
        }

    fetched = []

    async def fake_fetch(url: str, *, referer=None):
        fetched.append(url)
        return "Article body about the topic with enough text to pass." * 3

    monkeypatch.setattr(ws, "load_config", lambda: {
        "language": "en",
        "searxng": {
            "enabled": True,
            "fetch_page_content": True,
            "max_pages_to_fetch": 9,
            "base_url": "http://searx.local",
            "max_page_chars": 4000,
        },
    })
    monkeypatch.setattr(sx, "search_bundle", fake_bundle)
    monkeypatch.setattr(ws, "fetch_page_text", fake_fetch)
    monkeypatch.setattr(sx, "calculate_search_satisfaction", lambda *a, **k: 0.1)

    out, sources = asyncio.run(ws.search_and_fetch("topic"))
    assert len(fetched) == 2
    assert "## Opened pages" in out
    assert "Content: One" in out
    assert len(sources) >= 1


def test_search_and_fetch_fallback_on_error(monkeypatch):
    async def fake_bundle(query: str, categories: str = "general"):
        return {
            "instant": [],
            "results": [
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
            ],
        }

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
    monkeypatch.setattr(sx, "search_bundle", fake_bundle)
    monkeypatch.setattr(ws, "fetch_page_text", fake_fetch)
    monkeypatch.setattr(sx, "calculate_search_satisfaction", lambda *a, **k: 0.1)

    out, sources = asyncio.run(ws.search_and_fetch("topic"))
    assert "## Opened pages" in out
    assert "Content: Good" in out
    assert "Page open notes" in out


def test_max_searches_default_is_two():
    assert sx.max_searches_per_prompt({}) == 2
    assert sx.max_fetches_per_prompt({}) == 3


def test_site_name_from_url():
    assert sx.site_name_from_url("https://www.bbc.com/news") == "bbc.com"
