"""Which tool categories a secondary provider may handle on recall rounds."""

from __future__ import annotations

from typing import Any

from services import ha_tool_access as hta

# Non-HA buckets shown in Settings → Secondary provider → Use for.
EXTRA_CATEGORY_KEYS: dict[str, str] = {
    "web_search": "Web search (SearXNG)",
    "frigate": "Cameras (Frigate events and snapshots)",
    "skills": "Skills (run_skill)",
    "media": "Media files in the add-on",
    "memory": "Long-term memory tools",
    "bridge": "HASSAI Bridge status and settings tools",
}

# Flat defaults: extras on (current behaviour), every HA category off.
DEFAULT_USE_FOR: dict[str, bool] = {
    **{k: True for k in EXTRA_CATEGORY_KEYS},
    **{k: False for k in hta.CATEGORY_KEYS},
}

_FRIGATE_TOOLS = frozenset({
    "frigate_list_cameras", "frigate_events", "frigate_snapshot",
})
_MEDIA_TOOLS = frozenset({
    "media_list", "media_read", "media_delete",
})
_MEMORY_PREFIX = "memory_"
_BRIDGE_PREFIX = "hassai_"
_HA_PREFIX = "ha_"


def use_for_category_keys() -> list[str]:
    """Stable order: extras first, then HA categories."""
    return list(EXTRA_CATEGORY_KEYS) + list(hta.CATEGORY_KEYS)


def use_for_labels() -> dict[str, str]:
    out = dict(EXTRA_CATEGORY_KEYS)
    out.update(hta.CATEGORY_KEYS)
    return out


def merged_use_for(secondary: dict | None) -> dict[str, bool]:
    """Merge stored secondary.use_for with defaults (missing keys keep defaults)."""
    out = dict(DEFAULT_USE_FOR)
    raw = (secondary or {}).get("use_for")
    if not isinstance(raw, dict):
        return out
    for key in out:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def normalize_use_for(raw: Any) -> dict[str, bool]:
    """Validate a payload into a full use_for dict."""
    out = dict(DEFAULT_USE_FOR)
    if not isinstance(raw, dict):
        return out
    for key in out:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def tool_use_for_category(name: str) -> str | None:
    """Map a tool name to a use_for key, or None if not routable via secondary flags."""
    n = (name or "").strip()
    if not n:
        return None
    if n == "search_web":
        return "web_search"
    if n in _FRIGATE_TOOLS or n.startswith("frigate_"):
        return "frigate"
    if n == "run_skill":
        return "skills"
    if n in _MEDIA_TOOLS or n.startswith("media_"):
        return "media"
    if n.startswith(_MEMORY_PREFIX):
        return "memory"
    if n.startswith(_BRIDGE_PREFIX):
        return "bridge"
    if n.startswith(_HA_PREFIX):
        return hta.tool_category(n)
    # generate_image / vision use dedicated provider fields — not use_for.
    return None


def secondary_handles_tools(secondary: dict | None, tool_names: list[str]) -> bool:
    """True when every tool in the round is allowed for this secondary."""
    if not secondary or not tool_names:
        return False
    flags = merged_use_for(secondary)
    for name in tool_names:
        cat = tool_use_for_category(name)
        if cat is None:
            return False
        if not flags.get(cat, False):
            return False
    return True
