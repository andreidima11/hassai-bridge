"""Dynamic toolkits — lean core tools + on-demand pack activation.

When ``performance.tool_profile == "dynamic"``, chat sends only a small core
(plus an ``activate_toolkits`` meta-tool) and expands packs per turn. Settings
toggles remain a hard gate. Pack priming uses the LLM pack router (not regex).
``media_list``/``media_read`` are core when ``bridge_tools.media`` is on;
``media_delete`` requires pack ``media_write``.
"""

from __future__ import annotations

import json
import time

from services import bridge_tool_access as bta
from services import ha_tool_access as hta
from services import tool_profiles as tp

ACTIVATE_TOOL = "activate_toolkits"

PACK_FRIGATE = "frigate"
PACK_BRIDGE_WRITE = "bridge_write"
PACK_IMAGE_GEN = "image_gen"
PACK_SKILLS = "skills"
PACK_MEDIA_WRITE = "media_write"

NON_HA_PACK_KEYS: dict[str, str] = {
    PACK_FRIGATE: "Frigate cameras, events, snapshots and clips",
    PACK_BRIDGE_WRITE: "Change HASSAI settings, provider or model",
    PACK_IMAGE_GEN: "Generate images",
    PACK_SKILLS: "Run installed skills",
    PACK_MEDIA_WRITE: "Delete files in /media and /share",
}

_MEDIA_READ_NAMES = frozenset({"media_list", "media_read"})
_MEDIA_WRITE_NAMES = frozenset({"media_delete"})
_FRIGATE_NAMES = frozenset({
    "frigate_list_cameras", "frigate_events", "frigate_snapshot", "frigate_clip",
})
_BRIDGE_WRITE_NAMES = frozenset({"hassai_set_setting", "hassai_switch_provider"})
_BRIDGE_READ_NAMES = frozenset({
    "hassai_status", "hassai_get_settings", "hassai_list_providers", "hassai_usage_stats",
})
_MEMORY_PREFIX = "memory_"

_sticky: dict[str, dict] = {}
_STICKY_TTL_SEC = 30 * 60
_STICKY_MAX = 2000


def _prune_sticky(now: float | None = None) -> None:
    now = now if now is not None else time.time()
    stale = [sid for sid, row in _sticky.items() if now - float(row.get("ts") or 0) > _STICKY_TTL_SEC]
    for sid in stale:
        _sticky.pop(sid, None)
    if len(_sticky) > _STICKY_MAX:
        oldest = sorted(_sticky.items(), key=lambda kv: float(kv[1].get("ts") or 0))
        for sid, _ in oldest[: len(_sticky) - _STICKY_MAX]:
            _sticky.pop(sid, None)


def _persist_sticky(session_id: str, packs: set[str], user_id: str = "") -> None:
    try:
        from core import database as db

        db.upsert_session_state(
            user_id,
            session_id,
            db.KIND_TOOLKIT_STICKY,
            {"packs": sorted(packs), "ts": time.time()},
        )
    except Exception:
        pass


def _hydrate_sticky(session_id: str, user_id: str = "") -> set[str]:
    try:
        from core import database as db

        data = db.get_session_state(user_id, session_id, db.KIND_TOOLKIT_STICKY)
        if not data:
            return set()
        packs = {str(p).strip() for p in (data.get("packs") or []) if str(p).strip()}
        if packs:
            _sticky[session_id] = {"packs": packs, "ts": float(data.get("ts") or time.time())}
        return packs
    except Exception:
        return set()


def clear_sticky(session_id: str | None, user_id: str = "") -> None:
    sid = str(session_id or "").strip()
    if sid:
        _sticky.pop(sid, None)
        try:
            from core import database as db

            db.clear_session_state(sid, db.KIND_TOOLKIT_STICKY)
        except Exception:
            pass


def get_sticky(session_id: str | None, user_id: str = "") -> set[str]:
    sid = str(session_id or "").strip()
    if not sid:
        return set()
    _prune_sticky()
    row = _sticky.get(sid)
    if row and time.time() - float(row.get("ts") or 0) <= _STICKY_TTL_SEC:
        return set(row.get("packs") or ())
    if row:
        _sticky.pop(sid, None)
    return _hydrate_sticky(sid, user_id)


def set_sticky(
    session_id: str | None,
    packs: set[str] | list[str],
    user_id: str = "",
) -> set[str]:
    sid = str(session_id or "").strip()
    if not sid:
        return set()
    _prune_sticky()
    merged = get_sticky(sid, user_id) | {str(p).strip() for p in packs if str(p).strip()}
    _sticky[sid] = {"packs": merged, "ts": time.time()}
    _persist_sticky(sid, merged, user_id)
    return merged


def _tool_name(tool: dict) -> str:
    fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return str(fn.get("name") or "")


def pack_for_tool(name: str) -> str | None:
    if not name or name == ACTIVATE_TOOL:
        return None
    if name in _MEDIA_READ_NAMES:
        return None
    if name in _MEDIA_WRITE_NAMES:
        return PACK_MEDIA_WRITE
    if name.startswith(_MEMORY_PREFIX):
        return None
    if name in _BRIDGE_READ_NAMES:
        return None
    if name == "search_web":
        return None
    if name == "fetch_url":
        return None
    if name in _FRIGATE_NAMES:
        return PACK_FRIGATE
    if name in _BRIDGE_WRITE_NAMES:
        return PACK_BRIDGE_WRITE
    if name == "generate_image":
        return PACK_IMAGE_GEN
    if name == "run_skill":
        return PACK_SKILLS
    if name.startswith("ha_"):
        return hta.tool_category(name)
    return None


def all_pack_catalog() -> dict[str, str]:
    out = dict(hta.CATEGORY_KEYS)
    out.update(NON_HA_PACK_KEYS)
    return out


def eligible_packs(
    cfg: dict | None,
    all_tools: list[dict],
    *,
    frigate_available: bool = True,
    image_gen_available: bool = True,
    skills_available: bool = True,
) -> dict[str, str]:
    present = {_tool_name(t) for t in all_tools}
    catalog = all_pack_catalog()
    out: dict[str, str] = {}

    enabled_ha = hta.enabled_categories(cfg)
    for cat in enabled_ha:
        if any(hta.tool_category(n) == cat for n in present if n.startswith("ha_")):
            out[cat] = catalog.get(cat, cat)

    if frigate_available and (_FRIGATE_NAMES & present):
        out[PACK_FRIGATE] = catalog[PACK_FRIGATE]

    if bta.group_enabled("control", cfg) and (_BRIDGE_WRITE_NAMES & present):
        out[PACK_BRIDGE_WRITE] = catalog[PACK_BRIDGE_WRITE]

    if image_gen_available and "generate_image" in present:
        out[PACK_IMAGE_GEN] = catalog[PACK_IMAGE_GEN]

    if skills_available and "run_skill" in present:
        out[PACK_SKILLS] = catalog[PACK_SKILLS]

    if bta.group_enabled("media", cfg) and (_MEDIA_WRITE_NAMES & present):
        out[PACK_MEDIA_WRITE] = catalog[PACK_MEDIA_WRITE]

    return out


def is_core_tool(name: str) -> bool:
    if name == ACTIVATE_TOOL:
        return True
    if name in _MEDIA_READ_NAMES:
        return True
    if name.startswith(_MEMORY_PREFIX):
        return True
    if name in _BRIDGE_READ_NAMES:
        return True
    if name == "search_web":
        return True
    if name == "fetch_url":
        return True
    return False


def tools_for_packs(all_tools: list[dict], packs: set[str] | list[str]) -> list[dict]:
    want = {str(p).strip() for p in packs if str(p).strip()}
    out: list[dict] = []
    for tool in all_tools:
        name = _tool_name(tool)
        if not name or name == ACTIVATE_TOOL:
            continue
        pack = pack_for_tool(name)
        if pack is None:
            continue
        if pack in want:
            out.append(tool)
    return out


def core_tools(all_tools: list[dict]) -> list[dict]:
    out: list[dict] = []
    for tool in all_tools:
        name = _tool_name(tool)
        if is_core_tool(name) and name != ACTIVATE_TOOL:
            out.append(tool)
    return out


def build_activate_tool(eligible: dict[str, str]) -> dict:
    pack_ids = sorted(eligible.keys())
    lines = [f"- {pid}: {desc}" for pid, desc in sorted(eligible.items())]
    catalog = "\n".join(lines) if lines else "(no packs available — Settings disabled them)"
    return {
        "type": "function",
        "function": {
            "name": ACTIVATE_TOOL,
            "description": (
                "Activate Home Assistant / Frigate / image / skills / media-write tool packs "
                "needed for this request before calling those domain tools. Only packs listed "
                "below (and enabled in Settings) can be activated. Media list/read, memory, and "
                "HASSAI status tools are always available without activating. "
                "media_delete requires pack media_write.\n\nAvailable packs:\n" + catalog
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "packs": {
                        "type": "array",
                        "items": {"type": "string", "enum": pack_ids} if pack_ids else {"type": "string"},
                        "description": "Pack ids to activate for the rest of this turn.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Short reason (optional).",
                    },
                },
                "required": ["packs"],
            },
        },
    }


def resolve_dynamic_tools(
    all_tools: list[dict],
    *,
    cfg: dict | None,
    user_text: str = "",
    route_klass: str = "simple",
    session_id: str = "",
    user_id: str = "",
    provider: dict | None = None,
    primed_packs: set[str] | list[str] | None = None,
    frigate_available: bool = True,
    image_gen_available: bool = True,
    skills_available: bool = True,
) -> tuple[list[dict], set[str], dict[str, str]]:
    """Return (effective_tools, active_packs, eligible_catalog).

    ``primed_packs`` comes from the LLM pack router (not regex).
    """
    eligible = eligible_packs(
        cfg,
        all_tools,
        frigate_available=frigate_available,
        image_gen_available=image_gen_available,
        skills_available=skills_available,
    )
    sticky = get_sticky(session_id, user_id) & set(eligible)
    primed = {str(p).strip() for p in (primed_packs or []) if str(p).strip()} & set(eligible)
    active = sticky | primed

    core = core_tools(all_tools)
    packed = tools_for_packs(all_tools, active)
    activate = build_activate_tool(eligible)
    deduped = shorten_tool_descriptions(_dedupe_tools([activate, *core, *packed]))

    max_tools = tp.provider_tools_max(provider)
    if max_tools is not None and len(deduped) > max_tools:
        deduped = tp.cap_tools(
            deduped, max_tools, user_text=user_text, route_klass=route_klass,
        )
        names = {_tool_name(t) for t in deduped}
        if ACTIVATE_TOOL not in names and eligible:
            deduped = [activate] + [t for t in deduped if _tool_name(t) != ACTIVATE_TOOL]
            if len(deduped) > max_tools:
                deduped = deduped[:max_tools]
            deduped = shorten_tool_descriptions(deduped)

    return deduped, active, eligible


def expand_after_activate(
    all_tools: list[dict],
    *,
    cfg: dict | None,
    packs: list[str] | None,
    session_id: str = "",
    user_id: str = "",
    current_active: set[str] | None = None,
    provider: dict | None = None,
    user_text: str = "",
    route_klass: str = "simple",
    frigate_available: bool = True,
    image_gen_available: bool = True,
    skills_available: bool = True,
) -> tuple[list[dict], set[str], str]:
    eligible = eligible_packs(
        cfg,
        all_tools,
        frigate_available=frigate_available,
        image_gen_available=image_gen_available,
        skills_available=skills_available,
    )
    requested = [str(p).strip() for p in (packs or []) if str(p).strip()]
    allowed = [p for p in requested if p in eligible]
    denied = [p for p in requested if p not in eligible]

    active = set(current_active or ()) | set(allowed)
    active &= set(eligible)
    if session_id:
        active = set_sticky(session_id, active, user_id=user_id) & set(eligible)

    try:
        from core import database as db

        if denied:
            db.add_toolkit_audit(
                user_id=user_id,
                session_id=session_id,
                event="denied_pack",
                packs=denied,
                detail="activate_toolkits",
            )
    except Exception:
        pass

    core = core_tools(all_tools)
    packed = tools_for_packs(all_tools, active)
    activate = build_activate_tool(eligible)
    deduped = shorten_tool_descriptions(_dedupe_tools([activate, *core, *packed]))

    max_tools = tp.provider_tools_max(provider)
    if max_tools is not None and len(deduped) > max_tools:
        deduped = tp.cap_tools(
            deduped, max_tools, user_text=user_text, route_klass=route_klass,
        )

    payload = {
        "activated": sorted(allowed),
        "denied": sorted(denied),
        "active_packs": sorted(active),
        "tool_count": len(deduped),
        "tools_tokens": estimate_tools_tokens(deduped),
        "hint": (
            "Domain tools for the activated packs are now available. "
            "Continue the task with those tools."
            if allowed
            else "No new packs activated. Check pack ids against Available packs, "
            "or Settings toggles may have disabled them."
        ),
    }
    return deduped, active, json.dumps(payload)


def tool_inactive_message(name: str, eligible: dict[str, str]) -> str:
    pack = pack_for_tool(name)
    if pack and pack in eligible:
        return (
            f"Tool '{name}' is not active yet. Call {ACTIVATE_TOOL} with packs=[\"{pack}\"] "
            f"first, then retry."
        )
    if pack:
        return (
            f"Tool '{name}' belongs to pack '{pack}', which is disabled in Settings "
            f"or unavailable. Ask the user to enable it, or use another approach."
        )
    return f"Tool '{name}' is not available in the current tool list."


_DESC_MAX = 140


def estimate_tools_tokens(tools: list[dict] | None) -> int:
    if not tools:
        return 0
    try:
        raw = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return 0
    return max(0, len(raw) // 4)


def _one_line_desc(text: str, max_len: int = _DESC_MAX) -> str:
    t = " ".join(str(text or "").split())
    if not t:
        return t
    for sep in (". ", "! ", "? "):
        if sep in t:
            first = t.split(sep, 1)[0].strip()
            if len(first) >= 32:
                t = first + "."
                break
    if len(t) <= max_len:
        return t
    cut = t[: max_len - 1].rstrip(" ,;:-")
    return cut + "…"


def shorten_tool_descriptions(
    tools: list[dict],
    *,
    max_len: int = _DESC_MAX,
) -> list[dict]:
    out: list[dict] = []
    for tool in tools:
        name = _tool_name(tool)
        if name == ACTIVATE_TOOL:
            out.append(tool)
            continue
        fn = tool.get("function") if isinstance(tool.get("function"), dict) else None
        if not isinstance(fn, dict):
            out.append(tool)
            continue
        desc = str(fn.get("description") or "")
        short = _one_line_desc(desc, max_len)
        if short == desc:
            out.append(tool)
            continue
        new_fn = dict(fn)
        new_fn["description"] = short
        new_tool = dict(tool)
        new_tool["function"] = new_fn
        out.append(new_tool)
    return out


def _dedupe_tools(tools: list[dict]) -> list[dict]:
    seen: set[str] = set()
    deduped: list[dict] = []
    for tool in tools:
        name = _tool_name(tool)
        if not name or name in seen:
            continue
        seen.add(name)
        deduped.append(tool)
    return deduped
