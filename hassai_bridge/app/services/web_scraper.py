"""
Web content extraction with SSRF protection, trafilatura fallback,
relevant paragraph extraction, and sources formatting.
Inspired by hass_memory/brain/web_search.py.
"""

import logging
import re
from html.parser import HTMLParser
from typing import Optional

import httpx
from config import load_config
from services.searxng import is_internal_url

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


_DIACRITIC_MAP = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "a", "Â": "a", "Î": "i", "Ș": "s", "Ş": "s", "Ț": "t", "Ţ": "t",
})


def extract_relevant_paragraphs(page_text: str, query: str, max_chars: int = 2500) -> str:
    """Extract paragraphs relevant to the query; always keep short lead facts."""
    if not page_text or not query:
        return (page_text or "")[:max_chars]

    paragraphs = re.split(r"\n{2,}|\n(?=.{80,})", page_text)
    if len(paragraphs) <= 1:
        paragraphs = page_text.split("\n")

    stop_words = {
        "the", "and", "for", "are", "but", "not", "you", "all", "can",
        "was", "one", "our", "out", "this", "that", "with", "from",
        "have", "been", "will", "what", "when", "how", "who", "which",
        "cine", "este", "sunt", "despre", "care", "unde", "cand", "când",
        "pentru", "din", "sau", "mai", "decat", "decât", "prea",
    }
    folded_query = (query or "").translate(_DIACRITIC_MAP).lower()
    query_words = {
        w for w in folded_query.split()
        if len(w) > 2 and w not in stop_words
    }
    if not query_words:
        return page_text[:max_chars]

    # Always keep the first 1–2 lead paragraphs (often the factual answer).
    lead: list[str] = []
    for paragraph in paragraphs[:4]:
        clean = paragraph.strip()
        if len(clean) >= 20:
            lead.append(clean)
        if len(lead) >= 2:
            break

    scored = []
    for paragraph in paragraphs:
        clean = paragraph.strip()
        if len(clean) < 20:
            continue
        lower = clean.translate(_DIACRITIC_MAP).lower()
        matches = sum(1 for word in query_words if word in lower)
        length_bonus = min(len(clean) / 800, 0.25)
        score = matches + length_bonus
        if matches > 0:
            scored.append((score, clean))

    scored.sort(key=lambda x: x[0], reverse=True)
    result: list[str] = []
    chars = 0
    seen: set[str] = set()

    def _append(paragraph: str) -> bool:
        nonlocal chars
        key = paragraph[:80]
        if key in seen:
            return True
        if chars + len(paragraph) + 2 > max_chars:
            if not result:
                result.append(paragraph[:max_chars])
                seen.add(key)
                return False
            return False
        result.append(paragraph)
        seen.add(key)
        chars += len(paragraph) + 2
        return True

    for paragraph in lead:
        if not _append(paragraph):
            break
    for _, paragraph in scored:
        if not _append(paragraph):
            break

    if not result:
        return page_text[:max_chars]

    extracted = "\n\n".join(result)
    if len(extracted) < len(page_text) * 0.7:
        log.debug(f"Extracted {len(extracted)}/{len(page_text)} chars ({len(result)} paragraphs)")
    return extracted


async def fetch_page_text(url: str, *, referer: str | None = None) -> str:
    """Fetch a web page and extract text. On failure return ``[Fetch error: …]`` (not empty)."""
    from services import web_pace as pace

    if is_internal_url(url, dns_fail_closed=True):
        log.warning(f"SSRF blocked: {url[:80]}")
        return _fetch_error("blocked private/internal URL")

    full_cfg = load_config()
    cfg = full_cfg.get("searxng") if isinstance(full_cfg.get("searxng"), dict) else {}
    max_chars = cfg.get("max_page_chars", 4000)

    headers = pace.browser_headers(referer=referer, cfg=full_cfg)
    await pace.pace_fetch(full_cfg)

    html_raw = ""
    try:
        client = pace.get_page_client()
        resp = await client.get(url, headers=headers)
        chain = list(getattr(resp, "history", []) or []) + [resp]
        if any(is_internal_url(str(r.url), dns_fail_closed=True) for r in chain):
            log.warning(f"SSRF blocked redirect chain: {url[:80]}")
            return _fetch_error("blocked private/internal redirect")
        content_type = resp.headers.get("content-type", "")
        if resp.status_code >= 400:
            reason = f"HTTP {resp.status_code}"
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

    text = _extract_main_content(html_raw)
    if not text:
        extractor = _TextExtractor()
        extractor.feed(html_raw)
        text = extractor.get_text()

    if not text or len(text.strip()) < 40:
        block_reason = _looks_like_block_page(html_raw, {})
        if block_reason:
            return _fetch_error(f"{block_reason} — little/no extractable text")
        return _fetch_error("no extractable text on page")

    if len(text) > max_chars:
        text = text[:max_chars] + "\n\n[Content truncated]"
    return text


def _browse_candidates(results: list) -> list[dict]:
    """Rank http(s) hits for auto-open (confidence + authority, stable on ties)."""
    scored: list[tuple[float, int, dict]] = []
    for i, r in enumerate(results or []):
        url = (r.get("url") or "").strip()
        if not url.startswith("http"):
            continue
        try:
            conf = float(r.get("confidence", 0.5) or 0.5)
        except (TypeError, ValueError):
            conf = 0.5
        try:
            auth = float(r.get("authority", 0.5) or 0.5)
        except (TypeError, ValueError):
            auth = 0.5
        scored.append((conf + auth, -i, r))
    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
    return [r for _, __, r in scored]


async def search_and_fetch(query: str) -> tuple[str, list[dict]]:
    """Search → (optional) open pages → extract. Returns (tool_text, sources)."""
    from services.searxng import (
        calculate_search_satisfaction,
        health_check,
        search_bundle,
        sources_from_hits,
    )

    full_cfg = load_config()
    cfg = full_cfg.get("searxng") if isinstance(full_cfg.get("searxng"), dict) else {}
    if not cfg.get("enabled"):
        return (
            "[Web search is disabled. Enable Settings → Search (SearXNG) and set the base URL.]",
            [],
        )

    bundle = await search_bundle(query)
    results = list(bundle.get("results") or [])
    instant = list(bundle.get("instant") or [])
    if not results and not instant:
        base = (cfg.get("base_url") or "").rstrip("/") or "(unset)"
        try:
            ok = await health_check()
        except Exception:
            ok = False
        if not ok:
            return (
                f"[SearXNG unreachable at {base}. Check the URL, that the add-on/container "
                "is running, and that JSON format is enabled (format=json).]",
                [],
            )
        return (
            f"[No usable search results from SearXNG ({base}). "
            "The service is reachable but engines returned nothing — enable engines in SearXNG "
            "and allow the JSON format. Snippets/URLs were empty after filtering.]",
            [],
        )

    parts: list[str] = []

    if instant:
        lines = ["## Instant answers"]
        for item in instant:
            text = (item.get("text") or "").strip()
            if not text:
                continue
            line = f"- {text}"
            url = (item.get("url") or "").strip()
            if url:
                line += f"\n  URL: {url}"
            lines.append(line)
        parts.append("\n".join(lines))

    hit_lines = ["## Search hits"]
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
        hit_lines.append(line)
    if results:
        parts.append("\n\n".join(hit_lines))

    auto_fetch = cfg.get("fetch_page_content") is not False
    try:
        max_pages = int(cfg.get("max_pages_to_fetch", 2) or 0)
    except (TypeError, ValueError):
        max_pages = 2
    max_pages = max(0, min(max_pages, 2))

    satisfaction = calculate_search_satisfaction(results, instant=instant, query=query)
    skip_open = bool(instant) or satisfaction >= 0.7

    opened_urls: list[str] = []
    if not auto_fetch or max_pages < 1:
        parts.append(
            "(Tip: use Instant answers / Search hits first. Call fetch_url on one URL "
            "only if you still need more detail.)"
        )
        sources = sources_from_hits(results, instant=instant)
        return "\n\n".join(parts), sources

    if skip_open:
        parts.append(
            "(Snippets/instant answers look sufficient — pages were not auto-opened. "
            "Call fetch_url on one URL only if you still need more detail.)"
        )
        sources = sources_from_hits(results, instant=instant)
        log.info(
            "Snippet-first skip auto-open for '%s' (satisfaction=%.2f, instant=%s)",
            query[:40], satisfaction, len(instant),
        )
        return "\n\n".join(parts), sources

    opened: list[str] = []
    notes: list[str] = []
    for r in _browse_candidates(results):
        if len(opened) >= max_pages:
            break
        url = (r.get("url") or "").strip()
        title = (r.get("title") or "Page")[:80]
        try:
            page_text = await fetch_page_text(url)
            if is_fetch_error(page_text):
                notes.append(f"  · {title} ({url}): {page_text}")
                continue
            if not page_text:
                notes.append(f"  · {title} ({url}): empty page")
                continue
            relevant = extract_relevant_paragraphs(page_text, query)
            opened.append(f"--- Content: {title} ---\nURL: {url}\n{relevant}")
            opened_urls.append(url)
        except Exception as e:
            log.debug("Could not fetch %s: %s", url[:50], e)
            notes.append(f"  · {title} ({url}): {e}")

    if opened:
        parts.append("## Opened pages\n" + "\n\n".join(opened))
        log.info("Auto-opened %s page(s) for query: '%s'", len(opened), query[:40])
    if notes:
        parts.append(
            "## Page open notes\n"
            + "\n".join(notes)
            + "\nPrefer Instant answers / Search hits, or call fetch_url on a different URL."
        )
    elif not opened:
        parts.append(
            "(No pages could be opened automatically — use Instant answers / Search hits, "
            "or call fetch_url on one URL.)"
        )

    sources = sources_from_hits(results, instant=instant, opened_urls=opened_urls)
    return "\n\n".join(parts), sources
