"""
OpenAI-compatible /v1/chat/completions endpoint.
The HASSAI Bridge HA integration sends requests here. We:
1. Check for slash commands (/health, /settings, /help, etc.)
2. Retrieve relevant memories for the user
3. Forward augmented request to LMStudio
4. If LLM requests web search (<<SEARCH: query>>), search and re-prompt
5. Extract new memories from the conversation (background, non-blocking)
"""

import json
import asyncio
import logging
import re
import socket
import time
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config import load_config
from core.config import VERSION
from database import (
    add_conversation_message,
    get_conversation_history,
    get_memory_stats,
    get_all_users,
    get_usage_stats,
    add_usage_stat,
)
from services import providers
from services.providers import get_active_provider
from services import searxng, skills
from services.memory_engine import (
    retrieve_relevant_memories,
    build_memory_context,
    extract_memories_from_conversation,
)
from services.web_scraper import search_and_fetch
from services import homeassistant as ha_api

log = logging.getLogger("hassai.chat")
router = APIRouter()

_HA_TOOL_NAMES = ha_api.HA_TOOL_NAMES
_INTERNAL_TOOLS = {"search_web", "run_skill"} | _HA_TOOL_NAMES

# ── Start time for /uptime command ──
_cmd_start_time = time.time()


# ══════════════════════════════════════════════════
# Slash commands — intercepted before LLM processing
# ══════════════════════════════════════════════════

# ── Command i18n ──
_CMD_I18N = {
    "en": {
        "help.title": "📋 **Available commands:**",
        "help.health": "• `/health` — Service status (LLM Provider, Web Search, Memory)",
        "help.settings": "• `/settings` — Access links to the control panel",
        "help.info": "• `/info` — System info (version, uptime, stats)",
        "help.memory": "• `/memory` — Your memory statistics",
        "help.models": "• `/models` — Available models on the active provider",
        "help.setmodel": "• `/setmodel [name|#]` — Change model on the active provider",
        "help.setprovider": "• `/setprovider [name|#]` — Switch active AI provider",
        "help.set2nd": "• `/set2nd [name|#|off]` — Set or disable secondary provider",
        "help.seteco": "• `/seteco [on|off]` — Toggle Eco Mode on the active provider",
        "help.stats": "• `/stats [overview|users|memory|providers]` — Usage statistics",
        "help.lang": "• `/lang [en|ro]` — Change language",
        "help.version": "• `/version` — Current version",
        "help.help": "• `/help` — This command list",

        "health.title": "🏥 **Service Status:**",
        "health.connected": "✅ Connected",
        "health.unavailable": "❌ Unavailable",
        "health.disabled": "⚪ Disabled",
        "health.active": "✅ Active",
        "health.provider": "AI Provider",
        "health.search": "Web Search",
        "health.memoryAi": "AI Memory",

        "settings.title": "⚙️ **Control Panel:**",

        "info.title": "ℹ️ **HASSAI Bridge {version}**",
        "info.uptime": "Uptime",
        "info.lanIp": "LAN IP",
        "info.port": "Port",
        "info.provider": "Provider",
        "info.model": "Model",
        "info.maxTokens": "Max Tokens",
        "info.temperature": "Temperature",

        "memory.title": "🧠 **Memories for {user}:**",
        "memory.total": "Total",

        "models.title": "🤖 **Available models ({provider}):**",
        "models.none": "🤖 No models available on the active provider.",
        "models.error": "❌ Could not reach the active provider for model list.",
        "models.switch": "Use `/setmodel <name|#>` to switch.",

        "version.text": "🏠 HASSAI Bridge **{version}**",

        "setprovider.title": "🔄 **Available providers:**",
        "setprovider.none": "❌ No providers configured. Add one from the Web UI > Settings.",
        "setprovider.switch": "Use `/setprovider <name|#>` to switch.",
        "setprovider.notfound": "❌ Provider `{arg}` not found. Use `/setprovider` to see available providers.",
        "setprovider.ok": "✅ Switched to **{name}** ({type}) — model: `{model}`",

        "setmodel.title": "🤖 **Models on {provider}:**",
        "setmodel.none": "🤖 No models available on the active provider.",
        "setmodel.error": "❌ Could not reach the active provider for model list.",
        "setmodel.switch": "Use `/setmodel <name|#>` to switch.",
        "setmodel.notfound": "❌ Model #{arg} not found. Use `/setmodel` to see available models.",
        "setmodel.ok": "✅ Model changed to `{model}` on **{provider}**",

        "set2nd.title": "🔄 **Available secondary providers:**",
        "set2nd.none": "❌ No secondary providers configured. Add one from the Web UI > Settings.",
        "set2nd.hint": "Use `/set2nd <name|#>` to assign, `/set2nd off` to disable.",
        "set2nd.disabled": "✅ Secondary provider **disabled** for **{provider}**",
        "set2nd.notfound": "❌ Secondary provider `{arg}` not found. Use `/set2nd` to see available.",
        "set2nd.ok": "✅ Secondary provider set to **{name}** ({type}) for **{provider}**",

        "seteco.status": "🌿 **Eco Mode** on **{provider}**: {status}\n\nUse `/seteco on` to enable, `/seteco off` to disable.",
        "seteco.ok": "🌿 Eco Mode **{status}** for **{provider}**",

        "lang.current": "🌐 **Language:** {lang}\n\nUse `/lang en` or `/lang ro` to change.",
        "lang.ok": "🌐 Language changed to **{lang}**",
        "lang.invalid": "❌ Unsupported language `{arg}`. Available: `en`, `ro`.",

        "stats.title_overview": "📊 **Usage Statistics (last {days} days):**",
        "stats.totalRequests": "Total Requests",
        "stats.totalTokens": "Total Tokens",
        "stats.promptTokens": "Prompt",
        "stats.completionTokens": "Completion",
        "stats.searchRequests": "Search Requests",
        "stats.streamRequests": "Stream / Non-stream",
        "stats.ecoMode": "Eco Mode",
        "stats.ecoRequests": "Eco Requests",
        "stats.ecoSaved": "Tokens Saved (est.)",
        "stats.secondary": "Secondary Provider",
        "stats.secondaryCalls": "Secondary Calls",
        "stats.secondaryTokens": "Secondary Tokens",

        "stats.title_users": "👥 **User Statistics (last {days} days):**",
        "stats.userRequests": "requests",
        "stats.userTokens": "tokens",
        "stats.noUsers": "No user data available.",

        "stats.title_memory": "🧠 **Memory Statistics:**",
        "stats.memTotalUsers": "Users with memories",
        "stats.memTotalMem": "Total memories",
        "stats.memPerUser": "Per user:",

        "stats.title_providers": "🔌 **Provider Statistics (last {days} days):**",
        "stats.provRequests": "requests",
        "stats.provTokens": "tokens",
        "stats.provAvgMs": "avg {ms}ms",
        "stats.noProviders": "No provider data available.",

        "stats.hint": "Subcategories: `/stats overview`, `/stats users`, `/stats memory`, `/stats providers`",

        "unknown": "❓ Unknown command: `{command}`\n\nType `/help` for available commands.",
        "on": "ON ✅",
        "off": "OFF ⚪",
    },
    "ro": {
        "help.title": "📋 **Comenzi disponibile:**",
        "help.health": "• `/health` — Stare servicii (Provider LLM, Căutare Web, Memorie)",
        "help.settings": "• `/settings` — Linkuri către panoul de control",
        "help.info": "• `/info` — Info sistem (versiune, uptime, statistici)",
        "help.memory": "• `/memory` — Statistici memorii tale",
        "help.models": "• `/models` — Modele disponibile pe providerul activ",
        "help.setmodel": "• `/setmodel [nume|#]` — Schimbă modelul pe providerul activ",
        "help.setprovider": "• `/setprovider [nume|#]` — Schimbă providerul AI activ",
        "help.set2nd": "• `/set2nd [nume|#|off]` — Setează sau dezactivează providerul secundar",
        "help.seteco": "• `/seteco [on|off]` — Comută Eco Mode pe providerul activ",
        "help.stats": "• `/stats [overview|users|memory|providers]` — Statistici utilizare",
        "help.lang": "• `/lang [en|ro]` — Schimbă limba",
        "help.version": "• `/version` — Versiunea curentă",
        "help.help": "• `/help` — Lista de comenzi",

        "health.title": "🏥 **Stare Servicii:**",
        "health.connected": "✅ Conectat",
        "health.unavailable": "❌ Indisponibil",
        "health.disabled": "⚪ Dezactivat",
        "health.active": "✅ Activ",
        "health.provider": "Provider AI",
        "health.search": "Căutare Web",
        "health.memoryAi": "Memorie AI",

        "settings.title": "⚙️ **Panou de Control:**",

        "info.title": "ℹ️ **HASSAI Bridge {version}**",
        "info.uptime": "Timp funcționare",
        "info.lanIp": "IP Local",
        "info.port": "Port",
        "info.provider": "Provider",
        "info.model": "Model",
        "info.maxTokens": "Tokeni maximi",
        "info.temperature": "Temperatură",

        "memory.title": "🧠 **Memorii pentru {user}:**",
        "memory.total": "Total",

        "models.title": "🤖 **Modele disponibile ({provider}):**",
        "models.none": "🤖 Niciun model disponibil pe providerul activ.",
        "models.error": "❌ Nu s-a putut contacta providerul activ pentru lista de modele.",
        "models.switch": "Folosește `/setmodel <nume|#>` pentru a schimba.",

        "version.text": "🏠 HASSAI Bridge **{version}**",

        "setprovider.title": "🔄 **Provideri disponibili:**",
        "setprovider.none": "❌ Niciun provider configurat. Adaugă unul din Web UI > Setări.",
        "setprovider.switch": "Folosește `/setprovider <nume|#>` pentru a schimba.",
        "setprovider.notfound": "❌ Providerul `{arg}` nu a fost găsit. Folosește `/setprovider` pentru a vedea lista.",
        "setprovider.ok": "✅ Schimbat la **{name}** ({type}) — model: `{model}`",

        "setmodel.title": "🤖 **Modele pe {provider}:**",
        "setmodel.none": "🤖 Niciun model disponibil pe providerul activ.",
        "setmodel.error": "❌ Nu s-a putut contacta providerul activ pentru lista de modele.",
        "setmodel.switch": "Folosește `/setmodel <nume|#>` pentru a schimba.",
        "setmodel.notfound": "❌ Modelul #{arg} nu a fost găsit. Folosește `/setmodel` pentru a vedea lista.",
        "setmodel.ok": "✅ Model schimbat la `{model}` pe **{provider}**",

        "set2nd.title": "🔄 **Provideri secundari disponibili:**",
        "set2nd.none": "❌ Niciun provider secundar configurat. Adaugă unul din Web UI > Setări.",
        "set2nd.hint": "Folosește `/set2nd <nume|#>` pentru a asigna, `/set2nd off` pentru a dezactiva.",
        "set2nd.disabled": "✅ Provider secundar **dezactivat** pentru **{provider}**",
        "set2nd.notfound": "❌ Providerul secundar `{arg}` nu a fost găsit. Folosește `/set2nd` pentru a vedea lista.",
        "set2nd.ok": "✅ Provider secundar setat la **{name}** ({type}) pentru **{provider}**",

        "seteco.status": "🌿 **Eco Mode** pe **{provider}**: {status}\n\nFolosește `/seteco on` pentru a activa, `/seteco off` pentru a dezactiva.",
        "seteco.ok": "🌿 Eco Mode **{status}** pentru **{provider}**",

        "lang.current": "🌐 **Limbă:** {lang}\n\nFolosește `/lang en` sau `/lang ro` pentru a schimba.",
        "lang.ok": "🌐 Limba schimbată la **{lang}**",
        "lang.invalid": "❌ Limbă nesuportată `{arg}`. Disponibile: `en`, `ro`.",

        "stats.title_overview": "📊 **Statistici utilizare (ultimele {days} zile):**",
        "stats.totalRequests": "Total cereri",
        "stats.totalTokens": "Total tokeni",
        "stats.promptTokens": "Prompt",
        "stats.completionTokens": "Completare",
        "stats.searchRequests": "Cereri cu căutare",
        "stats.streamRequests": "Stream / Non-stream",
        "stats.ecoMode": "Eco Mode",
        "stats.ecoRequests": "Cereri Eco",
        "stats.ecoSaved": "Tokeni economisiți (est.)",
        "stats.secondary": "Provider Secundar",
        "stats.secondaryCalls": "Apeluri secundare",
        "stats.secondaryTokens": "Tokeni secundari",

        "stats.title_users": "👥 **Statistici utilizatori (ultimele {days} zile):**",
        "stats.userRequests": "cereri",
        "stats.userTokens": "tokeni",
        "stats.noUsers": "Nu există date despre utilizatori.",

        "stats.title_memory": "🧠 **Statistici memorie:**",
        "stats.memTotalUsers": "Utilizatori cu memorii",
        "stats.memTotalMem": "Total memorii",
        "stats.memPerUser": "Per utilizator:",

        "stats.title_providers": "🔌 **Statistici provideri (ultimele {days} zile):**",
        "stats.provRequests": "cereri",
        "stats.provTokens": "tokeni",
        "stats.provAvgMs": "medie {ms}ms",
        "stats.noProviders": "Nu există date despre provideri.",

        "stats.hint": "Subcategorii: `/stats overview`, `/stats users`, `/stats memory`, `/stats providers`",

        "unknown": "❓ Comandă necunoscută: `{command}`\n\nScrie `/help` pentru comenzile disponibile.",
        "on": "ON ✅",
        "off": "OFF ⚪",
    },
}


def _ct(key: str, cfg: dict, **kwargs) -> str:
    """Get translated command string."""
    lang = cfg.get("language", "en")
    strings = _CMD_I18N.get(lang, _CMD_I18N["en"])
    template = strings.get(key, _CMD_I18N["en"].get(key, key))
    return template.format(**kwargs) if kwargs else template

def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


async def _handle_command(cmd: str, user_id: str) -> str | None:
    """Handle slash commands. Returns response text or None if not a command."""
    cmd = cmd.strip()
    if not cmd.startswith("/"):
        return None

    parts = cmd.split(None, 1)
    command = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    cfg = load_config()
    ip = _get_local_ip()
    port = 8899
    base = f"http://{ip}:{port}"
    T = lambda key, **kw: _ct(key, cfg, **kw)

    if command == "/help":
        lines = [T("help.title"), ""]
        for k in ("health", "settings", "info", "memory", "models",
                   "setmodel", "setprovider", "set2nd", "seteco",
                   "stats", "lang", "version", "help"):
            lines.append(T(f"help.{k}"))
        return "\n".join(lines)

    elif command == "/health":
        active = get_active_provider()
        lm_ok = await providers.health_check(active)
        sx_ok = await searxng.health_check()
        lm_status = T("health.connected") if lm_ok else T("health.unavailable")
        sx_enabled = cfg["searxng"].get("enabled", False)
        if not sx_enabled:
            sx_status = T("health.disabled")
        elif sx_ok:
            sx_status = T("health.connected")
        else:
            sx_status = T("health.unavailable")
        mem_enabled = cfg["memory"].get("enabled", False)
        mem_status = T("health.active") if mem_enabled else T("health.disabled")
        return (
            f"{T('health.title')}\n\n"
            f"• **{T('health.provider')}:** {lm_status} — `{active.get('name', '?')}` ({active.get('type', '?')}) model: {active.get('model', '?')}\n"
            f"• **{T('health.search')}:** {sx_status} — `{cfg['searxng']['base_url']}`\n"
            f"• **{T('health.memoryAi')}:** {mem_status}"
        )

    elif command == "/settings":
        return (
            f"{T('settings.title')}\n\n"
            f"• **Web UI:** {base}\n"
            f"• **API (OpenAI):** {base}/v1\n"
            f"• **Settings API:** {base}/api/settings/\n"
            f"• **Health Check:** {base}/api/settings/health"
        )

    elif command == "/info":
        uptime_sec = time.time() - _cmd_start_time
        d = int(uptime_sec // 86400)
        h = int((uptime_sec % 86400) // 3600)
        m = int((uptime_sec % 3600) // 60)
        uptime_str = f"{d}d {h}h {m}m" if d > 0 else f"{h}h {m}m" if h > 0 else f"{m}m"
        active = get_active_provider()
        return (
            f"{T('info.title', version=VERSION)}\n\n"
            f"• **{T('info.uptime')}:** {uptime_str}\n"
            f"• **{T('info.lanIp')}:** {ip}\n"
            f"• **{T('info.port')}:** {port}\n"
            f"• **{T('info.provider')}:** {active.get('name', '?')} ({active.get('type', '?')})\n"
            f"• **{T('info.model')}:** {active.get('model', '?')}\n"
            f"• **{T('info.maxTokens')}:** {active.get('max_tokens', 2048)}\n"
            f"• **{T('info.temperature')}:** {active.get('temperature', 0.7)}"
        )

    elif command == "/memory":
        stats = get_memory_stats(user_id)
        lines = [T("memory.title", user=user_id), ""]
        lines.append(f"• **{T('memory.total')}:** {stats['total']}")
        for cat, count in stats.get("by_category", {}).items():
            lines.append(f"• **{cat}:** {count}")
        return "\n".join(lines)

    elif command == "/models":
        try:
            active = get_active_provider()
            models = await providers.list_models(active)
            if models:
                lines = [T("models.title", provider=active.get("name", "?")), ""]
                current_model = active.get("model", "")
                for i, m in enumerate(models, 1):
                    mid = m.get("id", "unknown")
                    marker = " ✅" if mid == current_model else ""
                    lines.append(f"**{i}.** `{mid}`{marker}")
                lines.append(f"\n{T('models.switch')}")
                return "\n".join(lines)
            else:
                return T("models.none")
        except Exception:
            return T("models.error")

    elif command == "/version":
        return T("version.text", version=VERSION)

    elif command == "/setprovider":
        from config import save_config
        all_providers = cfg.get("providers", [])
        if not arg:
            if not all_providers:
                return T("setprovider.none")
            lines = [T("setprovider.title"), ""]
            active_id = cfg.get("active_provider", "")
            for i, p in enumerate(all_providers, 1):
                marker = " ✅" if p["id"] == active_id else ""
                lines.append(f"**{i}.** `{p.get('name', '?')}` — {p.get('type', '?')} model: {p.get('model', '?')}{marker}")
            lines.append(f"\n{T('setprovider.switch')}")
            return "\n".join(lines)
        match = None
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(all_providers):
                match = all_providers[idx]
        if not match:
            for p in all_providers:
                if p["id"] == arg or p["id"].startswith(arg):
                    match = p
                    break
        if not match:
            for p in all_providers:
                if arg.lower() in p.get("name", "").lower():
                    match = p
                    break
        if not match:
            return T("setprovider.notfound", arg=arg)
        cfg["active_provider"] = match["id"]
        save_config(cfg)
        return T("setprovider.ok", name=match.get("name", match["id"]),
                  type=match.get("type", "?"), model=match.get("model", "?"))

    elif command == "/setmodel":
        from config import save_config
        active = get_active_provider()
        if not arg:
            try:
                models = await providers.list_models(active)
            except Exception:
                return T("setmodel.error")
            if not models:
                return T("setmodel.none")
            lines = [T("setmodel.title", provider=active.get("name", "?")), ""]
            current_model = active.get("model", "")
            for i, m in enumerate(models, 1):
                mid = m.get("id", "unknown")
                marker = " ✅" if mid == current_model else ""
                lines.append(f"**{i}.** `{mid}`{marker}")
            lines.append(f"\n{T('setmodel.switch')}")
            return "\n".join(lines)
        chosen = None
        if arg.isdigit():
            try:
                models = await providers.list_models(active)
                idx = int(arg) - 1
                if 0 <= idx < len(models):
                    chosen = models[idx].get("id")
            except Exception:
                return T("setmodel.error")
            if chosen is None:
                return T("setmodel.notfound", arg=arg)
        else:
            chosen = arg
        all_providers = cfg.get("providers", [])
        for p in all_providers:
            if p["id"] == active["id"]:
                p["model"] = chosen
                break
        cfg["providers"] = all_providers
        save_config(cfg)
        return T("setmodel.ok", model=chosen, provider=active.get("name", active["id"]))

    elif command == "/set2nd":
        from config import save_config
        active = get_active_provider()
        all_secondary = cfg.get("secondary_providers", [])

        if not arg:
            if not all_secondary:
                return T("set2nd.none")
            lines = [T("set2nd.title"), ""]
            current_sec_id = active.get("secondary_provider", "")
            for i, sp in enumerate(all_secondary, 1):
                marker = " ✅" if sp["id"] == current_sec_id else ""
                lines.append(f"**{i}.** `{sp.get('name', '?')}` — {sp.get('type', '?')} model: {sp.get('model', '?')}{marker}")
            lines.append(f"\n{T('set2nd.hint')}")
            return "\n".join(lines)

        if arg.lower() in ("off", "disable", "none", "0"):
            all_providers = cfg.get("providers", [])
            for p in all_providers:
                if p["id"] == active["id"]:
                    p["secondary_provider"] = ""
                    break
            cfg["providers"] = all_providers
            save_config(cfg)
            return T("set2nd.disabled", provider=active.get("name", active["id"]))

        match = None
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(all_secondary):
                match = all_secondary[idx]
        if not match:
            for sp in all_secondary:
                if sp["id"] == arg or sp["id"].startswith(arg):
                    match = sp
                    break
        if not match:
            for sp in all_secondary:
                if arg.lower() in sp.get("name", "").lower():
                    match = sp
                    break
        if not match:
            return T("set2nd.notfound", arg=arg)

        all_providers = cfg.get("providers", [])
        for p in all_providers:
            if p["id"] == active["id"]:
                p["secondary_provider"] = match["id"]
                break
        cfg["providers"] = all_providers
        save_config(cfg)
        return T("set2nd.ok", name=match.get("name", match["id"]),
                  type=match.get("type", "?"), provider=active.get("name", active["id"]))

    elif command == "/seteco":
        from config import save_config
        active = get_active_provider()

        if not arg:
            status = T("on") if active.get("eco_mode") else T("off")
            return T("seteco.status", provider=active.get("name", active["id"]), status=status)

        enable = arg.lower() in ("1", "on", "true", "yes")
        all_providers = cfg.get("providers", [])
        for p in all_providers:
            if p["id"] == active["id"]:
                p["eco_mode"] = enable
                break
        cfg["providers"] = all_providers
        save_config(cfg)
        status = T("on") if enable else T("off")
        return T("seteco.ok", provider=active.get("name", active["id"]), status=status)

    elif command == "/lang":
        from config import save_config
        supported = ("en", "ro")
        if not arg:
            current = cfg.get("language", "en")
            lang_names = {"en": "English", "ro": "Română"}
            return T("lang.current", lang=lang_names.get(current, current))
        lang_choice = arg.lower().strip()
        if lang_choice not in supported:
            return T("lang.invalid", arg=arg)
        cfg["language"] = lang_choice
        save_config(cfg)
        # Re-read T with new language
        T2 = lambda key, **kw: _ct(key, cfg, **kw)
        lang_names = {"en": "English", "ro": "Română"}
        return T2("lang.ok", lang=lang_names.get(lang_choice, lang_choice))

    elif command == "/stats":
        return _handle_stats_command(arg, user_id, cfg)

    else:
        return T("unknown", command=command)


def _handle_stats_command(arg: str, user_id: str, cfg: dict) -> str:
    """Handle /stats command with subcategories."""
    T = lambda key, **kw: _ct(key, cfg, **kw)
    sub = arg.lower().strip() if arg else ""

    if sub in ("", "overview"):
        s = get_usage_stats(30)
        tok = s["tokens"]
        eco = s["eco_mode"]
        sec = s["secondary"]
        lines = [T("stats.title_overview", days=30), ""]
        lines.append(f"• **{T('stats.totalRequests')}:** {s['total_requests']:,}")
        lines.append(f"• **{T('stats.totalTokens')}:** {tok['total']:,} ({T('stats.promptTokens')}: {tok['prompt']:,} / {T('stats.completionTokens')}: {tok['completion']:,})")
        lines.append(f"• **{T('stats.searchRequests')}:** {s['search_requests']:,}")
        lines.append(f"• **{T('stats.streamRequests')}:** {s['stream_requests']:,} / {s['non_stream_requests']:,}")
        lines.append("")
        lines.append(f"🌿 **{T('stats.ecoMode')}:**")
        lines.append(f"• **{T('stats.ecoRequests')}:** {eco['requests']:,}")
        lines.append(f"• **{T('stats.ecoSaved')}:** {eco['saved_tokens']:,}")
        lines.append("")
        lines.append(f"🔗 **{T('stats.secondary')}:**")
        lines.append(f"• **{T('stats.secondaryCalls')}:** {sec['requests']:,}")
        lines.append(f"• **{T('stats.secondaryTokens')}:** {sec['tokens']:,}")
        lines.append(f"\n{T('stats.hint')}")
        return "\n".join(lines)

    elif sub == "users":
        s = get_usage_stats(30)
        by_user = s.get("by_user", [])
        if not by_user:
            return T("stats.noUsers")
        lines = [T("stats.title_users", days=30), ""]
        for i, u in enumerate(by_user, 1):
            lines.append(f"**{i}.** `{u['user_id']}` — {u['requests']:,} {T('stats.userRequests')}, {u['tokens']:,} {T('stats.userTokens')}")
        lines.append(f"\n{T('stats.hint')}")
        return "\n".join(lines)

    elif sub == "memory":
        all_users = get_all_users()
        total_mem = 0
        user_lines = []
        for uid in all_users:
            ms = get_memory_stats(uid)
            if ms["total"] > 0:
                total_mem += ms["total"]
                cats = ", ".join(f"{c}: {n}" for c, n in ms["by_category"].items())
                user_lines.append(f"• `{uid}` — {ms['total']} ({cats})")
        lines = [T("stats.title_memory"), ""]
        lines.append(f"• **{T('stats.memTotalUsers')}:** {len(user_lines)}")
        lines.append(f"• **{T('stats.memTotalMem')}:** {total_mem}")
        if user_lines:
            lines.append(f"\n**{T('stats.memPerUser')}**")
            lines.extend(user_lines)
        lines.append(f"\n{T('stats.hint')}")
        return "\n".join(lines)

    elif sub in ("providers", "provider"):
        s = get_usage_stats(30)
        by_prov = s.get("by_provider", [])
        if not by_prov:
            return T("stats.noProviders")
        lines = [T("stats.title_providers", days=30), ""]
        for i, p in enumerate(by_prov, 1):
            lines.append(
                f"**{i}.** **{p['provider_name'] or p['provider_id']}** ({p['provider_type']}) — "
                f"{p['requests']:,} {T('stats.provRequests')}, "
                f"{p['tokens']:,} {T('stats.provTokens')}, "
                f"{T('stats.provAvgMs', ms=p['avg_response_ms'])}"
            )
        lines.append(f"\n{T('stats.hint')}")
        return "\n".join(lines)

    else:
        return T("stats.hint")


def _command_response_openai(content: str, model: str) -> dict:
    """Build an OpenAI-compatible response for a command result."""
    return {
        "id": f"cmd-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "hassai-bridge",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _estimate_tokens(text: str) -> int:
    """Estimate token count using word-based heuristic.

    ~1.3 tokens per word for English, ~1.5 for non-Latin (Romanian diacritics, CJK).
    """
    words = text.split()
    if not words:
        return 1
    # Non-ASCII heavy text tends to tokenize into more tokens
    non_ascii_ratio = sum(1 for c in text if ord(c) > 127) / max(len(text), 1)
    multiplier = 1.5 if non_ascii_ratio > 0.1 else 1.3
    return max(1, int(len(words) * multiplier))


def _sanitize_message_roles(messages: list[dict]) -> list[dict]:
    """Fix message list to respect role alternation rules expected by chat templates.

    1. Ensure the first non-system message is a user message (drop leading assistants)
    2. Merge consecutive messages with the same role
    3. Drop empty content messages (except tool_calls)
    """
    system_msgs = []
    other_msgs = []

    for m in messages:
        if m.get("role") == "system":
            system_msgs.append(m)
        else:
            other_msgs.append(m)

    if not other_msgs:
        return system_msgs

    # Drop leading assistant messages (before the first user message)
    while other_msgs and other_msgs[0].get("role") != "user":
        other_msgs.pop(0)

    if not other_msgs:
        return system_msgs

    # Merge consecutive same-role messages and drop empty ones
    cleaned = []
    for m in other_msgs:
        content = (m.get("content") or "").strip()
        role = m.get("role", "user")

        # Keep tool_calls messages even if content is empty
        if not content and not m.get("tool_calls") and role != "tool":
            continue

        if cleaned and cleaned[-1].get("role") == role and role != "tool":
            # Merge with previous message of same role
            prev_content = (cleaned[-1].get("content") or "").strip()
            if content and prev_content:
                cleaned[-1]["content"] = prev_content + "\n" + content
            elif content:
                cleaned[-1]["content"] = content
        else:
            cleaned.append(dict(m))

    return system_msgs + cleaned


def _trim_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """Trim conversation to fit within token budget.

    Strategy: keep system msgs + compress oldest conversation turns into a
    single summary line, then keep the most recent turns verbatim.
    This preserves context while drastically reducing token count.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    system_tokens = sum(_estimate_tokens(m.get("content") or "") for m in system_msgs)
    budget = max_tokens - system_tokens
    if budget <= 0:
        return system_msgs

    # First pass: total cost of all non-system messages
    total_others = sum(_estimate_tokens(m.get("content") or "") for m in other_msgs)
    if total_others <= budget:
        return system_msgs + other_msgs  # everything fits

    # Keep recent messages verbatim, compress older ones into a summary
    kept_recent = []
    used = 0
    for msg in reversed(other_msgs):
        cost = _estimate_tokens(msg.get("content") or "")
        if used + cost > budget * 0.7:  # reserve 70% budget for recent messages
            break
        kept_recent.append(msg)
        used += cost
    kept_recent.reverse()

    # Compress dropped older messages into a single summary
    dropped = other_msgs[:len(other_msgs) - len(kept_recent)]
    if dropped:
        summary_parts = []
        for m in dropped:
            role = m.get("role", "user")
            content = (m.get("content") or "")[:80].replace("\n", " ").strip()
            if content and role in ("user", "assistant"):
                prefix = "U" if role == "user" else "A"
                summary_parts.append(f"{prefix}: {content}")
        if summary_parts:
            # Cap summary to use at most 15% of budget
            summary_text = "[Earlier conversation summary]\n" + "\n".join(summary_parts[-8:])
            summary_tokens = _estimate_tokens(summary_text)
            if summary_tokens < budget * 0.15:
                kept_recent.insert(0, {"role": "user", "content": summary_text})

    return system_msgs + kept_recent

# ══════════════════════════════════════════════════
# AI-driven search via function-calling (tool_calls)
# Like hass_memory/brain/toolbox.py — reliable, no marker parsing.
# ══════════════════════════════════════════════════

_SEARCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the web for current/time-sensitive info (news, weather, prices, events, scores). "
            "Do NOT search for facts already in your training data. "
            "Use short keyword queries (3-7 words)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Short keyword-focused search query.",
                }
            },
            "required": ["query"],
        },
    },
}

# For stripping old <<SEARCH:...>> markers from conversation history (legacy cleanup)
_SEARCH_MARKER_STRIP = re.compile(r"<<SEARCH:[^>\n]*(?:>>)?")


def _strip_search_markers(text: str) -> str:
    """Remove any <<SEARCH:...>> markers from text (legacy cleanup)."""
    return _SEARCH_MARKER_STRIP.sub("", text).strip()


def _build_skill_tools() -> list[dict]:
    """Build the run_skill tool definition with current skill descriptions."""
    cfg = load_config()
    disabled = set(cfg.get("skills_disabled", []))
    registry = skills.get_skill_registry()
    enabled = [s for s in registry if s["name"] not in disabled]
    if not enabled:
        return []
    skill_list = ", ".join(s["name"] for s in enabled)
    return [{
        "type": "function",
        "function": {
            "name": "run_skill",
            "description": f"Execute a skill: {skill_list}.",
            "parameters": {
                "type": "object",
                "properties": {
                    "skill_name": {
                        "type": "string",
                        "enum": [s["name"] for s in enabled],
                    },
                    "input_data": {
                        "type": "object",
                    },
                },
                "required": ["skill_name", "input_data"],
            },
        },
    }]


def _build_search_instruction(cfg: dict) -> str:
    """Compact search context hint."""
    cutoff = cfg.get("knowledge_cutoff", "2024-01")
    today = date.today().strftime("%Y-%m-%d")
    return (
        f"Date: {today}. Knowledge cutoff: {cutoff}. "
        "Use search_web for anything after your cutoff. "
        "Never say you can't search."
    )


_API_KEY_PATTERN = re.compile(r"^hab_[a-f0-9]{32,64}$")

# ── SSE keepalive interval (seconds) to prevent client timeout during prompt processing ──
_KEEPALIVE_INTERVAL = 3


async def _stream_with_keepalive_sse(gen, interval: float = _KEEPALIVE_INTERVAL):
    """Wrap an async generator with periodic SSE keepalive comments.

    Prevents client disconnect during long prompt processing by sending
    SSE comments (`: keepalive\\n\\n`) which are ignored by spec-compliant clients.
    Uses asyncio.shield to prevent cancelling the upstream read on timeout.
    """
    gen_iter = gen.__aiter__()
    next_task = None
    while True:
        if next_task is None:
            next_task = asyncio.ensure_future(gen_iter.__anext__())
        try:
            chunk = await asyncio.wait_for(asyncio.shield(next_task), timeout=interval)
            next_task = None
            yield chunk
        except asyncio.TimeoutError:
            # Upstream read still in progress — send keepalive without cancelling it
            yield ": keepalive\n\n"
        except StopAsyncIteration:
            break


def _validate_api_key(request: Request):
    """Validate API key, or allow trusted Web UI / HA Ingress sessions."""
    from core.auth import require_api_key_or_webui

    require_api_key_or_webui(request)


def _extract_user_id(request: Request, body: dict) -> str:
    """Identify the HA user from the request.

    Priority:
    1. API key → username mapping (config users.api_keys)
    2. HA headers (X-HA-User-Id, X-HA-Username, etc.)
    3. body fields (user, user_id, username)
    4. Fallback to config users.default_user
    """
    cfg = load_config()
    users_cfg = cfg.get("users", {})
    api_key_map = users_cfg.get("api_keys", {})
    default_user = users_cfg.get("default_user", "").strip()

    # 1) Check if the API key maps to a specific user
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token in api_key_map:
            return api_key_map[token]

    assist_key = request.headers.get("x-assist-key", "").strip()
    if assist_key and assist_key in api_key_map:
        return api_key_map[assist_key]

    # 2) HA headers
    for header in ("X-HA-Username", "X-HA-User-Name", "X-HA-User-Id", "X-HA-User"):
        val = request.headers.get(header, "").strip()
        if val:
            return val

    # 3) Body fields
    for field in ("username", "user_name", "user_id", "user"):
        val = str(body.get(field, "") or "").strip()
        if val:
            return val

    # 4) Fallback to configured default user
    if default_user:
        return default_user

    return "default"


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model")
    stream = body.get("stream", False)
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")
    user_id = _extract_user_id(request, body)
    cfg = load_config()
    search_enabled = cfg["searxng"].get("enabled", False)

    # Build effective tools list: client tools + search_web + skills + HA
    all_tools = list(tools or []) if tools else []
    if search_enabled:
        all_tools.append(_SEARCH_WEB_TOOL)
    all_tools.extend(_build_skill_tools())
    all_tools.extend(ha_api.build_ha_tools())
    effective_tools = all_tools if all_tools else None

    # ── Slash command check ──
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = (msg.get("content") or "").strip()
            break

    # Authenticate when an API key is configured
    _validate_api_key(request)

    # ── Message size validation (#16) ──
    total_size = sum(len(m.get("content") or "") for m in messages)
    if total_size > 512_000:  # 500KB max
        return JSONResponse(
            status_code=413,
            content={"error": {"message": "Message content too large (max 500KB)", "type": "invalid_request_error"}},
        )
    for msg in messages:
        if len(msg.get("content") or "") > 100_000:  # 100KB per message
            return JSONResponse(
                status_code=413,
                content={"error": {"message": "Single message too large (max 100KB)", "type": "invalid_request_error"}},
            )

    cmd_result = await _handle_command(last_user_msg, user_id)
    if cmd_result is not None:
        log.info(f"[{user_id}] Slash command: {last_user_msg[:50]}")
        # Slash commands: save only user msg, not polluting history with /health etc. (#18)
        if stream:
            # Stream the command response as a single chunk
            chunk_data = json.dumps({
                "id": f"cmd-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model or "hassai-bridge",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": cmd_result}, "finish_reason": "stop"}],
            })
            async def cmd_stream():
                yield f"data: {chunk_data}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(cmd_stream(), media_type="text/event-stream")
        return JSONResponse(content=_command_response_openai(cmd_result, model))

    # ── Build augmented message list ──
    active = get_active_provider()
    log.info(f"[{user_id}] Request: \"{last_user_msg[:80]}\" (provider={active.get('name','?')}, stream={stream})")
    augmented: list[dict] = []

    # 1) System prompt (per-provider overrides global)
    secondary = providers.get_secondary_provider(active)
    system_prompt = (active.get("system_prompt") or "").strip() or cfg.get("system_prompt", "")

    # Eco Mode: append conciseness instruction to reduce output tokens
    if active.get("eco_mode"):
        default_eco = (
            "Be concise. No filler words, no pleasantries, no sign-offs. "
            "Answer directly without restating the question. "
            "Skip explanations unless explicitly asked. "
            "Keep responses short and to the point."
        )
        eco_instruction = cfg.get("security", {}).get("eco_prompt", "").strip() or default_eco
        system_prompt = f"{system_prompt}\n\n{eco_instruction}" if system_prompt else eco_instruction

    # 2) Memory + history retrieval (parallel)
    history_limit = cfg.get("performance", {}).get("history_limit", 10)
    memories, history = await asyncio.gather(
        retrieve_relevant_memories(user_id, last_user_msg),
        asyncio.to_thread(get_conversation_history, user_id, history_limit),
    )

    mem_ctx = build_memory_context(memories, user_id=user_id, message=last_user_msg)

    # 3) Merge all system content into ONE system message (saves per-message overhead on local LLMs)
    system_parts = []
    if system_prompt:
        system_parts.append(system_prompt)
    if mem_ctx:
        system_parts.append(mem_ctx)
    if search_enabled:
        system_parts.append(_build_search_instruction(cfg))
    ha_hint = ha_api.ha_system_hint()
    if ha_hint:
        system_parts.append(ha_hint)
    if system_parts:
        augmented.append({"role": "system", "content": "\n\n".join(system_parts)})

    # 4) Conversation history — only add DB history if incoming messages
    #    don't already contain a conversation (HA sends full history)
    incoming_roles = {m.get("role") for m in messages}
    has_incoming_history = "assistant" in incoming_roles and "user" in incoming_roles
    if history and not has_incoming_history:
        augmented.extend(history)

    # 5) Current messages
    augmented.extend(messages)

    # ── Save user messages to history ──
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content") or ""
        if content and role in ("user", "assistant"):
            add_conversation_message(user_id, role, content)

    # ── Strip any <<SEARCH markers that leaked into stored assistant messages ──
    for m in augmented:
        c = m.get("content") or ""
        if c and m.get("role") == "assistant" and "<<SEARCH" in c:
            cleaned = _strip_search_markers(c).strip()
            m["content"] = cleaned if cleaned else "(search attempted)"

    # ── Sanitize role order + trim to fit context window ──
    augmented = _sanitize_message_roles(augmented)
    max_ctx = active.get("max_tokens", 2048) * 3  # rough context budget
    augmented = _trim_messages(augmented, max_ctx)

    # Log prompt size for optimization tracking
    _prompt_tokens = sum(_estimate_tokens(m.get("content") or "") for m in augmented)
    log.info(f"Prompt: {len(augmented)} msgs, ~{_prompt_tokens} tokens (budget {max_ctx})")

    # ── First LLM call ──
    _req_start = time.time()
    _search_used = False
    _secondary_used_for_recall = False  # tracks if secondary handled a re-call (search/skill)
    if not stream:
        try:
            result = await providers.chat_completion(augmented, model=model, tools=effective_tools, tool_choice=tool_choice, provider=active)
        except Exception as e:
            log.error(f"Provider [{active.get('name', '?')}] request failed: {e}")
            return JSONResponse(
                status_code=502,
                content={"error": {"message": "Provider request failed. Check server logs for details.", "type": "upstream_error"}},
            )

        # ── Handle tool_calls (search_web, run_skill, HA, or forward to client) ──
        for _round in range(3):
            msg = result.get("choices", [{}])[0].get("message", {})
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                break

            # Separate internal (bridge-handled) vs external (client-handled) tool calls
            internal_calls = [tc for tc in tool_calls if tc.get("function", {}).get("name") in _INTERNAL_TOOLS]
            external_calls = [tc for tc in tool_calls if tc.get("function", {}).get("name") not in _INTERNAL_TOOLS]

            if not internal_calls:
                # Only external tool_calls — forward to client (HA)
                msg["content"] = ""
                return JSONResponse(content=result)

            # Process all internal tool calls
            augmented.append(msg)  # assistant message with tool_calls
            used_tool_names = set()

            for tc in internal_calls:
                fn_name = tc.get("function", {}).get("name", "")
                tc_id = tc.get("id", f"call_{fn_name}")
                try:
                    args = json.loads(tc["function"]["arguments"])
                except (json.JSONDecodeError, KeyError):
                    args = {}

                if fn_name == "search_web" and search_enabled:
                    query = (args.get("query") or "").strip()[:200]
                    if query:
                        log.info(f"AI requested search (tool, round {_round + 1}): {query}")
                        _search_used = True
                        try:
                            search_ctx = await search_and_fetch(query)
                        except Exception as e:
                            log.error(f"Search failed: {e}")
                            search_ctx = ""
                        augmented.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "content": (
                                f"[Web search results for '{query}' — use this to answer accurately. "
                                "Summarize clearly in your own words, do not paste raw text or cite sources.]\n"
                                + (search_ctx or "No results found.")
                            ),
                        })
                        used_tool_names.add("search_web")

                elif fn_name == "run_skill":
                    skill_name = (args.get("skill_name") or "").strip()
                    input_data = args.get("input_data") or {}
                    log.info(f"AI requested skill '{skill_name}' (round {_round + 1}): {input_data}")
                    skill_result = skills.run_skill(skill_name, input_data)
                    augmented.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": (
                            f"[Skill '{skill_name}' result]\n"
                            + (skill_result.get("message", "") if skill_result.get("success")
                               else f"Error: {skill_result.get('message', 'unknown error')}")
                        ),
                    })
                    used_tool_names.add("run_skill")

                elif fn_name in _HA_TOOL_NAMES:
                    log.info(f"AI requested HA tool '{fn_name}' (round {_round + 1}): {args}")
                    ha_result = await ha_api.run_ha_tool(fn_name, args)
                    augmented.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": f"[Home Assistant — {fn_name}]\n{ha_result}",
                    })
                    used_tool_names.add(fn_name)

            # Re-call without used tools to avoid loops
            # Use secondary provider if configured (cost reduction / faster processing)
            re_provider = secondary or active
            re_tools = [t for t in all_tools if t.get("function", {}).get("name") not in used_tool_names]
            result = await providers.chat_completion(
                augmented, model=model, tools=re_tools or None,
                tool_choice=tool_choice, provider=re_provider,
            )
            # Track secondary provider re-call
            if secondary and re_provider is secondary:
                _secondary_used_for_recall = True

        # If final result still has non-internal tool_calls, forward to client
        final_msg = result.get("choices", [{}])[0].get("message", {})
        if final_msg.get("tool_calls"):
            remaining = [tc for tc in final_msg["tool_calls"] if tc.get("function", {}).get("name") not in _INTERNAL_TOOLS]
            if remaining:
                final_msg["tool_calls"] = remaining
                final_msg["content"] = ""
                return JSONResponse(content=result)
            else:
                del final_msg["tool_calls"]

        assistant_content = final_msg.get("content", "") or ""

        # Strip any legacy <<SEARCH>> markers from content
        if assistant_content and _SEARCH_MARKER_STRIP.search(assistant_content):
            assistant_content = _strip_search_markers(assistant_content)
            result["choices"][0]["message"]["content"] = assistant_content

        # Save & extract memories
        if assistant_content:
            add_conversation_message(user_id, "assistant", assistant_content)
            all_msgs = messages + [{"role": "assistant", "content": assistant_content}]
            asyncio.create_task(_safe_extract(user_id, all_msgs, provider=secondary))

        # Track usage statistics
        _elapsed_ms = int((time.time() - _req_start) * 1000)
        log.info(f"[{user_id}] Response: {len(assistant_content or '')} chars, {_elapsed_ms}ms, search={_search_used}")
        try:
            usage = result.get("usage", {})
            stat_prov = secondary if _secondary_used_for_recall and secondary else active
            add_usage_stat(
                user_id=user_id, provider_id=stat_prov.get("id", ""),
                provider_name=stat_prov.get("name", ""), provider_type=stat_prov.get("type", ""),
                model=result.get("model", model or stat_prov.get("model", "")),
                tokens_prompt=usage.get("prompt_tokens", 0),
                tokens_completion=usage.get("completion_tokens", 0),
                tokens_total=usage.get("total_tokens", 0),
                response_time_ms=int((time.time() - _req_start) * 1000),
                stream=False, search_used=_search_used,
                eco_mode=bool(active.get("eco_mode")),
                secondary_used=_secondary_used_for_recall,
            )
        except Exception:
            pass

        return JSONResponse(content=result)

    # ── Streaming path ──
    # Uses tool_calls for search (like hass_memory). No marker parsing needed.
    # Tool call chunks are accumulated silently; content/reasoning chunks pass through.
    gen = providers.chat_completion_stream(augmented, model=model, tools=effective_tools, tool_choice=tool_choice, provider=active)

    async def stream_wrapper():
        nonlocal augmented
        full_response = ""
        # Accumulate streaming tool_call deltas
        tc_accum: dict[int, dict] = {}  # index -> {id, name, arguments}
        tc_chunks: list[str] = []  # raw chunks for forwarding if not search
        has_tool_calls = False

        async for chunk in _stream_with_keepalive_sse(gen):
            if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                try:
                    data = json.loads(chunk[6:])
                    delta = data.get("choices", [{}])[0].get("delta", {})
                except (json.JSONDecodeError, IndexError, KeyError):
                    yield chunk
                    continue

                content = delta.get("content") or ""
                reasoning = delta.get("reasoning_content")
                tool_calls_delta = delta.get("tool_calls")
                finish_reason = data.get("choices", [{}])[0].get("finish_reason")

                # Tool call delta — accumulate silently (don't yield to client yet)
                if tool_calls_delta:
                    has_tool_calls = True
                    tc_chunks.append(chunk)
                    for tc in tool_calls_delta:
                        idx = tc.get("index", 0)
                        if idx not in tc_accum:
                            tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.get("id"):
                            tc_accum[idx]["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            tc_accum[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tc_accum[idx]["arguments"] += fn["arguments"]
                    continue

                # Suppress finish chunk when we have accumulated tool_calls
                # (we'll handle search and re-stream on [DONE])
                if has_tool_calls and finish_reason:
                    continue

                # Reasoning content — yield immediately (user sees "thinking")
                if reasoning:
                    yield chunk
                    continue

                # Regular content — yield directly (no buffering!)
                if content:
                    full_response += content
                yield chunk

            elif chunk.strip() == "data: [DONE]":
                # Stream finished — handle accumulated tool_calls
                if has_tool_calls and tc_accum:
                    # Identify internal tool calls we handle (search_web, run_skill, HA)
                    internal_calls = {idx: td for idx, td in tc_accum.items() if td["name"] in _INTERNAL_TOOLS}

                    if internal_calls:
                        # Build all tool_calls for the assistant message
                        all_tcs = [
                            {
                                "id": td["id"] or f"call_{idx}",
                                "type": "function",
                                "function": {"name": td["name"], "arguments": td["arguments"]},
                            }
                            for idx, td in tc_accum.items()
                        ]
                        augmented.append({"role": "assistant", "content": None, "tool_calls": all_tcs})

                        # Process each internal tool call
                        used_tool_names = set()
                        for idx, td in internal_calls.items():
                            tc_id = td["id"] or f"call_{idx}"
                            try:
                                args = json.loads(td["arguments"])
                            except (json.JSONDecodeError, KeyError):
                                args = {}

                            if td["name"] == "search_web" and search_enabled:
                                query = (args.get("query") or "").strip()[:200]
                                if query:
                                    log.info(f"AI requested search (stream/tool): {query}")
                                    search_ctx = ""
                                    try:
                                        search_ctx = await search_and_fetch(query)
                                    except Exception as e:
                                        log.error(f"Search failed: {e}")
                                    augmented.append({
                                        "role": "tool",
                                        "tool_call_id": tc_id,
                                        "content": (
                                            f"[Web search results for '{query}' — use this to answer accurately. "
                                            "Summarize clearly in your own words, do not paste raw text or cite sources.]\n"
                                            + (search_ctx or "No results found.")
                                        ),
                                    })
                                    used_tool_names.add("search_web")

                            elif td["name"] == "run_skill":
                                skill_name = (args.get("skill_name") or "").strip()
                                input_data = args.get("input_data") or {}
                                log.info(f"AI requested skill '{skill_name}' (stream): {input_data}")
                                skill_result = skills.run_skill(skill_name, input_data)
                                augmented.append({
                                    "role": "tool",
                                    "tool_call_id": tc_id,
                                    "content": (
                                        f"[Skill '{skill_name}' result]\n"
                                        + (skill_result.get("message", "") if skill_result.get("success")
                                           else f"Error: {skill_result.get('message', 'unknown error')}")
                                    ),
                                })
                                used_tool_names.add("run_skill")

                            elif td["name"] in _HA_TOOL_NAMES:
                                log.info(f"AI requested HA tool '{td['name']}' (stream): {args}")
                                ha_result = await ha_api.run_ha_tool(td["name"], args)
                                augmented.append({
                                    "role": "tool",
                                    "tool_call_id": tc_id,
                                    "content": f"[Home Assistant — {td['name']}]\n{ha_result}",
                                })
                                used_tool_names.add(td["name"])

                        # Re-stream without used tools
                        # Use secondary provider if configured (cost reduction / faster processing)
                        re_provider = secondary or active
                        if secondary and re_provider is secondary:
                            _secondary_used_for_recall = True
                        re_tools = [t for t in all_tools if t.get("function", {}).get("name") not in used_tool_names]
                        gen2 = providers.chat_completion_stream(
                            augmented, model=model, tools=re_tools or None,
                            tool_choice=tool_choice, provider=re_provider,
                        )
                        async for chunk2 in gen2:
                            if chunk2.startswith("data: ") and chunk2.strip() != "data: [DONE]":
                                try:
                                    d2 = json.loads(chunk2[6:])
                                    t2 = d2.get("choices", [{}])[0].get("delta", {}).get("content") or ""
                                    if t2:
                                        full_response += t2
                                except (json.JSONDecodeError, IndexError, KeyError):
                                    pass
                            yield chunk2

                        # Save & extract
                        if full_response:
                            add_conversation_message(user_id, "assistant", full_response)
                            all_msgs = messages + [{"role": "assistant", "content": full_response}]
                            asyncio.create_task(_safe_extract(user_id, all_msgs, provider=secondary))
                        try:
                            stat_prov = secondary if _secondary_used_for_recall and secondary else active
                            add_usage_stat(
                                user_id=user_id, provider_id=stat_prov.get("id", ""),
                                provider_name=stat_prov.get("name", ""), provider_type=stat_prov.get("type", ""),
                                model=model or stat_prov.get("model", ""),
                                tokens_prompt=_prompt_tokens, tokens_completion=_estimate_tokens(full_response),
                                tokens_total=_prompt_tokens + _estimate_tokens(full_response),
                                response_time_ms=int((time.time() - _req_start) * 1000),
                                stream=True, search_used=bool(used_tool_names),
                                eco_mode=bool(active.get("eco_mode")),
                                secondary_used=_secondary_used_for_recall,
                            )
                        except Exception:
                            pass
                        return

                    # No internal tool calls — forward buffered tool_call chunks to client (HA)
                    for tc_chunk in tc_chunks:
                        yield tc_chunk
                    yield chunk  # forward the [DONE]

                else:
                    # No tool_calls — just forward [DONE]
                    yield chunk

            else:
                # Keepalive comments or other non-data lines — pass through
                yield chunk

        if full_response:
            clean_response = _strip_search_markers(full_response) if "<<SEARCH" in full_response else full_response
            add_conversation_message(user_id, "assistant", clean_response)
            all_msgs = messages + [{"role": "assistant", "content": clean_response}]
            asyncio.create_task(_safe_extract(user_id, all_msgs, provider=secondary))

        _stream_elapsed = int((time.time() - _req_start) * 1000)
        log.info(f"[{user_id}] Stream response: {len(full_response)} chars, {_stream_elapsed}ms")
        try:
            add_usage_stat(
                user_id=user_id, provider_id=active.get("id", ""),
                provider_name=active.get("name", ""), provider_type=active.get("type", ""),
                model=model or active.get("model", ""),
                tokens_prompt=_prompt_tokens, tokens_completion=_estimate_tokens(full_response),
                tokens_total=_prompt_tokens + _estimate_tokens(full_response),
                response_time_ms=int((time.time() - _req_start) * 1000),
                stream=True, search_used=False,
                eco_mode=bool(active.get("eco_mode")),
                secondary_used=False,
            )
        except Exception:
            pass

    return StreamingResponse(stream_wrapper(), media_type="text/event-stream")


# Per-user extraction locks to prevent concurrent duplicate extractions (#6)
_extraction_locks: dict[str, asyncio.Lock] = {}
_EXTRACTION_TIMEOUT = 30.0  # seconds (#8)


async def _safe_extract(user_id: str, messages: list[dict], provider: dict | None = None):
    """Safely run memory extraction in background with per-user lock and timeout."""
    if user_id not in _extraction_locks:
        _extraction_locks[user_id] = asyncio.Lock()

    # Skip if another extraction is already running for this user
    if _extraction_locks[user_id].locked():
        log.debug(f"Skipping extraction for {user_id} — already in progress")
        return

    async with _extraction_locks[user_id]:
        try:
            await asyncio.wait_for(
                extract_memories_from_conversation(user_id, messages, provider=provider),
                timeout=_EXTRACTION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning(f"Memory extraction timed out for {user_id} (>{_EXTRACTION_TIMEOUT}s)")
        except Exception as e:
            log.error(f"Background memory extraction failed: {e}")


@router.get("/v1/models")
async def list_models():
    try:
        models = await providers.list_models()
        return {"object": "list", "data": models}
    except Exception as e:
        # Bridge is up but provider unreachable — return empty list so HA can
        # still connect; chat will surface a clearer error later.
        log.warning(f"Could not list models from provider: {e}")
        return {"object": "list", "data": []}
