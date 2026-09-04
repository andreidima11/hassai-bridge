"""Process-wide pacing for outbound web requests (anti-bot human-like delays)."""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import Any

import httpx

from config import load_config

log = logging.getLogger("hassai.web_pace")

_fetch_lock = asyncio.Lock()
_search_lock = asyncio.Lock()
_last_fetch_mono = 0.0
_last_search_mono = 0.0
_page_client: httpx.AsyncClient | None = None


def _sx_cfg(cfg: dict | None = None) -> dict:
    if cfg is None:
        try:
            cfg = load_config()
        except Exception:
            cfg = {}
    sx = cfg.get("searxng") if isinstance((cfg or {}).get("searxng"), dict) else {}
    return sx or {}


def min_fetch_interval_ms(cfg: dict | None = None) -> int:
    try:
        n = int(_sx_cfg(cfg).get("min_fetch_interval_ms", 2000))
    except (TypeError, ValueError):
        n = 2000
    return max(0, min(n, 30_000))


def min_search_interval_ms(cfg: dict | None = None) -> int:
    try:
        n = int(_sx_cfg(cfg).get("min_search_interval_ms", 1500))
    except (TypeError, ValueError):
        n = 1500
    return max(0, min(n, 30_000))


def accept_language_header(cfg: dict | None = None) -> str:
    """Browser-like Accept-Language from HASSAI UI language."""
    try:
        full = cfg if cfg is not None else load_config()
    except Exception:
        full = {}
    lang = str((full or {}).get("language") or "en").strip().lower()
    if lang in {"ro", "ro-ro"}:
        return "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7"
    if lang in {"en", "en-us"}:
        return "en-US,en;q=0.9,ro;q=0.5"
    return "en-US,en;q=0.9"


def browser_headers(*, referer: str | None = None, cfg: dict | None = None) -> dict[str, str]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": accept_language_header(cfg),
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none" if not referer else "cross-site",
        "Sec-Fetch-User": "?1",
    }
    if referer:
        headers["Referer"] = str(referer)[:500]
        headers["Sec-Fetch-Site"] = "cross-site"
    return headers


def get_page_client() -> httpx.AsyncClient:
    """Shared keep-alive client for page fetches (less bot-like than open/close each time)."""
    global _page_client
    if _page_client is None or _page_client.is_closed:
        _page_client = httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            max_redirects=5,
            limits=httpx.Limits(max_connections=8, max_keepalive_connections=4),
            headers=browser_headers(),
        )
    return _page_client


async def close_page_client() -> None:
    global _page_client
    if _page_client is not None and not _page_client.is_closed:
        await _page_client.aclose()
    _page_client = None


async def _wait_slot(lock: asyncio.Lock, last_attr: str, interval_ms: int) -> None:
    """Ensure at least interval_ms (+ small jitter) since the previous call of this kind."""
    global _last_fetch_mono, _last_search_mono
    if interval_ms <= 0:
        return
    async with lock:
        now = time.monotonic()
        last = _last_fetch_mono if last_attr == "fetch" else _last_search_mono
        need = interval_ms / 1000.0
        # Human-like jitter: 15–35% of the base interval
        jitter = need * random.uniform(0.15, 0.35)
        wait_for = (last + need + jitter) - now
        if wait_for > 0:
            log.debug("web pace %s: sleeping %.2fs", last_attr, wait_for)
            await asyncio.sleep(wait_for)
        stamp = time.monotonic()
        if last_attr == "fetch":
            _last_fetch_mono = stamp
        else:
            _last_search_mono = stamp


async def pace_fetch(cfg: dict | None = None) -> None:
    await _wait_slot(_fetch_lock, "fetch", min_fetch_interval_ms(cfg))


async def pace_search(cfg: dict | None = None) -> None:
    await _wait_slot(_search_lock, "search", min_search_interval_ms(cfg))


def reset_pace_for_tests() -> None:
    """Test helper — clear timers (does not close the HTTP client)."""
    global _last_fetch_mono, _last_search_mono
    _last_fetch_mono = 0.0
    _last_search_mono = 0.0
