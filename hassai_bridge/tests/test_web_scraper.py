"""Web scraper fetch errors and soft-block detection."""

from __future__ import annotations

import asyncio

from services import web_scraper as ws


def test_looks_like_cloudflare_challenge():
    html = "<html><title>Just a moment...</title><body>Checking your browser before accessing</body></html>"
    reason = ws._looks_like_block_page(html, {"server": "cloudflare", "cf-ray": "abc"})
    assert reason
    assert "Cloudflare" in reason or "challenge" in reason.lower() or "just a moment" in reason.lower()


def test_looks_like_access_denied_short_page():
    html = "<html><title>Access Denied</title><body>Forbidden</body></html>"
    reason = ws._looks_like_block_page(html, {})
    assert reason


def test_real_article_not_flagged_for_footer_captcha():
    # Long article that mentions captcha in a footer should not trip the short-page heuristic.
    body = "Article paragraph about weather. " * 2000 + " We use captcha on login."
    html = f"<html><title>Weather today</title><body>{body}</body></html>"
    assert ws._looks_like_block_page(html, {}) is None


def test_is_fetch_error():
    assert ws.is_fetch_error(ws._fetch_error("HTTP 403"))
    assert not ws.is_fetch_error("normal page text")
    assert not ws.is_fetch_error("")


def test_fetch_page_text_surfaces_http_403(monkeypatch):
    class FakeResp:
        status_code = 403
        headers = {"content-type": "text/html", "server": "cloudflare"}
        text = "<html>Access Denied</html>"
        history = []
        url = "https://news.example/a"

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return FakeResp()

    monkeypatch.setattr(ws.httpx, "AsyncClient", FakeClient)
    monkeypatch.setattr(ws, "load_config", lambda: {"searxng": {"max_page_chars": 4000}})
    monkeypatch.setattr(ws, "is_internal_url", lambda url, dns_fail_closed=False: False)

    out = asyncio.run(ws.fetch_page_text("https://news.example/a"))
    assert ws.is_fetch_error(out)
    assert "403" in out


def test_search_and_fetch_includes_urls(monkeypatch):
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

    monkeypatch.setattr(ws, "load_config", lambda: {
        "searxng": {
            "enabled": True,
            "fetch_page_content": False,
            "base_url": "http://searx.local",
        },
        "performance": {},
    })

    import services.searxng as sx
    monkeypatch.setattr(sx, "search_bundle", fake_bundle)

    out, sources = asyncio.run(ws.search_and_fetch("hello world"))
    assert "## Search hits" in out
    assert "URL: https://example.com/a" in out
    assert "Example" in out
    assert sources and sources[0]["url"] == "https://example.com/a"


def test_search_disabled_message(monkeypatch):
    monkeypatch.setattr(ws, "load_config", lambda: {"searxng": {"enabled": False}})
    out, sources = asyncio.run(ws.search_and_fetch("x"))
    assert "disabled" in out.lower()
    assert sources == []
