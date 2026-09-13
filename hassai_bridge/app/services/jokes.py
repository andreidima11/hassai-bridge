"""Jokes via Official Joke API (15dkatz) — free, no API key.

https://github.com/15dkatz/official_joke_api
https://official-joke-api.appspot.com/
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger("hassai.jokes")

_BASE = "https://official-joke-api.appspot.com"
_TIMEOUT = httpx.Timeout(12.0, connect=5.0)
_HEADERS = {
    "User-Agent": "HASSAI-Bridge/1.0 (+https://github.com/andreidima11/hassai-bridge)",
    "Accept": "application/json",
}
_KNOWN_TYPES = frozenset({"general", "knock-knock", "programming", "dad"})
_MAX_COUNT = 10


def normalize_type(raw: str | None) -> str:
    s = (raw or "").strip().lower().replace("_", "-").replace(" ", "-")
    if not s or s in {"any", "random", "all"}:
        return ""
    aliases = {
        "knockknock": "knock-knock",
        "knock": "knock-knock",
        "code": "programming",
        "coding": "programming",
        "dev": "programming",
        "programmer": "programming",
        "dad-joke": "dad",
        "dadjoke": "dad",
    }
    s = aliases.get(s, s)
    return s if s in _KNOWN_TYPES else s  # still try unknown types; API may 404


def normalize_count(raw: Any, default: int = 1) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return default
    return max(1, min(_MAX_COUNT, n))


def format_joke(row: dict[str, Any], *, index: int | None = None) -> str:
    setup = str(row.get("setup") or "").strip()
    punch = str(row.get("punchline") or "").strip()
    jtype = str(row.get("type") or "").strip()
    jid = row.get("id")
    if not setup and not punch:
        return "Error: empty joke payload."
    prefix = f"{index}. " if index is not None else ""
    meta = []
    if jtype:
        meta.append(jtype)
    if jid is not None:
        meta.append(f"#{jid}")
    head = prefix + (f"[{' · '.join(meta)}] " if meta else "")
    if setup and punch:
        return f"{head}{setup}\n→ {punch}"
    return head + (setup or punch)


async def _get_json(path: str) -> Any:
    url = f"{_BASE}{path}"
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, headers=_HEADERS) as client:
        resp = await client.get(url)
        if resp.status_code != 200:
            raise RuntimeError(f"HTTP {resp.status_code} from {url}")
        return resp.json()


async def list_types() -> str:
    try:
        data = await _get_json("/types")
    except Exception as e:
        # Fallback to known static list
        log.debug("joke types fetch failed: %s", e)
        return "Joke types: " + ", ".join(sorted(_KNOWN_TYPES))
    if isinstance(data, list):
        types = [str(x).strip() for x in data if str(x).strip()]
        return "Joke types: " + ", ".join(types) if types else "Joke types: (none)"
    return "Joke types: " + ", ".join(sorted(_KNOWN_TYPES))


async def tell(
    *,
    joke_type: str | None = None,
    count: Any = 1,
) -> str:
    n = normalize_count(count, 1)
    jtype = normalize_type(joke_type)

    try:
        if jtype:
            if n == 1:
                data = await _get_json(f"/jokes/{jtype}/random")
            elif n == 10:
                data = await _get_json(f"/jokes/{jtype}/ten")
            else:
                # API has no typed N-endpoint; fetch ten and slice, or N singles.
                if n <= 5:
                    rows = []
                    for _ in range(n):
                        row = await _get_json(f"/jokes/{jtype}/random")
                        if isinstance(row, list):
                            rows.extend(x for x in row if isinstance(x, dict))
                        elif isinstance(row, dict):
                            rows.append(row)
                    data = rows
                else:
                    data = await _get_json(f"/jokes/{jtype}/ten")
        else:
            if n == 1:
                data = await _get_json("/random_joke")
            elif n == 10:
                data = await _get_json("/random_ten")
            else:
                data = await _get_json(f"/jokes/random/{n}")
    except Exception as e:
        return f"Error: Official Joke API unavailable: {e}"

    rows: list[dict] = []
    if isinstance(data, dict):
        rows = [data]
    elif isinstance(data, list):
        rows = [x for x in data if isinstance(x, dict)]
    if not rows:
        return "Error: no jokes returned."

    rows = rows[:n]
    if len(rows) == 1:
        return format_joke(rows[0])
    return "\n\n".join(format_joke(row, index=i) for i, row in enumerate(rows, 1))


TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "tell_joke",
            "description": (
                "Tell a joke from the Official Joke API (setup + punchline). "
                "Optional type: general, programming, knock-knock, dad. "
                "Optional count 1–10. Prefer this over web search for jokes / "
                "'spune o glumă' / 'tell me a joke'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "description": "Joke category: general|programming|knock-knock|dad (default: any).",
                    },
                    "count": {
                        "type": "integer",
                        "description": "How many jokes (1–10, default 1).",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "joke_types",
            "description": "List available Official Joke API categories.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_NAMES = frozenset({"tell_joke", "joke_types"})
