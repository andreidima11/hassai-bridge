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
        n = int(sx.get("max_searches_per_prompt", 3))
    except (TypeError, ValueError):
        n = 3
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


# ── Snippet quality check ──

def _is_snippet_quality_good(snippet: str) -> bool:
    """Filter out low-quality snippets (cookie notices, subscribe CTAs, etc.)."""
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

def _deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove duplicate results by domain and snippet hash."""
    seen_domains: set[str] = set()
    seen_snippets: set[str] = set()
    deduplicated = []
    for result in results:
        url = (result.get("url") or "").strip()
        try:
            domain = urlparse(url).netloc
        except Exception:
            domain = ""
        snippet = (result.get("snippet") or "").strip()[:100]
        snippet_hash = hashlib.md5(snippet.encode()).hexdigest()[:8] if snippet else ""

        if domain and domain in seen_domains:
            continue
        if snippet_hash and snippet_hash in seen_snippets:
            continue

        deduplicated.append(result)
        if domain:
            seen_domains.add(domain)
        if snippet_hash:
            seen_snippets.add(snippet_hash)

    if len(deduplicated) < len(results):
        log.debug(f"Dedup: removed {len(results) - len(deduplicated)} duplicates")
    return deduplicated


# ── Relevance scoring ──

def _score_relevance(result: dict, query: str) -> float:
    """Score a result's relevance to the query (0.0 - 1.0)."""
    query_words = set(query.lower().split())
    title = (result.get("title") or "").lower()
    snippet = (result.get("snippet") or "").lower()
    url = (result.get("url") or "").lower()
    score = 0.0

    # Title match
    title_matches = sum(1 for w in query_words if w in title and len(w) > 2)
    score += min(0.4, (title_matches / max(len(query_words), 1)) * 0.4)

    # Snippet match
    snippet_matches = sum(1 for w in query_words if w in snippet and len(w) > 2)
    score += min(0.3, (snippet_matches / max(len(query_words), 1)) * 0.3)

    # Domain authority
    score += get_domain_authority(url) * 0.2

    # Snippet length bonus
    if len(snippet) > 100:
        score += 0.1
    elif len(snippet) > 50:
        score += 0.05

    return min(score, 1.0)


def _filter_by_relevance(results: list[dict], query: str, threshold: float = 0.2) -> list[dict]:
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
    """Rank results by combined relevance + authority score."""
    scored = []
    for i, r in enumerate(results):
        relevance = _score_relevance(r, query)
        authority = get_domain_authority(r.get("url", ""))
        # Combined score: 70% relevance, 20% authority, 10% position
        position_score = max(0, (10 - i) / 10)
        combined = 0.7 * relevance + 0.2 * authority + 0.1 * position_score
        scored.append((combined, r))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [r for _, r in scored]


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

def calculate_search_satisfaction(results: list[dict]) -> float:
    """Check if search snippets are sufficient (0.0 - 1.0). High = no need to fetch pages."""
    if not results:
        return 0.0
    score = 0.0

    high_authority = sum(1 for r in results if get_domain_authority(r.get("url", "")) >= 0.85)
    if high_authority >= 1:
        score += 0.5
    elif len(results) >= 3:
        score += 0.3

    avg_snippet_len = sum(len(r.get("snippet") or "") for r in results) / len(results)
    if avg_snippet_len > 150:
        score += 0.3
    elif avg_snippet_len > 80:
        score += 0.15

    if len(results) >= 4:
        score += 0.2
    elif len(results) >= 2:
        score += 0.1

    return min(score, 1.0)


# ── Main search function ──

async def search(query: str, categories: str = "general") -> list[dict]:
    """Search using SearXNG with caching, dedup, ranking, and quality filtering."""
    cfg = load_config()["searxng"]
    if not cfg.get("enabled"):
        return []

    query = _normalize_query(query)
    if not query:
        return []

    # Check cache first
    cached = _cache_get(query)
    if cached is not None:
        return cached

    base_url = cfg["base_url"].rstrip("/")
    max_results = cfg.get("max_results", 5)
    timeout = cfg.get("search_timeout", 15)

    params = {
        "q": query,
        "format": "json",
        "categories": categories,
    }

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
            return []
        data = resp.json()
    except httpx.TimeoutException:
        log.warning(f"SearXNG timeout for: '{query[:50]}'")
        return []
    except Exception as e:
        log.error(f"SearXNG error: {e}")
        return []

    raw_results = []
    blocked = 0
    for item in data.get("results", [])[:max_results * 2]:  # get extra for filtering
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

    if not raw_results:
        total = len(data.get("results") or [])
        log.warning(
            "SearXNG returned %s raw hit(s) for '%s' but none usable (ssrf_blocked=%s)",
            total,
            query[:50],
            blocked,
        )
        return []

    # Quality filtering
    quality_results = [r for r in raw_results if _is_snippet_quality_good(r.get("snippet", ""))]
    if not quality_results:
        quality_results = raw_results  # fallback to originals

    # Deduplication
    deduped = _deduplicate_results(quality_results)

    # Relevance filtering
    relevant = _filter_by_relevance(deduped, query)

    # Rank and trim
    ranked = _rank_results(relevant, query)[:max_results]

    # Add metadata
    for i, r in enumerate(ranked):
        r["confidence"] = round(calculate_confidence(r, query, i), 2)
        r["authority"] = round(get_domain_authority(r.get("url", "")), 2)

    log.info(f"Search '{query[:50]}': {len(ranked)} results (from {len(raw_results)} raw)")

    # Cache results
    _cache_set(query, ranked)
    return ranked


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
