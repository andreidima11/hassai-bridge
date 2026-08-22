"""Per-group enable flags for the add-on's own tools (Settings UI).

Mirrors ha_tool_access, but for the tools that let the assistant act on HASSAI
Bridge itself instead of on Home Assistant.
"""

from __future__ import annotations

# Settings keys (bridge_tools.<key>) — all default True when missing.
GROUP_KEYS: dict[str, str] = {
    "memory": "Read and write the assistant's long-term memory",
    "status": "Read own version, provider, settings and usage",
    "control": "Change own settings, provider and model",
}

DEFAULT_BRIDGE_TOOLS: dict[str, bool] = {k: True for k in GROUP_KEYS}


def merged_bridge_tools_config(cfg: dict | None) -> dict[str, bool]:
    raw = (cfg or {}).get("bridge_tools")
    raw = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_BRIDGE_TOOLS)
    for key in GROUP_KEYS:
        if key in raw:
            out[key] = bool(raw[key])
    return out


def group_enabled(group: str, cfg: dict | None) -> bool:
    return merged_bridge_tools_config(cfg).get(group, True)
