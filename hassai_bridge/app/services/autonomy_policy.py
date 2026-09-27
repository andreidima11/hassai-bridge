"""Granular autonomy policy layered above Settings tool groups.

Settings remain the hard ceiling — this module cannot enable a disabled tool.
"""

from __future__ import annotations

import time
from typing import Iterable

ALLOW = "allow"
ASK = "ask"
DENY = "deny"

# Domains that always ask unless explicitly allow-listed in config.
_HIGH_RISK_DOMAINS = frozenset({
    "lock", "alarm_control_panel", "cover",  # cover often garage
})
_HIGH_RISK_SERVICES = frozenset({
    "lock", "unlock", "alarm_arm_away", "alarm_disarm", "open_cover",
})
_ALWAYS_ASK_TOOLS = frozenset({
    "ha_delete_automation", "ha_delete_script", "ha_delete_scene",
    "ha_write_file", "ha_replace_in_file", "ha_recorder_purge",
    "ha_recorder_purge_entities", "ha_hacs_install", "ha_hacs_remove",
    "media_delete", "hassai_set_setting",
})
_ALWAYS_DENY_TOOLS = frozenset()  # reserved for explicit config denies

# Rate limit: proactive actions per hour
_PROACTIVE_HITS: dict[str, list[float]] = {}


def _policy_cfg(cfg: dict | None) -> dict:
    raw = (cfg or {}).get("autonomy_policy")
    return dict(raw) if isinstance(raw, dict) else {}


def decide(
    *,
    tool: str,
    domain: str = "",
    service: str = "",
    entity_ids: Iterable[str] | None = None,
    cfg: dict | None = None,
    user_id: str = "",
    proactive: bool = False,
) -> str:
    """Return allow | ask | deny."""
    tool = str(tool or "").strip()
    domain = str(domain or "").strip().lower()
    service = str(service or "").strip().lower()
    eids = [str(e).strip() for e in (entity_ids or []) if str(e).strip()]
    pol = _policy_cfg(cfg)

    # Explicit deny lists
    deny_tools = set(pol.get("deny_tools") or ()) | _ALWAYS_DENY_TOOLS
    if tool in deny_tools:
        return DENY
    deny_entities = {str(x).lower() for x in (pol.get("deny_entities") or [])}
    if any(e.lower() in deny_entities for e in eids):
        return DENY
    deny_domains = {str(x).lower() for x in (pol.get("deny_domains") or [])}
    if domain and domain in deny_domains:
        return DENY

    # Time window deny (quiet hours) for proactive only by default
    if proactive and _in_quiet_hours(pol):
        return DENY

    # Settings ceiling: if HA control group off, deny mutations
    if tool.startswith("ha_") and tool not in {"ha_list_entities", "ha_get_state", "ha_list_areas"}:
        try:
            from services import ha_tool_access as hta
            if not hta.tool_enabled(tool, cfg or {}):
                return DENY
        except Exception:
            pass

    ask_tools = set(pol.get("ask_tools") or ()) | _ALWAYS_ASK_TOOLS
    if tool in ask_tools:
        return ASK

    allow_domains = {str(x).lower() for x in (pol.get("allow_domains") or [])}
    ask_domains = {str(x).lower() for x in (pol.get("ask_domains") or [])} | _HIGH_RISK_DOMAINS
    ask_services = {str(x).lower() for x in (pol.get("ask_services") or [])} | _HIGH_RISK_SERVICES

    # Garage covers often entity_id contains garage
    if domain == "cover" and any("garage" in e.lower() or "poarta" in e.lower() or "poart" in e.lower() for e in eids):
        return ASK

    if service in ask_services and domain not in allow_domains:
        return ASK
    if domain in ask_domains and domain not in allow_domains:
        # Lights/switches should stay allow even if cover is ask — only when domain matches
        if domain in {"lock", "alarm_control_panel"}:
            return ASK
        if domain == "cover" and pol.get("covers_ask", True) is not False:
            return ASK

    if proactive:
        if not bool(pol.get("proactive_enabled", False)):
            return ASK  # suggest only — caller should not execute
        if not _within_surprise_budget(user_id, pol):
            return DENY
        # Proactive mutations only for low-risk reversible domains
        if domain not in {"light", "switch", "scene", "input_boolean"} and domain not in allow_domains:
            return ASK

    # Default: reads and common reversible controls
    if tool in {"ha_list_entities", "ha_get_state", "ha_list_areas", "ha_explain_event"}:
        return ALLOW
    if domain in {"light", "switch", "fan", "scene", "script", "input_boolean", "media_player", "climate"}:
        return ALLOW
    if tool == "ha_call_service":
        return ALLOW
    return ALLOW


def _in_quiet_hours(pol: dict) -> bool:
    quiet = pol.get("quiet_hours")
    if not isinstance(quiet, dict):
        return False
    try:
        start = int(quiet.get("start", 22))
        end = int(quiet.get("end", 7))
    except (TypeError, ValueError):
        return False
    hour = time.localtime().tm_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _within_surprise_budget(user_id: str, pol: dict) -> bool:
    try:
        budget = int(pol.get("surprise_budget_per_hour") or 3)
    except (TypeError, ValueError):
        budget = 3
    budget = max(0, min(budget, 20))
    if budget == 0:
        return False
    uid = str(user_id or "default")
    now = time.time()
    hits = [t for t in _PROACTIVE_HITS.get(uid, []) if now - t < 3600]
    if len(hits) >= budget:
        _PROACTIVE_HITS[uid] = hits
        return False
    hits.append(now)
    _PROACTIVE_HITS[uid] = hits
    return True


def record_proactive_hit(user_id: str) -> None:
    uid = str(user_id or "default")
    _PROACTIVE_HITS.setdefault(uid, []).append(time.time())
