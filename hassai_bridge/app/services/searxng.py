"""
SearXNG search service with caching, SSRF protection, domain authority ranking,
result deduplication, relevance filtering, and quality checks.
Inspired by hass_memory/brain/web_search.py.
"""

import hashlib
import logging
import re
import time
import threading
from collections import OrderedDict
from typing import Optional
from urllib.parse import urlparse

import httpx
from config import load_config

log = logging.getLogger("hassai.searxng")


def max_searches_per_prompt(cfg: dict | None = None) -> int:
    """Cap ``search_web`` calls per user message (protects SearXNG from agent loops)."""
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    sx = cfg.get("searxng") if isinstance(cfg.get("searxng"), dict) else {}
    try:
        n = int(sx.get("max_searches_per_prompt", 2))
    except (TypeError, ValueError):
        n = 2
    return max(1, min(n, 10))


def max_fetches_per_prompt(cfg: dict | None = None) -> int:
    """Cap ``fetch_url`` calls per user message (direct page fetches)."""
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    sx = cfg.get("searxng") if isinstance(cfg.get("searxng"), dict) else {}
    try:
        n = int(sx.get("max_fetches_per_prompt", 3))
    except (TypeError, ValueError):
        n = 3
    return max(1, min(n, 10))


# ── Persistent connection pool for SearXNG ──
_sx_client: httpx.AsyncClient | None = None


def _get_sx_client(timeout: int = 15) -> httpx.AsyncClient:
    global _sx_client
    if _sx_client is None or _sx_client.is_closed:
        _sx_client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        )
    return _sx_client

# ── Search cache (TTL-based, thread-safe) ──

_SEARCH_CACHE: OrderedDict = OrderedDict()
_SEARCH_CACHE_LOCK = threading.Lock()
_CACHE_MAX_SIZE = 50


def _get_cache_ttl() -> int:
    """Get cache TTL from config (with fallback)."""
    try:
        return load_config()["searxng"].get("cache_ttl", 300)
    except Exception:
        return 300


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.strip().lower().encode()).hexdigest()[:16]


def _cache_get(query: str) -> Optional[list[dict]]:
    key = _cache_key(query)
    ttl = _get_cache_ttl()
    with _SEARCH_CACHE_LOCK:
        if key not in _SEARCH_CACHE:
            return None
        results, timestamp = _SEARCH_CACHE[key]
        if time.time() - timestamp > ttl:
            del _SEARCH_CACHE[key]
            return None
        _SEARCH_CACHE.move_to_end(key)
    log.debug(f"Cache hit for: '{query[:50]}'")
    return results


def _cache_set(query: str, results: list[dict]) -> None:
    key = _cache_key(query)
    with _SEARCH_CACHE_LOCK:
        while len(_SEARCH_CACHE) >= _CACHE_MAX_SIZE:
            _SEARCH_CACHE.popitem(last=False)
        _SEARCH_CACHE[key] = (results, time.time())


# ── SSRF protection ──

def is_internal_url(url: str, *, dns_fail_closed: bool = False) -> bool:
    """Block requests to internal/private network addresses.

    When DNS lookup fails, default is fail-open (``dns_fail_closed=False``) so
    SearXNG result lists are not wiped just because the add-on's resolver hiccups.
    Fetch paths still re-check after redirects.
    """
    try:
        import ipaddress
        import socket

        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        if parsed.username or "@" in (parsed.netloc or ""):
            return True
        host_l = hostname.lower().rstrip(".")
        if host_l in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "metadata.google.internal"):
            return True
        if host_l.endswith(".local") or host_l.endswith(".internal"):
            return True
        if host_l in ("169.254.169.254", "100.100.100.200"):
            return True
        # Literal IP in the URL
        try:
            ip = ipaddress.ip_address(hostname)
            return bool(
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            )
        except ValueError:
            pass
        try:
            infos = socket.getaddrinfo(hostname, None)
        except OSError:
            log.debug("SSRF DNS lookup failed for %s (fail_closed=%s)", hostname, dns_fail_closed)
            return bool(dns_fail_closed)
        for info in infos:
            try:
                ip = ipaddress.ip_address(info[4][0])
            except (ValueError, IndexError, TypeError):
                continue
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_reserved
                or ip.is_multicast
                or ip.is_unspecified
            ):
                return True
        return False
    except Exception:
        return True


# ── Domain authority ranking ──

_DOMAIN_AUTHORITY = {
    ".gov": 0.95, "gov.ro": 0.95, ".edu": 0.90, ".ac.uk": 0.85,
    "bbc.com": 0.92, "bbc.co.uk": 0.92, "reuters.com": 0.92, "apnews.com": 0.90,
    "theguardian.com": 0.88, "nytimes.com": 0.88, "washingtonpost.com": 0.88,
    "economist.com": 0.85, "wikipedia.org": 0.87, "arxiv.org": 0.85,
    "stackoverflow.com": 0.82, "github.com": 0.80,
    "bloomberg.com": 0.83, "cnbc.com": 0.82, "forbes.com": 0.80,
}


def get_domain_authority(url: str) -> float:
    """Score domain trustworthiness (0.0 - 1.0)."""
    if not url:
        return 0.3
    url_lower = url.lower()
    for domain, score in _DOMAIN_AUTHORITY.items():
        if domain in url_lower:
            return score
    if ".gov" in url_lower:
        return 0.85
    if ".edu" in url_lower:
        return 0.80
    if ".org" in url_lower:
        return 0.65
    return 0.50


# ── Query normalization ──

def _normalize_query(query: str) -> str:
    """Remove timestamps and noise from search query."""
    q = query.strip()
    q = re.sub(r"\b(acum|ora|now|at|la)\s+\d{1,2}:\d{2}(?::\d{2})?\b", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\d{1,2}:\d{2}(?::\d{2})?\s+\d{1,2}\s+\w+\s+\d{4}\s*$", " ", q, flags=re.IGNORECASE)
    q = re.sub(r"\s+", " ", q).strip()
    return q if q else query.strip()


# ── Text helpers ──

_DIACRITIC_MAP = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "a", "Â": "a", "Î": "i", "Ș": "s", "Ş": "s", "Ț": "t", "Ţ": "t",
})


def _fold_text(value: str) -> str:
    """Lowercase + fold common RO diacritics for matching."""
    return (value or "").translate(_DIACRITIC_MAP).lower()


def _looks_like_answer_snippet(snippet: str) -> bool:
    """Short factual blurbs (e.g. who-is answers) should not be dropped."""
    text = (snippet or "").strip()
    if len(text) < 18 or len(text) > 280:
        return False
    lower = text.lower()
    noise = ("cookie", "subscribe", "sign up", "privacy policy", "click here")
    if sum(1 for p in noise if p in lower) >= 1 and len(text) < 80:
        return False
    words = [w for w in re.split(r"\W+", text) if len(w) > 1]
    return len(words) >= 3


# ── Snippet quality check ──

def _is_snippet_quality_good(snippet: str) -> bool:
    """Filter out low-quality snippets (cookie notices, subscribe CTAs, etc.)."""
    if _looks_like_answer_snippet(snippet):
        return True
    if not snippet or len(snippet.strip()) < 50:
        return False
    snippet_lower = snippet.lower()
    noise_patterns = [
        "click here", "read more", "subscribe", "sign up",
        "cookie", "privacy policy", "terms of service",
    ]
    noise_count = sum(1 for p in noise_patterns if p in snippet_lower)
    if noise_count >= 2:
        return False
    word_count = len([w for w in snippet.split() if len(w) > 3])
    return word_count >= 5


# ── Result deduplication ──

def _deduplicate_results(results: list[dict], *, max_per_domain: int = 2) -> list[dict]:
    """Remove near-duplicate results; allow a few hits per domain (wiki/gov)."""
    domain_counts: dict[str, int] = {}
    seen_snippets: set[str] = set()
    deduplicated = []
    for result in results:
        url = (result.get("url") or "").strip()
        try:
            domain = (urlparse(url).netloc or "").lower()
        except Exception:
            domain = ""
        snippet = (result.get("snippet") or "").strip()[:100]
        snippet_hash = hashlib.md5(snippet.encode()).hexdigest()[:8] if snippet else ""

        if domain and domain_counts.get(domain, 0) >= max_per_domain:
            continue
        if snippet_hash and snippet_hash in seen_snippets:
            continue

        deduplicated.append(result)
        if domain:
            domain_counts[domain] = domain_counts.get(domain, 0) + 1
        if snippet_hash:
            seen_snippets.add(snippet_hash)

    if len(deduplicated) < len(results):
        log.debug(f"Dedup: removed {len(results) - len(deduplicated)} duplicates")
    return deduplicated


# ── Relevance scoring ──

def _score_relevance(result: dict, query: str) -> float:
    """Score a result's relevance to the query (0.0 - 1.0)."""
    query_words = {w for w in _fold_text(query).split() if len(w) > 2}
    title = _fold_text(result.get("title") or "")
    snippet = _fold_text(result.get("snippet") or "")
    url = (result.get("url") or "").lower()
    score = 0.0

    # Title match
    title_matches = sum(1 for w in query_words if w in title)
    score += min(0.4, (title_matches / max(len(query_words), 1)) * 0.4)

    # Snippet match
    snippet_matches = sum(1 for w in query_words if w in snippet)
    score += min(0.3, (snippet_matches / max(len(query_words), 1)) * 0.3)

    # Soft domain authority (don't overpower engine order)
    score += get_domain_authority(url) * 0.12

    # Snippet length / answer-like bonus
    raw_snip = (result.get("snippet") or "").strip()
    if _looks_like_answer_snippet(raw_snip):
        score += 0.12
    elif len(snippet) > 100:
        score += 0.08
    elif len(snippet) > 50:
        score += 0.04

    return min(score, 1.0)


def _filter_by_relevance(results: list[dict], query: str, threshold: float = 0.15) -> list[dict]:
    """Filter out irrelevant results."""
    scored = [(r, _score_relevance(r, query)) for r in results]
    filtered = [r for r, s in scored if s >= threshold]
    if not filtered:
        return results  # keep originals if everything was filtered
    if len(filtered) < len(results):
        log.debug(f"Relevance filter: kept {len(filtered)}/{len(results)}")
    return filtered


# ── Result ranking ──

def _rank_results(results: list[dict], query: str) -> list[dict]:
    """Soft re-rank: keep engine order strong; nudge by relevance/authority."""
    scored = []
    for i, r in enumerate(results):
        relevance = _score_relevance(r, query)
        authority = get_domain_authority(r.get("url", ""))
        # Prefer original engine position so hit #1 with a good snippet stays near top.
        position_score = max(0, (len(results) - i) / max(len(results), 1))
        combined = 0.45 * relevance + 0.15 * authority + 0.40 * position_score
        scored.append((combined, -i, r))
    scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    return [r for _, __, r in scored]


# ── Confidence scoring ──

def calculate_confidence(result: dict, query: str, rank: int = 0) -> float:
    """Calculate confidence score for a single result."""
    confidence = 0.5
    if rank == 0:
        confidence += 0.3
    elif rank == 1:
        confidence += 0.2
    elif rank <= 2:
        confidence += 0.1

    url = (result.get("url") or "").lower()
    if any(d in url for d in ["wikipedia.org", ".gov", ".edu", "bbc", "reuters"]):
        confidence += 0.2

    snippet = (result.get("snippet") or "").strip()
    if len(snippet) > 150:
        confidence += 0.15
    elif len(snippet) > 50:
        confidence += 0.05

    return min(confidence, 1.0)


# ── Search satisfaction (decide if page fetch is needed) ──

def calculate_search_satisfaction(
    results: list[dict],
    *,
    instant: list[dict] | None = None,
    query: str = "",
) -> float:
    """Check if search snippets/instant answers are sufficient (0.0 - 1.0). High = skip page fetch."""
    if instant:
        return 1.0
    if not results:
        return 0.0
    score = 0.0

    top = results[0]
    top_snip = (top.get("snippet") or "").strip()
    if _looks_like_answer_snippet(top_snip):
        score += 0.55
    elif len(top_snip) >= 80:
        score += 0.35

    if query:
        q_words = {w for w in _fold_text(query).split() if len(w) > 2}
        folded = _fold_text(top_snip)
        if q_words and sum(1 for w in q_words if w in folded) >= max(1, len(q_words) // 2):
            score += 0.25

    high_authority = sum(1 for r in results if get_domain_authority(r.get("url", "")) >= 0.85)
    if high_authority >= 1:
        score += 0.15

    avg_snippet_len = sum(len(r.get("snippet") or "") for r in results) / len(results)
    if avg_snippet_len > 120:
        score += 0.15
    elif avg_snippet_len > 60:
        score += 0.08

    return min(score, 1.0)


def _parse_instant_answers(data: dict) -> list[dict]:
    """Extract SearXNG answers + infoboxes into a compact list."""
    out: list[dict] = []
    seen: set[str] = set()

    def _add(text: str, url: str = "", title: str = "") -> None:
        clean = " ".join(str(text or "").split()).strip()
        if len(clean) < 8:
            return
        key = clean[:160].lower()
        if key in seen:
            return
        seen.add(key)
        row: dict = {"text": clean[:500]}
        if url and str(url).startswith("http"):
            row["url"] = str(url).strip()
        if title:
            row["title"] = str(title).strip()[:120]
        out.append(row)

    for ans in data.get("answers") or []:
        if isinstance(ans, str):
            _add(ans)
        elif isinstance(ans, dict):
            _add(
                ans.get("answer") or ans.get("content") or ans.get("text") or "",
                url=ans.get("url") or "",
                title=ans.get("title") or "",
            )

    for box in data.get("infoboxes") or []:
        if not isinstance(box, dict):
            continue
        title = (box.get("infobox") or box.get("title") or "").strip()
        content = (box.get("content") or box.get("answer") or "").strip()
        url = ""
        urls = box.get("urls") or []
        if isinstance(urls, list) and urls:
            first = urls[0]
            if isinstance(first, dict):
                url = first.get("url") or ""
            elif isinstance(first, str):
                url = first
        url = url or box.get("url") or ""
        if content:
            _add(f"{title}: {content}" if title and title.lower() not in content.lower() else content, url=url, title=title)
        for attr in box.get("attributes") or []:
            if not isinstance(attr, dict):
                continue
            label = (attr.get("label") or "").strip()
            value = (attr.get("value") or "").strip()
            if label and value:
                _add(f"{label}: {value}", url=url, title=title or label)

    return out[:5]


def site_name_from_url(url: str) -> str:
    """Hostname without leading www. for source chips."""
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        host = ""
    if host.startswith("www."):
        host = host[4:]
    return host or "source"


def sources_from_hits(
    results: list[dict] | None = None,
    *,
    instant: list[dict] | None = None,
    opened_urls: list[str] | None = None,
    limit: int = 8,
) -> list[dict]:
    """Build deduped source list for UI: {url, title, site}."""
    out: list[dict] = []
    seen: set[str] = set()

    def _push(url: str, title: str = "") -> None:
        url = (url or "").strip()
        if not url.startswith("http"):
            return
        site = site_name_from_url(url)
        if not site or site in seen:
            return
        seen.add(site)
        out.append({
            "url": url,
            "title": (title or site)[:120],
            "site": site,
        })

    for item in instant or []:
        _push(item.get("url") or "", item.get("title") or "")
        if len(out) >= limit:
            return out
    for url in opened_urls or []:
        _push(url)
        if len(out) >= limit:
            return out
    for r in results or []:
        _push(r.get("url") or "", r.get("title") or "")
        if len(out) >= limit:
            break
    return out


# ── Main search function ──

async def search_bundle(query: str, categories: str = "general") -> dict:
    """Search SearXNG; return ``{results, instant}`` with caching."""
    full_cfg = load_config()
    cfg = full_cfg["searxng"]
    if not cfg.get("enabled"):
        return {"results": [], "instant": []}

    query = _normalize_query(query)
    if not query:
        return {"results": [], "instant": []}

    cached = _cache_get(query)
    if cached is not None:
        if isinstance(cached, dict):
            return {
                "results": list(cached.get("results") or []),
                "instant": list(cached.get("instant") or []),
            }
        # Legacy cache entries were bare result lists
        return {"results": list(cached), "instant": []}

    from services import web_pace as pace

    await pace.pace_search(full_cfg)

    base_url = cfg["base_url"].rstrip("/")
    max_results = cfg.get("max_results", 5)
    timeout = cfg.get("search_timeout", 15)

    params = {
        "q": query,
        "format": "json",
        "categories": categories,
    }
    lang = str((full_cfg or {}).get("language") or "").strip()
    if lang and lang.lower() not in {"auto", "all"}:
        params["language"] = "ro-RO" if lang.lower() in {"ro", "ro-ro"} else (
            "en-US" if lang.lower() in {"en", "en-us"} else lang
        )

    try:
        client = _get_sx_client(timeout)
        resp = await client.get(f"{base_url}/search", params=params)
        resp.raise_for_status()
        ct = (resp.headers.get("content-type") or "").lower()
        if "json" not in ct and not (resp.text or "").lstrip().startswith(("{", "[")):
            log.error(
                "SearXNG returned non-JSON (content-type=%s). "
                "Enable format=json in SearXNG settings.",
                ct or "?",
            )
            return {"results": [], "instant": []}
        data = resp.json()
    except httpx.TimeoutException:
        log.warning(f"SearXNG timeout for: '{query[:50]}'")
        return {"results": [], "instant": []}
    except Exception as e:
        log.error(f"SearXNG error: {e}")
        return {"results": [], "instant": []}

    instant = _parse_instant_answers(data if isinstance(data, dict) else {})

    raw_results = []
    blocked = 0
    for item in data.get("results", [])[:max_results * 2]:
        url = (item.get("url") or "").strip()
        if is_internal_url(url, dns_fail_closed=False):
            blocked += 1
            log.warning(f"SSRF blocked: {url[:80]}")
            continue
        raw_results.append({
            "title": item.get("title", ""),
            "url": url,
            "snippet": item.get("content", ""),
        })

    if not raw_results and not instant:
        total = len(data.get("results") or [])
        log.warning(
            "SearXNG returned %s raw hit(s) for '%s' but none usable (ssrf_blocked=%s)",
            total,
            query[:50],
            blocked,
        )
        return {"results": [], "instant": []}

    # Quality filtering — always keep engine hit #1 if present
    quality_results = [r for r in raw_results if _is_snippet_quality_good(r.get("snippet", ""))]
    if raw_results and raw_results[0] not in quality_results:
        quality_results = [raw_results[0]] + quality_results
    if not quality_results:
        quality_results = raw_results

    deduped = _deduplicate_results(quality_results, max_per_domain=2)
    relevant = _filter_by_relevance(deduped, query) if deduped else []
    ranked = _rank_results(relevant, query)[:max_results] if relevant else []

    for i, r in enumerate(ranked):
        r["confidence"] = round(calculate_confidence(r, query, i), 2)
        r["authority"] = round(get_domain_authority(r.get("url", "")), 2)

    log.info(
        "Search '%s': %s results, %s instant (from %s raw)",
        query[:50], len(ranked), len(instant), len(raw_results),
    )

    bundle = {"results": ranked, "instant": instant}
    _cache_set(query, bundle)
    return bundle


async def search(query: str, categories: str = "general") -> list[dict]:
    """Search using SearXNG; return ranked hit list (compat wrapper)."""
    bundle = await search_bundle(query, categories=categories)
    return list(bundle.get("results") or [])


async def health_check() -> bool:
    """Check if SearXNG is reachable."""
    try:
        cfg = load_config()["searxng"]
        if not cfg.get("enabled"):
            return False
        base_url = cfg["base_url"].rstrip("/")
        client = _get_sx_client(5)
        resp = await client.get(base_url)
        return resp.status_code == 200
    except Exception:
        return False
