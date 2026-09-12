"""Session grants for Settings-disabled tool groups + enable request meta-tool.

The model always sees which groups are OFF (system hint) and can call
``request_enable_tools``. Approve enables for this chat (or permanently in
Settings); Decline refuses.
"""

from __future__ import annotations

import json
from typing import Any

from services import bridge_tool_access as bta
from services import ha_tool_access as hta

TOOL_NAME = "request_enable_tools"

# session_id → set of canonical group keys (bridge:browser, ha:backups, feature:searxng, …)
_session_grants: dict[str, set[str]] = {}

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Ask the user (Approve/Decline UI) to enable a tool group that is currently "
            "OFF in Settings. Use when you need a capability that is listed as disabled. "
            "After approval, retry the real tools."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "group": {
                    "type": "string",
                    "description": (
                        "Settings group id, e.g. browser, media, memory, backups, "
                        "dashboards, searxng, frigate, or ha_<category>."
                    ),
                },
                "reason": {
                    "type": "string",
                    "description": "Short why you need it (shown to the user)",
                },
            },
            "required": ["group"],
        },
    },
}

# Short alias → canonical key
_ALIASES: dict[str, str] = {
    "browser": "bridge:browser",
    "bridge_browser": "bridge:browser",
    "media": "bridge:media",
    "memory": "bridge:memory",
    "status": "bridge:status",
    "control": "bridge:control",
    "bridge_control": "bridge:control",
    "searxng": "feature:searxng",
    "search": "feature:searxng",
    "web_search": "feature:searxng",
    "frigate": "feature:frigate",
    "cameras": "feature:frigate",
    "bridge_write": "bridge:control",
    "media_write": "bridge:media",
}
for _k in bta.GROUP_KEYS:
    _ALIASES[_k] = f"bridge:{_k}"
for _k in hta.CATEGORY_KEYS:
    _ALIASES[_k] = f"ha:{_k}"
    _ALIASES[f"ha_{_k}"] = f"ha:{_k}"
    _ALIASES[f"ha:{_k}"] = f"ha:{_k}"


def clear_session(session_id: str | None) -> None:
    sid = str(session_id or "").strip()
    if sid:
        _session_grants.pop(sid, None)


def grant_session(session_id: str | None, group_key: str) -> None:
    sid = str(session_id or "").strip()
    key = str(group_key or "").strip()
    if not sid or not key:
        return
    _session_grants.setdefault(sid, set()).add(key)


def session_grants(session_id: str | None) -> set[str]:
    sid = str(session_id or "").strip()
    if not sid:
        return set()
    return set(_session_grants.get(sid) or ())


def resolve_group(raw: str | None) -> str | None:
    text = str(raw or "").strip().lower().replace(" ", "_")
    if not text:
        return None
    if text in _ALIASES:
        return _ALIASES[text]
    if text.startswith("bridge:") or text.startswith("ha:") or text.startswith("feature:"):
        return text
    return _ALIASES.get(text)


def group_label(group_key: str) -> str:
    if group_key.startswith("bridge:"):
        k = group_key.split(":", 1)[1]
        return bta.GROUP_KEYS.get(k, k)
    if group_key.startswith("ha:"):
        k = group_key.split(":", 1)[1]
        return hta.CATEGORY_KEYS.get(k, k)
    if group_key == "feature:searxng":
        return "Web search (SearXNG)"
    if group_key == "feature:frigate":
        return "Frigate cameras"
    return group_key


def canonical_for_tool(name: str) -> str | None:
    """Settings group that gates this tool, if any."""
    n = str(name or "")
    if n == "browser_interact":
        return "bridge:browser"
    if n in {"media_list", "media_read", "media_delete"}:
        return "bridge:media"
    if n.startswith("memory_"):
        return "bridge:memory"
    if n in {"hassai_status", "hassai_get_settings", "hassai_list_providers", "hassai_usage_stats"}:
        return "bridge:status"
    if n in {"hassai_set_setting", "hassai_switch_provider"}:
        return "bridge:control"
    if n in {"search_web", "fetch_url"}:
        return "feature:searxng"
    if n.startswith("frigate_"):
        return "feature:frigate"
    if n.startswith("ha_"):
        return f"ha:{hta.tool_category(n)}"
    return None


def settings_enabled(group_key: str, cfg: dict | None) -> bool:
    cfg = cfg or {}
    if group_key.startswith("bridge:"):
        g = group_key.split(":", 1)[1]
        if bta.group_enabled(g, cfg):
            return True
        # Legacy browser.enabled still counts when bridge_tools.browser is unset/false
        if g == "browser" and bool((cfg.get("browser") or {}).get("enabled")):
            return True
        return False
    if group_key.startswith("ha:"):
        return group_key.split(":", 1)[1] in hta.enabled_categories(cfg)
    if group_key == "feature:searxng":
        return bool((cfg.get("searxng") or {}).get("enabled"))
    if group_key == "feature:frigate":
        return bool((cfg.get("frigate") or {}).get("enabled", True))
    return True


def effectively_enabled(group_key: str, cfg: dict | None, session_id: str | None) -> bool:
    if group_key in session_grants(session_id):
        return True
    return settings_enabled(group_key, cfg)


def tool_effectively_enabled(name: str, cfg: dict | None, session_id: str | None) -> bool:
    key = canonical_for_tool(name)
    if not key:
        return True
    return effectively_enabled(key, cfg, session_id)


def apply_session_overrides(cfg: dict | None, session_id: str | None) -> dict:
    """Copy of cfg with session-granted groups forced on (for tool list build)."""
    base = dict(cfg or {})
    grants = session_grants(session_id)
    if not grants:
        return base
    ha = dict(base.get("ha_tools") or {})
    bridge = dict(base.get("bridge_tools") or {})
    browser = dict(base.get("browser") or {})
    searxng = dict(base.get("searxng") or {})
    frigate = dict(base.get("frigate") or {})
    for key in grants:
        if key.startswith("ha:"):
            ha[key.split(":", 1)[1]] = True
        elif key.startswith("bridge:"):
            g = key.split(":", 1)[1]
            bridge[g] = True
            if g == "browser":
                browser["enabled"] = True
        elif key == "feature:searxng":
            searxng["enabled"] = True
        elif key == "feature:frigate":
            frigate["enabled"] = True
    base["ha_tools"] = ha
    base["bridge_tools"] = bridge
    base["browser"] = browser
    base["searxng"] = searxng
    base["frigate"] = frigate
    return base


def disabled_groups(cfg: dict | None) -> list[tuple[str, str]]:
    """List (canonical_key, label) for groups currently OFF in Settings."""
    cfg = cfg or {}
    out: list[tuple[str, str]] = []
    for g in bta.GROUP_KEYS:
        key = f"bridge:{g}"
        if not settings_enabled(key, cfg):
            out.append((key, group_label(key)))
    for g in hta.CATEGORY_KEYS:
        key = f"ha:{g}"
        if not settings_enabled(key, cfg):
            out.append((key, group_label(key)))
    if not settings_enabled("feature:searxng", cfg):
        out.append(("feature:searxng", group_label("feature:searxng")))
    if not settings_enabled("feature:frigate", cfg):
        out.append(("feature:frigate", group_label("feature:frigate")))
    return out


def system_hint(cfg: dict | None, session_id: str | None = None) -> str:
    rows = []
    for key, label in disabled_groups(cfg):
        if effectively_enabled(key, cfg, session_id):
            continue
        short = key.split(":", 1)[-1]
        rows.append(f"- {short}: {label}")
    if not rows:
        return ""
    return (
        "Tool groups currently OFF in Settings — they still exist. "
        "Never say you cannot find them or that they are unavailable. "
        f"When you need one, call the real tool or {TOOL_NAME} with group=<id> and a short reason "
        "so the user gets Approve / Decline in the chat UI. After approval, retry.\n"
        + "\n".join(rows)
    )


def persist_group_to_settings(group_key: str) -> str:
    """Turn the group on permanently in config.json. Returns status text."""
    from config import load_config, save_config

    cfg = load_config()
    if group_key.startswith("bridge:"):
        g = group_key.split(":", 1)[1]
        cfg.setdefault("bridge_tools", {})[g] = True
        if g == "browser":
            cfg.setdefault("browser", {})["enabled"] = True
    elif group_key.startswith("ha:"):
        g = group_key.split(":", 1)[1]
        cfg.setdefault("ha_tools", {})[g] = True
    elif group_key == "feature:searxng":
        cfg.setdefault("searxng", {})["enabled"] = True
    elif group_key == "feature:frigate":
        cfg.setdefault("frigate", {})["enabled"] = True
    else:
        return f"Unknown group {group_key}"
    save_config(cfg)
    return f"Saved: {group_label(group_key)} is now ON in Settings."


def approval_preview(group_key: str, reason: str = "") -> str:
    label = group_label(group_key)
    short = group_key.split(":", 1)[-1]
    bits = [f"Enable “{short}”?", label]
    if reason:
        bits.append(str(reason).strip()[:160])
    return " · ".join(bits)
