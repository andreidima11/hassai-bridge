"""
Web content extraction with SSRF protection, trafilatura fallback,
relevant paragraph extraction, and sources formatting.
Inspired by hass_memory/brain/web_search.py.
"""

import asyncio
import html
import logging
import re
from html.parser import HTMLParser
from typing import Optional

import httpx
from config import load_config
from services.searxng import is_internal_url, get_domain_authority, calculate_search_satisfaction

log = logging.getLogger("hassai.scraper")


class _TextExtractor(HTMLParser):
    """Simple HTML-to-text extractor."""

    def __init__(self):
        super().__init__()
        self._texts: list[str] = []
        self._skip = False
        self._skip_tags = {"script", "style", "noscript", "svg", "head"}

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            self._skip = True

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            text = data.strip()
            if text:
                self._texts.append(text)

    def get_text(self) -> str:
        return "\n".join(self._texts)


def _extract_main_content(html_raw: str) -> Optional[str]:
    """Try trafilatura first (high quality), fallback to basic extractor."""
    try:
        import trafilatura
        out = trafilatura.extract(
            html_raw,
            include_comments=False,
            include_links=False,
            include_formatting=False,
        )
        if out and len(out.strip()) > 80:
            return out.strip()
    except ImportError:
        pass
    except Exception:
        pass
    return None


def extract_relevant_paragraphs(page_text: str, query: str, max_chars: int = 2500) -> str:
    """Extract only paragraphs relevant to the query (saves tokens)."""
    if not page_text or not query:
        return (page_text or "")[:max_chars]

    paragraphs = re.split(r"\n{2,}|\n(?=.{80,})", page_text)
    if len(paragraphs) <= 1:
        paragraphs = page_text.split("\n")

    stop_words = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "was", "one", "our", "out", "this", "that", "with", "from",
        "have", "been", "will", "what", "when", "how", "who", "which",
    }
    query_words = {w.lower() for w in query.split() if len(w) > 2 and w.lower() not in stop_words}
    if not query_words:
        return page_text[:max_chars]

    scored = []
    for paragraph in paragraphs:
        clean = paragraph.strip()
        if len(clean) < 40:
            continue
        lower = clean.lower()
        matches = sum(1 for word in query_words if word in lower)
        length_bonus = min(len(clean) / 500, 0.5)
        score = matches + length_bonus
        if matches > 0:
            scored.append((score, clean))

    if not scored:
        return page_text[:max_chars]

    scored.sort(key=lambda x: x[0], reverse=True)
    result = []
    chars = 0
    for score, paragraph in scored:
        if chars + len(paragraph) + 2 > max_chars:
            if not result:
                result.append(paragraph[:max_chars])
            break
        result.append(paragraph)
        chars += len(paragraph) + 2

    extracted = "\n\n".join(result)
    if len(extracted) < len(page_text) * 0.7:
        log.debug(f"Extracted {len(extracted)}/{len(page_text)} chars ({len(result)} paragraphs)")
    return extracted


async def fetch_page_text(url: str) -> str:
    """Fetch a web page and extract its text content with SSRF protection."""
    if is_internal_url(url):
        log.warning(f"SSRF blocked: {url[:80]}")
        return ""

    cfg = load_config()["searxng"]
    max_chars = cfg.get("max_page_chars", 4000)

    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, max_redirects=5) as client:
            resp = await client.get(url, headers=headers)
            # Check redirects for SSRF
            chain = list(getattr(resp, "history", []) or []) + [resp]
            if any(is_internal_url(str(r.url)) for r in chain):
                log.warning(f"SSRF blocked redirect chain: {url[:80]}")
                return ""
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return f"[Non-text content: {content_type}]"
            html_raw = resp.text
    except httpx.TimeoutException:
        log.warning(f"Timeout fetching: {url[:60]}")
        return ""
    except Exception as e:
        log.error(f"Fetch error for {url[:60]}: {e}")
        return ""

    if not html_raw or len(html_raw) > 2_000_000:
        return ""

    # Try trafilatura first, then basic extractor
    text = _extract_main_content(html_raw)
    if not text:
        extractor = _TextExtractor()
        extractor.feed(html_raw)
        text = extractor.get_text()

    if not text:
        return ""

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Content truncated]"
    return text


async def search_and_fetch(query: str) -> str:
    """Search with SearXNG, optionally fetch pages, with relevance extraction and sources."""
    from services.searxng import search

    results = await search(query)
    if not results:
        return ""

    cfg = load_config()["searxng"]

    parts = []

    # Add result snippets with confidence indicators
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "")[:100]
        snippet = (r.get("snippet") or "").strip()[:400]
        url = (r.get("url") or "").strip()
        confidence = r.get("confidence", 0.5)
        authority = r.get("authority", 0.5)

        line = f"- {title}"
        if snippet:
            line += f" — {snippet}"
        if confidence >= 0.7:
            line += " ⭐"
        if authority >= 0.85:
            line += " 🔐"
        parts.append(line)

    # Decide whether to fetch pages based on satisfaction
    satisfaction = calculate_search_satisfaction(results)
    should_fetch = cfg.get("fetch_page_content", True) and satisfaction < 0.75
    max_pages = min(cfg.get("max_pages_to_fetch", 2), 3)

    # Also check total snippet length
    total_snippet_chars = sum(len(r.get("snippet") or "") for r in results)
    if total_snippet_chars >= 600:
        should_fetch = False
        log.debug(f"Snippets sufficient ({total_snippet_chars} chars), skipping page fetch")

    if should_fetch:
        urls_to_fetch = []
        url_titles = {}
        for r in results[:max_pages]:
            url = (r.get("url") or "").strip()
            if url and url.startswith("http"):
                urls_to_fetch.append(url)
                url_titles[url] = (r.get("title") or "Page")[:80]

        parallel = load_config().get("performance", {}).get("parallel_page_fetch", True)
        if parallel and len(urls_to_fetch) > 1:
            # Fetch pages in parallel
            page_texts = await asyncio.gather(
                *[fetch_page_text(u) for u in urls_to_fetch],
                return_exceptions=True,
            )
            fetched = 0
            for url, page_text in zip(urls_to_fetch, page_texts):
                if isinstance(page_text, Exception):
                    log.debug(f"Could not fetch {url[:50]}: {page_text}")
                    continue
                if page_text:
                    relevant = extract_relevant_paragraphs(page_text, query)
                    parts.append(f"\n--- Content: {url_titles[url]} ---\n{relevant}")
                    fetched += 1
        else:
            # Sequential fetch
            fetched = 0
            for url in urls_to_fetch:
                try:
                    page_text = await fetch_page_text(url)
                    if page_text:
                        relevant = extract_relevant_paragraphs(page_text, query)
                        parts.append(f"\n--- Content: {url_titles[url]} ---\n{relevant}")
                        fetched += 1
                except Exception as e:
                    log.debug(f"Could not fetch {url[:50]}: {e}")
        if fetched:
            log.info(f"Fetched {fetched} pages for query: '{query[:40]}'")

    return "\n".join(parts)
