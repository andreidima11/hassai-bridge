"""Song lyrics via lyrics-api (YouTube Music / Musixmatch proxy).

Public demo: https://lyrics.lewdhutao.my.eu.org
Upstream: https://github.com/imanimtiyaz20/lyrics-api (LewdHuTao fork)

Unofficial / best-effort — prefer YouTube source (more reliable on the demo).
"""

from __future__ import annotations

import logging
import os
from typing import Any
from urllib.parse import urlencode

import httpx

log = logging.getLogger("hassai.lyrics")

_DEFAULT_BASE = "https://lyrics.lewdhutao.my.eu.org"
_TIMEOUT = httpx.Timeout(20.0, connect=6.0)
_HEADERS = {
    "User-Agent": "HASSAI-Bridge/1.0 (+https://github.com/andreidima11/hassai-bridge)",
    "Accept": "application/json",
}
_MAX_LYRICS_CHARS = 4500


def api_base(cfg: dict | None = None) -> str:
    raw = ""
    if isinstance(cfg, dict):
        raw = str((cfg.get("lyrics") or {}).get("base_url") or "").strip()
    if not raw:
        raw = (os.environ.get("HASSAI_LYRICS_BASE") or "").strip()
    return (raw or _DEFAULT_BASE).rstrip("/")


def _clip(text: str, n: int = _MAX_LYRICS_CHARS) -> str:
    s = (text or "").strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


async def _get(path: str, params: dict[str, str], *, base: str) -> dict[str, Any]:
    qs = urlencode({k: v for k, v in params.items() if v})
    url = f"{base}{path}"
    if qs:
        url = f"{url}?{qs}"
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        resp = await client.get(url)
        if resp.status_code == 404:
            raise RuntimeError("not found")
        if resp.status_code == 429:
            raise RuntimeError("rate limited (429)")
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code}")
        data = resp.json()
        if not isinstance(data, dict):
            raise RuntimeError("unexpected JSON")
        # Demo sometimes wraps Spring-style errors with status 200
        if data.get("status") in (500, 400, 404) or data.get("error"):
            raise RuntimeError(str(data.get("error") or data.get("message") or "upstream error"))
        return data


def _extract(payload: dict[str, Any]) -> dict[str, str]:
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    if not isinstance(data, dict):
        return {}
    lyrics = str(data.get("lyrics") or data.get("plainLyrics") or data.get("syncedLyrics") or "").strip()
    return {
        "artist": str(data.get("artistName") or data.get("artist") or "").strip(),
        "track": str(data.get("trackName") or data.get("title") or data.get("name") or "").strip(),
        "engine": str(data.get("searchEngine") or data.get("source") or "").strip(),
        "track_id": str(data.get("trackId") or data.get("trackid") or "").strip(),
        "lyrics": lyrics,
    }


async def fetch_lyrics(
    *,
    title: str,
    artist: str | None = None,
    source: str | None = None,
    translate: str | None = None,
    cfg: dict | None = None,
) -> str:
    title_s = " ".join(str(title or "").split()).strip()
    artist_s = " ".join(str(artist or "").split()).strip()
    if not title_s:
        return "Error: need a song title (optional artist)."

    src = (source or "auto").strip().lower()
    if src in {"yt", "youtube_music", "ytmusic"}:
        src = "youtube"
    if src in {"mm", "musix"}:
        src = "musixmatch"
    if src not in {"auto", "youtube", "musixmatch"}:
        src = "auto"

    base = api_base(cfg)
    params: dict[str, str] = {"title": title_s}
    if artist_s:
        params["artist"] = artist_s
    lang = (translate or "").strip().lower()
    if lang and lang not in {"none", "off", "false"}:
        params["translate"] = lang

    order: list[str]
    if src == "youtube":
        order = ["youtube"]
    elif src == "musixmatch":
        order = ["musixmatch"]
    else:
        # YouTube first — Musixmatch often 500 on the public demo.
        order = ["youtube", "musixmatch"]

    errors: list[str] = []
    for engine in order:
        path = f"/v2/{engine}/lyrics"
        try:
            payload = await _get(path, params, base=base)
            row = _extract(payload)
            lyrics = row.get("lyrics") or ""
            if not lyrics:
                errors.append(f"{engine}: empty lyrics")
                continue
            track = row.get("track") or title_s
            artist_out = row.get("artist") or artist_s or "?"
            eng = row.get("engine") or engine
            head = f"{track} — {artist_out} ({eng})"
            body = _clip(lyrics)
            return f"{head}\n\n{body}"
        except Exception as e:
            log.debug("lyrics %s failed: %s", engine, e)
            errors.append(f"{engine}: {e}")
            continue

    detail = "; ".join(errors) if errors else "unknown"
    return (
        f"Error: could not fetch lyrics for “{title_s}”"
        + (f" / {artist_s}" if artist_s else "")
        + f" ({detail})."
    )


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "song_lyrics",
            "description": (
                "Fetch song lyrics by title (optional artist). "
                "Uses an unofficial lyrics API (YouTube Music, then Musixmatch). "
                "Prefer this over web search for 'versuri' / lyrics questions. "
                "Optional translate=ro|en|… (Musixmatch only when available)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Song title (required).",
                    },
                    "artist": {
                        "type": "string",
                        "description": "Artist name (recommended for accuracy).",
                    },
                    "source": {
                        "type": "string",
                        "description": "auto (default) | youtube | musixmatch",
                    },
                    "translate": {
                        "type": "string",
                        "description": "Optional ISO language code for translated lyrics (e.g. ro).",
                    },
                },
                "required": ["title"],
            },
        },
    },
]

TOOL_NAMES = frozenset({"song_lyrics"})
