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

FETCH_ERROR_PREFIX = "[Fetch error:"

# Soft-block / bot-challenge markers (status 200 but no useful article body).
_BLOCK_MARKERS = (
    "just a moment",
    "checking your browser",
    "cf-browser-verification",
    "cf-challenge",
    "attention required! | cloudflare",
    "enable javascript and cookies to continue",
    "please verify you are a human",
    "access denied",
    "request blocked",
    "sorry, you have been blocked",
    "unusual traffic from your computer network",
    "captcha",
    "bot detection",
    "perimeterx",
    "datadome",
)


def is_fetch_error(text: str | None) -> bool:
    return bool(text) and str(text).startswith(FETCH_ERROR_PREFIX)


def _fetch_error(reason: str) -> str:
    clean = " ".join(str(reason or "unknown").split())[:200]
    return f"{FETCH_ERROR_PREFIX} {clean}]"


def _looks_like_block_page(html_raw: str, headers: dict | None = None) -> str | None:
    """Return a short reason if the response is a bot/WAF challenge, else None."""
    headers = headers or {}
    server = str(headers.get("server") or "").lower()
    lower = (html_raw or "")[:8000].lower()
    title_m = re.search(r"<title[^>]*>(.*?)</title>", lower, re.I | re.S)
    title = (title_m.group(1) if title_m else "").strip()
    if "cloudflare" in server or "cf-ray" in {k.lower() for k in headers}:
        if any(m in lower for m in ("just a moment", "cf-browser-verification", "cf-challenge", "attention required")):
            return "Cloudflare bot challenge"
    for marker in _BLOCK_MARKERS:
        if marker in lower or marker in title:
            if marker in ("captcha", "access denied") and len(html_raw or "") > 50_000:
                # Long pages mentioning captcha in footers are usually real articles.
                continue
            return f"site blocked automated access ({marker})"
    # Very short HTML with challenge-ish title
    if len((html_raw or "").strip()) < 2500 and any(
        w in title for w in ("access denied", "forbidden", "just a moment", "attention required", "blocked")
    ):
        return f"blocked page ({title[:80] or 'empty'})"
    return None


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
    """Fetch a web page and extract text. On failure return ``[Fetch error: …]`` (not empty)."""
    if is_internal_url(url, dns_fail_closed=True):
        log.warning(f"SSRF blocked: {url[:80]}")
        return _fetch_error("blocked private/internal URL")

    cfg = load_config()["searxng"]
    max_chars = cfg.get("max_page_chars", 4000)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9,ro;q=0.8",
        # Do not force "br" — without brotli installed, some servers return
        # undecodable bodies and every page looks empty.
        "Cache-Control": "no-cache",
        "Upgrade-Insecure-Requests": "1",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, max_redirects=5) as client:
            resp = await client.get(url, headers=headers)
            # Check redirects for SSRF
            chain = list(getattr(resp, "history", []) or []) + [resp]
            if any(is_internal_url(str(r.url), dns_fail_closed=True) for r in chain):
                log.warning(f"SSRF blocked redirect chain: {url[:80]}")
                return _fetch_error("blocked private/internal redirect")
            content_type = resp.headers.get("content-type", "")
            if resp.status_code >= 400:
                reason = f"HTTP {resp.status_code}"
                # Soft body hint for common WAF pages
                body_snip = (resp.text or "")[:2000].lower()
                if "cloudflare" in body_snip or "cf-ray" in {k.lower() for k in resp.headers}:
                    reason += " (Cloudflare/WAF)"
                elif "captcha" in body_snip:
                    reason += " (captcha)"
                elif "access denied" in body_snip or "forbidden" in body_snip:
                    reason += " (access denied)"
                log.warning("Fetch %s for %s", reason, url[:80])
                return _fetch_error(f"{reason} — site refused the request; try another URL")
            if "text/html" not in content_type and "text/plain" not in content_type:
                return _fetch_error(f"non-text content ({content_type or 'unknown'})")
            html_raw = resp.text
            block_reason = _looks_like_block_page(html_raw, dict(resp.headers))
            if block_reason:
                log.warning("Fetch blocked page for %s: %s", url[:80], block_reason)
                return _fetch_error(f"{block_reason} — try another URL")
    except httpx.TimeoutException:
        log.warning(f"Timeout fetching: {url[:60]}")
        return _fetch_error("timeout after 15s")
    except Exception as e:
        log.error(f"Fetch error for {url[:60]}: {e}")
        return _fetch_error(str(e)[:160])

    if not html_raw or len(html_raw) > 2_000_000:
        return _fetch_error("empty or oversized page")

    # Try trafilatura first, then basic extractor
    text = _extract_main_content(html_raw)
    if not text:
        extractor = _TextExtractor()
        extractor.feed(html_raw)
        text = extractor.get_text()

    if not text or len(text.strip()) < 40:
        # Challenge pages sometimes extract to nearly-empty strings.
        block_reason = _looks_like_block_page(html_raw, {})
        if block_reason:
            return _fetch_error(f"{block_reason} — little/no extractable text")
        return _fetch_error("no extractable text on page")

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Content truncated]"
    return text


async def search_and_fetch(query: str) -> str:
    """Search with SearXNG, optionally fetch pages, with relevance extraction and sources."""
    from services.searxng import health_check, search

    cfg = load_config().get("searxng") if isinstance(load_config().get("searxng"), dict) else {}
    if not cfg.get("enabled"):
        return (
            "[Web search is disabled. Enable Settings → Search (SearXNG) and set the base URL.]"
        )

    results = await search(query)
    if not results:
        base = (cfg.get("base_url") or "").rstrip("/") or "(unset)"
        try:
            ok = await health_check()
        except Exception:
            ok = False
        if not ok:
            return (
                f"[SearXNG unreachable at {base}. Check the URL, that the add-on/container "
                "is running, and that JSON format is enabled (format=json).]"
            )
        return (
            f"[No usable search results from SearXNG ({base}). "
            "The service is reachable but engines returned nothing — enable engines in SearXNG "
            "and allow the JSON format. Snippets/URLs were empty after filtering.]"
        )

    parts = []

    # Add result snippets WITH urls (required for fetch_url follow-ups)
    for i, r in enumerate(results, 1):
        title = (r.get("title") or "")[:100]
        snippet = (r.get("snippet") or "").strip()[:400]
        url = (r.get("url") or "").strip()
        confidence = r.get("confidence", 0.5)
        authority = r.get("authority", 0.5)

        line = f"{i}. {title}"
        if url:
            line += f"\n   URL: {url}"
        if snippet:
            line += f"\n   {snippet}"
        badges = []
        if confidence >= 0.7:
            badges.append("high-confidence")
        if authority >= 0.85:
            badges.append("trusted-source")
        if badges:
            line += f"\n   ({', '.join(badges)})"
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
            skipped = []
            for url, page_text in zip(urls_to_fetch, page_texts):
                if isinstance(page_text, Exception):
                    log.debug(f"Could not fetch {url[:50]}: {page_text}")
                    skipped.append(f"{url_titles[url]} ({url}): {page_text}")
                    continue
                if is_fetch_error(page_text):
                    skipped.append(f"{url_titles[url]} ({url}): {page_text}")
                    continue
                if page_text:
                    relevant = extract_relevant_paragraphs(page_text, query)
                    parts.append(f"\n--- Content: {url_titles[url]} ---\nURL: {url}\n{relevant}")
                    fetched += 1
            if skipped:
                notes = "\n".join(f"  · {s}" for s in skipped[:5])
                parts.append(
                    f"\n--- Page fetch notes ---\n"
                    f"Some results refused automated access (common with news/paywalls/Cloudflare):\n{notes}\n"
                    "Use the snippets and URLs above, or call fetch_url on a different URL."
                )
        else:
            # Sequential fetch
            fetched = 0
            skipped = []
            for url in urls_to_fetch:
                try:
                    page_text = await fetch_page_text(url)
                    if is_fetch_error(page_text):
                        skipped.append(f"{url_titles[url]} ({url}): {page_text}")
                        continue
                    if page_text:
                        relevant = extract_relevant_paragraphs(page_text, query)
                        parts.append(
                            f"\n--- Content: {url_titles[url]} ---\nURL: {url}\n{relevant}"
                        )
                        fetched += 1
                except Exception as e:
                    log.debug(f"Could not fetch {url[:50]}: {e}")
                    skipped.append(f"{url_titles[url]} ({url}): {e}")
            if skipped:
                notes = "\n".join(f"  · {s}" for s in skipped[:5])
                parts.append(
                    f"\n--- Page fetch notes ---\n"
                    f"Some results refused automated access (common with news/paywalls/Cloudflare):\n{notes}\n"
                    "Use the snippets and URLs above, or call fetch_url on a different URL."
                )
        if fetched:
            log.info(f"Fetched {fetched} pages for query: '{query[:40]}'")

    return "\n\n".join(parts)
