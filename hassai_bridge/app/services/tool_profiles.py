"""Intent- and provider-aware tool subsetting to cut prompt size and latency."""

from __future__ import annotations

import re

from services import ha_tool_access as hta
from services import openai_api as oai
from services import router as provider_router

PROFILE_FULL = "full"
PROFILE_AUTO = "auto"

# HA categories included per routing class when profile is auto/compact.
_ROUTE_HA_CATEGORIES: dict[str, frozenset[str] | None] = {
    "simple": frozenset({"entities", "control"}),
    "control": frozenset({"entities", "control"}),
    "deep": frozenset({
        "entities", "control", "automations", "diagnostics",
        "config_files", "registry",
    }),
    "vision": None,  # keep all user-enabled categories
}

_FRIGATE_RE = re.compile(
    r"\b(frigate|camera|cam(?:era)?s?|nvr|surveillance|recordings?|snapshot)\b",
    re.I,
)
_IMAGE_GEN_RE = re.compile(
    r"\b(draw|generate|create|make|design|imagine|picture|image|photo|logo|poster)\b",
    re.I,
)
_BRIDGE_WRITE_RE = re.compile(
    r"\b(setting|config|provider|eco.?mode|hassai|add-?on|bridge)\b",
    re.I,
)
_MEDIA_RE = re.compile(
    r"\b(media|photo|video|file|folder|share|upload|download)\b",
    re.I,
)

_FRIGATE_TOOLS = frozenset({
    "frigate_list_cameras", "frigate_events", "frigate_snapshot",
})
_BRIDGE_WRITE_TOOLS = frozenset({
    "hassai_set_setting", "hassai_switch_provider",
})
_MEDIA_TOOL_NAMES = frozenset({
    "media_list", "media_read", "media_write",
})


def tool_profile_mode(cfg: dict | None) -> str:
    perf = (cfg or {}).get("performance") if isinstance((cfg or {}).get("performance"), dict) else {}
    mode = str(perf.get("tool_profile") or PROFILE_AUTO).strip().lower()
    return mode if mode in (PROFILE_AUTO, PROFILE_FULL) else PROFILE_AUTO


def should_compact_tools(
    provider: dict | None,
    cfg: dict | None,
    *,
    eco_mode: bool = False,
) -> bool:
    if tool_profile_mode(cfg) == PROFILE_FULL:
        return False
    if eco_mode:
        return True
    return oai._is_local_provider(provider)


def route_class(user_text: str, *, has_images: bool = False, tools_active: bool = True) -> str:
    return provider_router.classify(
        user_text or "",
        has_images=has_images,
        tools_active=tools_active,
    )


def ha_categories_for_turn(
    cfg: dict | None,
    route_klass: str,
    *,
    compact: bool,
) -> set[str]:
    enabled = hta.enabled_categories(cfg)
    if not compact:
        return enabled
    subset = _ROUTE_HA_CATEGORIES.get(route_klass)
    if subset is None:
        return enabled
    return enabled & set(subset)


def _tool_name(tool: dict) -> str:
    fn = tool.get("function") if isinstance(tool.get("function"), dict) else {}
    return str(fn.get("name") or "")


def filter_chat_tools(
    tools: list[dict],
    *,
    provider: dict | None,
    cfg: dict | None,
    user_text: str,
    eco_mode: bool = False,
    route_klass: str = "simple",
    search_enabled: bool = False,
) -> tuple[list[dict], bool]:
    """Return (filtered tools, compact_prompt)."""
    compact = should_compact_tools(provider, cfg, eco_mode=eco_mode)
    if not compact:
        return list(tools), False

    text = user_text or ""
    allow_frigate = bool(_FRIGATE_RE.search(text))
    allow_image = bool(_IMAGE_GEN_RE.search(text))
    allow_bridge_write = bool(_BRIDGE_WRITE_RE.search(text))
    allow_media = bool(_MEDIA_RE.search(text))

    ha_cats = ha_categories_for_turn(cfg, route_klass, compact=True)

    out: list[dict] = []
    for tool in tools:
        name = _tool_name(tool)
        if not name:
            out.append(tool)
            continue
        if name.startswith("ha_"):
            if hta.tool_category(name) in ha_cats and hta.tool_enabled(name, cfg):
                out.append(tool)
            continue
        if name == "search_web":
            if search_enabled:
                out.append(tool)
            continue
        if name in _FRIGATE_TOOLS:
            if allow_frigate:
                out.append(tool)
            continue
        if name == "generate_image":
            if allow_image:
                out.append(tool)
            continue
        if name in _BRIDGE_WRITE_TOOLS:
            if allow_bridge_write:
                out.append(tool)
            continue
        if name in _MEDIA_TOOL_NAMES:
            if allow_media:
                out.append(tool)
            continue
        # Memory, bridge read, skills — small and usually useful.
        out.append(tool)

    return out, True


def effective_history_limit(
    cfg: dict | None,
    provider: dict | None,
    *,
    eco_mode: bool = False,
) -> int:
    perf = (cfg or {}).get("performance") if isinstance((cfg or {}).get("performance"), dict) else {}
    try:
        base = int(perf.get("history_limit", 10))
    except (TypeError, ValueError):
        base = 10
    if should_compact_tools(provider, cfg, eco_mode=eco_mode):
        try:
            local_cap = int(perf.get("local_history_limit", 6))
        except (TypeError, ValueError):
            local_cap = 6
        return min(base, local_cap)
    return base


def tool_replay_turns(cfg: dict | None, provider: dict | None, *, eco_mode: bool = False) -> int:
    perf = (cfg or {}).get("performance") if isinstance((cfg or {}).get("performance"), dict) else {}
    try:
        configured = int(perf.get("tool_replay_turns", 0))
    except (TypeError, ValueError):
        configured = 0
    if configured > 0:
        return configured
    if should_compact_tools(provider, cfg, eco_mode=eco_mode):
        return 3
    return 6
