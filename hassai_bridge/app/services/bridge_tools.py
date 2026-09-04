"""Tools that let the assistant inspect and control HASSAI Bridge itself.

The model already knows how to drive Home Assistant; without these it has no
idea it *is* an add-on with its own version, providers, memory and settings, so
questions like "what model are you on" or "turn your web search on" ended in a
guess or a refusal.
"""

from __future__ import annotations

import json
import logging
import time

from config import load_config, save_config
from core.config import ADDON_VERSION, VERSION
from database import get_memory_stats, get_usage_stats
from services import bridge_tool_access as bta

log = logging.getLogger("hassai.bridge.tools")

_READ_TOOLS = frozenset({
    "hassai_status",
    "hassai_get_settings",
    "hassai_list_providers",
    "hassai_usage_stats",
})
_WRITE_TOOLS = frozenset({"hassai_set_setting", "hassai_switch_provider"})
TOOL_NAMES = _READ_TOOLS | _WRITE_TOOLS

_START_TIME = time.time()

# Sections exposed to hassai_get_settings — everything else stays hidden.
_SECTIONS = ("memory", "searxng", "frigate", "performance", "ha_tools",
             "bridge_tools", "general", "all")

_SECRET_KEYS = frozenset({"api_key", "token", "password", "secret"})


# ── Writable settings allowlist ────────────────────
# path → ("bool" | "int" | "str", *bounds)
_ALLOWED: dict[str, tuple] = {
    "language": ("enum", ("en", "ro")),
    "knowledge_cutoff": ("str", 20),
    "dynamic_greetings": ("bool",),
    "memory.enabled": ("bool",),
    "memory.auto_extract": ("bool",),
    "memory.max_memories_per_user": ("int", 50, 5000),
    "memory.auto_consolidation.enabled": ("bool",),
    "memory.auto_consolidation.schedule": ("enum", ("daily", "weekly", "interval")),
    "memory.auto_consolidation.hour": ("int", 0, 23),
    "memory.auto_consolidation.interval_hours": ("int", 1, 168),
    "searxng.enabled": ("bool",),
    "searxng.max_results": ("int", 1, 20),
    "searxng.max_searches_per_prompt": ("int", 1, 10),
    "searxng.max_fetches_per_prompt": ("int", 1, 10),
    "searxng.min_fetch_interval_ms": ("int", 0, 30000),
    "searxng.min_search_interval_ms": ("int", 0, 30000),
    "searxng.max_pages_to_fetch": ("int", 0, 1),
    "frigate.enabled": ("bool",),
    "frigate.timeout": ("int", 3, 60),
    "performance.history_limit": ("int", 2, 50),
    "performance.local_history_limit": ("int", 2, 30),
    "performance.agent_max_rounds": ("int", 2, 32),
    "performance.parallel_page_fetch": ("bool",),
    "performance.tool_profile": ("enum", ("auto", "full", "dynamic")),
    "performance.tool_replay_turns": ("int", 0, 12),
}
for _grp in ("memory", "status", "control", "media"):
    _ALLOWED[f"bridge_tools.{_grp}"] = ("bool",)


def _ha_tool_paths() -> dict[str, tuple]:
    from services import ha_tool_access as hta

    return {f"ha_tools.{key}": ("bool",) for key in hta.CATEGORY_KEYS}


def allowed_paths() -> dict[str, tuple]:
    return {**_ALLOWED, **_ha_tool_paths()}


# ── Tool specs ─────────────────────────────────────

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "hassai_status",
            "description": (
                "Report what you are running as: HASSAI Bridge add-on version, uptime, active "
                "AI provider and model, helper providers, which capabilities are switched on "
                "(memory, web search, Frigate, Home Assistant tools), and how many memories you "
                "hold for this user. Use it whenever the user asks about you, your version, "
                "your model or what you can do — do not guess."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hassai_get_settings",
            "description": (
                "Read your own add-on configuration (secrets redacted). Use it before changing "
                "a setting so you report the real current value."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "section": {
                        "type": "string",
                        "enum": list(_SECTIONS),
                        "description": "Config section, or 'all'.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hassai_set_setting",
            "description": (
                "Change one of your own add-on settings, e.g. searxng.enabled, memory.auto_extract, "
                "performance.agent_max_rounds, frigate.enabled, language, or any ha_tools.* / "
                "bridge_tools.* permission. Call hassai_get_settings first if unsure of the key. "
                "Takes effect immediately; only the keys in the allowlist can be written."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Dotted setting key, e.g. 'searxng.enabled'.",
                    },
                    "value": {
                        "type": "string",
                        "description": "New value: 'true'/'false' for switches, a number, or text.",
                    },
                },
                "required": ["path", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hassai_list_providers",
            "description": (
                "List the AI providers configured in the add-on — primary providers with their "
                "models plus the secondary/vision/image helpers — and mark which one is active."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hassai_switch_provider",
            "description": (
                "Switch which AI provider or model answers from now on. "
                "Use hassai_list_providers first to get the exact names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider": {"type": "string", "description": "Provider name or id."},
                    "model": {"type": "string", "description": "Model id on the target provider."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "hassai_usage_stats",
            "description": (
                "Token and request usage recorded by the add-on, per provider. Use it when the "
                "user asks how much they used, how many tokens went out, or which provider is busiest."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "days": {"type": "integer", "description": "Look-back window (default 30)."},
                },
            },
        },
    },
]


def build_tools(cfg: dict | None = None) -> list[dict]:
    if cfg is None:
        cfg = load_config()
    read_on = bta.group_enabled("status", cfg)
    write_on = bta.group_enabled("control", cfg)
    out = []
    for spec in TOOL_SPECS:
        name = spec["function"]["name"]
        if name in _READ_TOOLS and read_on:
            out.append(spec)
        elif name in _WRITE_TOOLS and write_on:
            out.append(spec)
    return out


def is_bridge_tool(name: str) -> bool:
    return name in TOOL_NAMES


def tool_enabled(name: str, cfg: dict | None = None) -> bool:
    if cfg is None:
        cfg = load_config()
    if name in _READ_TOOLS:
        return bta.group_enabled("status", cfg)
    if name in _WRITE_TOOLS:
        return bta.group_enabled("control", cfg)
    return False


def tool_detail(name: str, args: dict) -> str:
    args = args or {}
    if name == "hassai_get_settings":
        return str(args.get("section") or "all")
    if name == "hassai_set_setting":
        return f"{args.get('path') or ''} = {args.get('value')}".strip()
    if name == "hassai_switch_provider":
        return " ".join(
            str(v) for v in (args.get("provider"), args.get("model")) if v
        )
    if name == "hassai_usage_stats":
        return f"{args.get('days') or 30}d"
    return ""


def system_hint(cfg: dict | None = None) -> str:
    if cfg is None:
        cfg = load_config()
    read_on = bta.group_enabled("status", cfg)
    write_on = bta.group_enabled("control", cfg)

    lines = [
        f"[HASSAI Bridge] You are not a generic chatbot in a browser tab. You run as the "
        f"\"HASSAI Bridge\" Home Assistant add-on ({VERSION}) inside this user's Home Assistant "
        "install, and you act on their real home. Everything you can do — Home Assistant control, "
        "cameras, media files, web search, long-term memory — comes from tools this add-on gives "
        "you, so when the user asks what you can do, answer from your actual tool list."
    ]
    if read_on:
        lines.append(
            "You can also inspect yourself: hassai_status (version, provider, model, enabled "
            "features), hassai_get_settings, hassai_list_providers, hassai_usage_stats. Use them "
            "instead of guessing when the user asks about you."
        )
    if write_on:
        lines.append(
            "You can change yourself too: hassai_set_setting for add-on settings and tool "
            "permissions, hassai_switch_provider for the AI provider or model. "
            "The user manages this add-on, so just do it when they ask, then confirm the new value."
        )
    return "\n".join(lines)


# ── Handlers ───────────────────────────────────────

def _redact(value):
    if isinstance(value, dict):
        return {
            k: ("***" if k.lower() in _SECRET_KEYS and v else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_redact(v) for v in value]
    return value


def _uptime() -> str:
    secs = int(time.time() - _START_TIME)
    days, rem = divmod(secs, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days:
        return f"{days}d {hours}h {minutes}m"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _status(user_id: str, cfg: dict) -> str:
    from services import frigate_tools as ft
    from services import homeassistant as ha_api
    from services import memory_tools as mt
    from services import providers as pv

    active = pv.get_active_provider()
    secondary = pv.get_secondary_provider(active)
    vision = pv.get_vision_provider(active)
    image_gen = pv.resolve_image_generation_provider(active)

    lines = [
        f"HASSAI Bridge {VERSION} (add-on {ADDON_VERSION}), up {_uptime()}.",
        f"Active provider: {active.get('name') or '?'} ({active.get('type') or '?'}) — "
        f"model {active.get('model') or '?'}"
    ]
    if secondary:
        lines.append(
            f"Secondary (categories via use_for; final answer + memory use primary): "
            f"{secondary.get('name')} — {secondary.get('model')}"
        )
    if vision:
        lines.append(f"Vision: {vision.get('name')} — {vision.get('model')}")
    if image_gen:
        lines.append(f"Image generation: {image_gen.get('name')} — {image_gen.get('model')}")

    mem_cfg = cfg.get("memory") or {}
    if mem_cfg.get("enabled", True):
        stats = get_memory_stats(user_id) if user_id else {"total": 0, "by_category": {}}
        cats = ", ".join(f"{k}: {v}" for k, v in sorted(stats["by_category"].items())) or "none"
        lines.append(
            f"Memory: on ({stats['total']} memories for this user — {cats}); "
            f"auto-extract {'on' if mem_cfg.get('auto_extract', True) else 'off'}; "
            f"memory tools {'on' if mt.is_enabled(cfg) else 'off'}."
        )
    else:
        lines.append("Memory: off.")

    lines.append(f"Web search: {'on' if (cfg.get('searxng') or {}).get('enabled') else 'off'}.")
    lines.append(f"Frigate cameras: {'on' if ft.is_enabled() else 'off'}.")

    if ha_api.is_available():
        from services import ha_tool_access as hta

        enabled = sorted(hta.enabled_categories(cfg))
        disabled = sorted(set(hta.CATEGORY_KEYS) - set(enabled))
        lines.append(
            f"Home Assistant: connected, {len(ha_api.ha_tool_names(cfg))} tools enabled "
            f"({', '.join(enabled) or 'none'})"
            + (f"; disabled: {', '.join(disabled)}" if disabled else "")
        )
    else:
        lines.append("Home Assistant: not reachable from the add-on.")

    lines.append(f"UI language: {cfg.get('language') or 'en'}.")
    return "\n".join(lines)


def _get_settings(args: dict, cfg: dict) -> str:
    section = str(args.get("section") or "all").strip().lower()
    if section == "general":
        data = {
            "language": cfg.get("language"),
            "knowledge_cutoff": cfg.get("knowledge_cutoff"),
            "dynamic_greetings": cfg.get("dynamic_greetings"),
            "system_prompt": cfg.get("system_prompt"),
        }
    elif section in ("", "all"):
        data = {
            k: _redact(v)
            for k, v in cfg.items()
            if k not in ("api_key", "users", "providers", "secondary_providers")
        }
    elif section in _SECTIONS:
        if section not in cfg and section == "bridge_tools":
            data = bta.merged_bridge_tools_config(cfg)
        else:
            data = _redact(cfg.get(section))
    else:
        return f"Error: unknown section '{section}'. Use one of: {', '.join(_SECTIONS)}."
    return f"[HASSAI Bridge settings — {section or 'all'}]\n{json.dumps(data, indent=2, ensure_ascii=False)}"


def _coerce(spec: tuple, raw):
    kind = spec[0]
    if kind == "bool":
        if isinstance(raw, bool):
            return raw, ""
        text = str(raw).strip().lower()
        if text in ("true", "1", "yes", "on", "da", "enabled"):
            return True, ""
        if text in ("false", "0", "no", "off", "nu", "disabled"):
            return False, ""
        return None, "expected true or false"
    if kind == "int":
        try:
            val = int(raw)
        except (TypeError, ValueError):
            return None, "expected a number"
        lo, hi = spec[1], spec[2]
        if not (lo <= val <= hi):
            return None, f"must be between {lo} and {hi}"
        return val, ""
    if kind == "enum":
        text = str(raw).strip().lower()
        if text not in spec[1]:
            return None, f"must be one of: {', '.join(spec[1])}"
        return text, ""
    text = str(raw).strip()
    if len(text) > spec[1]:
        return None, f"must be at most {spec[1]} characters"
    return text, ""


def _set_setting(args: dict, cfg: dict) -> str:
    path = str(args.get("path") or "").strip()
    if not path:
        return "Error: pass the setting key in `path`."
    allowed = allowed_paths()
    spec = allowed.get(path)
    if spec is None:
        return (
            f"Error: '{path}' is not writable from chat. Writable keys: "
            f"{', '.join(sorted(allowed))}."
        )
    value, problem = _coerce(spec, args.get("value"))
    if problem:
        return f"Error: '{path}' {problem}."

    fresh = load_config()
    parts = path.split(".")
    target = fresh
    for key in parts[:-1]:
        node = target.get(key)
        if not isinstance(node, dict):
            node = {}
            target[key] = node
        target = node
    before = target.get(parts[-1])
    if before == value:
        return f"'{path}' is already {json.dumps(value)}."
    target[parts[-1]] = value
    save_config(fresh)
    log.info("Bridge setting changed via chat: %s %r → %r", path, before, value)
    return f"Changed '{path}' from {json.dumps(before)} to {json.dumps(value)}."


def _list_providers(cfg: dict) -> str:
    active_id = cfg.get("active_provider") or ""
    lines = ["Primary providers:"]
    primaries = cfg.get("providers") or []
    if not primaries:
        lines.append("  (none configured)")
    for p in primaries:
        mark = " ← active" if p.get("id") == active_id else ""
        eco = ""
        lines.append(
            f"  • {p.get('name') or p.get('id')} ({p.get('type') or '?'}) — "
            f"model {p.get('model') or '?'}{eco}{mark}"
        )
    secondaries = cfg.get("secondary_providers") or []
    lines.append("Helper providers (secondary / vision / image):")
    if not secondaries:
        lines.append("  (none configured)")
    for p in secondaries:
        lines.append(
            f"  • {p.get('name') or p.get('id')} ({p.get('type') or '?'}) — model {p.get('model') or '?'}"
        )
    return "\n".join(lines)


def _match_provider(candidates: list[dict], needle: str) -> dict | None:
    text = needle.strip().lower()
    for p in candidates:
        if str(p.get("id") or "").lower() == text:
            return p
    for p in candidates:
        if str(p.get("name") or "").lower() == text:
            return p
    for p in candidates:
        if text and text in str(p.get("name") or "").lower():
            return p
    return None


def _switch_provider(args: dict) -> str:
    provider = str(args.get("provider") or "").strip()
    model = str(args.get("model") or "").strip()
    if not provider and not model:
        return "Error: pass provider or model."

    fresh = load_config()
    primaries = fresh.get("providers") or []
    if not primaries:
        return "Error: no providers configured. Add one in Settings → Providers."

    if provider:
        target = _match_provider(primaries, provider)
        if not target:
            names = ", ".join(str(p.get("name") or p.get("id")) for p in primaries)
            return f"Error: provider '{provider}' not found. Available: {names}."
        fresh["active_provider"] = target["id"]
    else:
        active_id = fresh.get("active_provider") or ""
        target = next((p for p in primaries if p.get("id") == active_id), primaries[0])

    changes = []
    if provider:
        changes.append(f"provider → {target.get('name') or target.get('id')}")
    if model:
        target["model"] = model
        changes.append(f"model → {model}")

    save_config(fresh)
    log.info("Provider switched via chat: %s", "; ".join(changes))
    return (
        "Switched: " + ", ".join(changes) + ". "
        f"Now on {target.get('name') or target.get('id')} ({target.get('type') or '?'}) "
        f"with model {target.get('model') or '?'}. This applies to your next reply."
    )


def _usage_stats(args: dict) -> str:
    try:
        days = max(1, min(365, int(args.get("days") or 30)))
    except (TypeError, ValueError):
        days = 30
    stats = get_usage_stats(days)
    tokens = stats.get("tokens") or {}
    lines = [
        f"Usage over the last {days} day(s): {stats.get('total_requests', 0)} requests, "
        f"{tokens.get('total', 0)} tokens "
        f"({tokens.get('prompt', 0)} prompt / {tokens.get('completion', 0)} completion)."
    ]
    for row in (stats.get("by_provider") or [])[:8]:
        lines.append(
            f"  • {row.get('provider_name') or row.get('provider_id') or '?'}: "
            f"{row.get('requests', 0)} requests, {row.get('tokens', 0)} tokens"
        )
    return "\n".join(lines)


async def run_tool(name: str, args: dict, user_id: str = "", cfg: dict | None = None) -> str:
    if cfg is None:
        cfg = load_config()
    if not tool_enabled(name, cfg):
        return f"Error: '{name}' is disabled in Settings → HASSAI Bridge tools."
    args = args or {}
    try:
        if name == "hassai_status":
            return _status(user_id, cfg)
        if name == "hassai_get_settings":
            return _get_settings(args, cfg)
        if name == "hassai_set_setting":
            return _set_setting(args, cfg)
        if name == "hassai_list_providers":
            return _list_providers(cfg)
        if name == "hassai_switch_provider":
            return _switch_provider(args)
        if name == "hassai_usage_stats":
            return _usage_stats(args)
    except Exception as exc:  # pragma: no cover - defensive
        log.error("Bridge tool %s failed: %s", name, exc)
        return f"Error: {name} failed — {exc}"
    return f"Error: unknown bridge tool '{name}'"
