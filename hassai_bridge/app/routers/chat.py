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
from services import provider_capabilities as pc
from services import searxng, skills
from services.memory_engine import (
    retrieve_relevant_memories,
    build_memory_context,
    extract_memories_from_conversation,
)
from services.web_scraper import search_and_fetch
from services import homeassistant as ha_api
from services import lovelace_tools as lt
from services import entity_tools as et
from services import chat_content as cc
from services import chat_media as cm
from services import gemini as gm
from services import memory_tools as mt
from services import bridge_tools as bt
from services import pricing
from services import tool_profiles as tp
# `router` is the FastAPI APIRouter below — alias the routing service.
from services import router as provider_router

log = logging.getLogger("hassai.chat")
router = APIRouter()

_MEDIA_TOOL_NAMES = {"media_list", "media_read", "media_delete"}
_FRIGATE_TOOL_NAMES = {"frigate_list_cameras", "frigate_events", "frigate_snapshot"}


def _is_internal_tool(fn_name: str, cfg: dict) -> bool:
    if fn_name in ("search_web", "run_skill", "generate_image"):
        return True
    if fn_name in _MEDIA_TOOL_NAMES or fn_name in _FRIGATE_TOOL_NAMES:
        return True
    if fn_name in mt.TOOL_NAMES or bt.is_bridge_tool(fn_name):
        return True
    return ha_api.is_ha_tool(fn_name, cfg)

# Identical tool+args this many times → skip and tell the model to move on.
_AGENT_REPEAT_LIMIT = 2


def _agent_max_rounds(cfg: dict) -> int:
    raw = (cfg.get("performance") or {}).get("agent_max_rounds", 16)
    try:
        n = int(raw)
    except (TypeError, ValueError):
        n = 16
    return max(2, min(n, 32))


def _agentic_instruction() -> str:
    """Always injected so the model keeps working like Cursor, not Q&A."""
    return (
        "Work style: autonomous agent. Finish the job; do not narrate a plan and wait. "
        "Keep using tools until the task is actually done — inspect, change, verify, fix, then stop. "
        "Never ask \"should I continue?\" or \"want me to proceed?\". "
        "Read-only questions (explain, what does X do, list, show): use 1–3 tool calls, then answer clearly — do not loop tools or expose chain-of-thought. "
        "If the user asked you to change Home Assistant (entities, cards, files, automations, reloads), "
        "set confirm=true and do it. Only pause when the request is ambiguous or truly destructive "
        "and they did not ask for that change. End with a short summary of what you did."
    )


def resolve_provider_personality(active: dict | None, cfg: dict | None = None) -> tuple[str, str]:
    """Return ``(global_system_prompt, provider_personality)``.

    Provider Personality used to *replace* the global system prompt. That made short
    tone/style notes disappear under the mandatory Bridge / agentic hints — so users
    only saw an effect when they pasted the same text into the global field (where it
    sat next to the long HASSAI identity). Personality is now an overlay on top of
    the global prompt.
    """
    cfg = cfg or {}
    active = active or {}
    base = (cfg.get("system_prompt") or "").strip()
    persona = (active.get("system_prompt") or "").strip()
    return base, persona


def build_stable_system_parts(
    *,
    global_prompt: str = "",
    provider_personality: str = "",
    bridge_hint: str = "",
    memory_hint: str = "",
    agentic: str = "",
) -> list[str]:
    """Assemble the stable (KV-cache friendly) system prefix.

    Order matters: Bridge/agentic boilerplate comes before provider personality so
    tone/language/style instructions win when they conflict with identity hints.
    """
    parts: list[str] = []
    base = (global_prompt or "").strip()
    persona = (provider_personality or "").strip()
    if base:
        parts.append(base)
    if bridge_hint:
        parts.append(bridge_hint)
    if memory_hint:
        parts.append(memory_hint)
    if agentic:
        parts.append(agentic)
    if persona:
        parts.append(
            "Personality (follow for tone, language, and style):\n" + persona
        )
    return parts


def _inject_late_user_context(messages: list[dict], context: str) -> None:
    """Prefix volatile context onto the last user turn (KV-cache friendly).

    Stable system + conversation history stay byte-identical across turns; only
    the final user message carries fresh memory / retrieval context.
    """
    ctx = (context or "").strip()
    if not ctx or not messages:
        return
    prefix = ctx + "\n\n"
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") != "user":
            continue
        row = dict(messages[i])
        content = row.get("content")
        if isinstance(content, str):
            row["content"] = prefix + content if content else ctx
        elif isinstance(content, list):
            parts = list(content)
            if parts and isinstance(parts[0], dict) and parts[0].get("type") == "text":
                parts[0] = {
                    **parts[0],
                    "text": prefix + str(parts[0].get("text") or ""),
                }
            else:
                parts.insert(0, {"type": "text", "text": prefix})
            row["content"] = parts
        else:
            row["content"] = ctx
        messages[i] = row
        return
    messages.append({"role": "system", "content": ctx})


# Text a model writes in the same turn as a tool call is narration ("let me
# check the terrace light"), not the answer. It belongs in the step timeline —
# in the chat body it reads like padding, and the voice reads it out loud.
_SAY_DETAIL_MAX = 400


def _say_event(round_i: int, text: str) -> dict | None:
    clean = " ".join(str(text or "").split())
    if not clean:
        return None
    if len(clean) > _SAY_DETAIL_MAX:
        clean = clean[:_SAY_DETAIL_MAX].rsplit(" ", 1)[0] + "…"
    return {"id": f"say-{round_i}", "name": "say", "detail": clean, "status": "done"}


def _tool_fingerprint(name: str, args: dict) -> str:
    try:
        payload = json.dumps(args or {}, sort_keys=True, default=str)
    except TypeError:
        payload = str(args)
    return f"{name}:{payload[:600]}"


def _tool_names(tool_calls: list[dict]) -> list[str]:
    names: list[str] = []
    for tc in tool_calls or []:
        fn = (tc.get("function") or {}).get("name") or ""
        if fn:
            names.append(fn)
    return names


def _parse_thinking_override(raw) -> str | None:
    if raw is None:
        return None
    from services.deepseek import THINKING_MODES

    mode = str(raw).strip().lower()
    return mode if mode in THINKING_MODES else None


def _recall_provider(
    tool_calls: list[dict],
    active: dict,
    secondary: dict | None,
    *,
    image_provider: dict | None = None,
    image_gen_provider: dict | None = None,
) -> dict:
    if image_provider is not None:
        return image_provider
    names = _tool_names(tool_calls)
    if any(name == "generate_image" for name in names):
        return image_gen_provider or active
    from services import secondary_routing as sr

    if secondary and sr.secondary_handles_tools(secondary, names):
        return secondary
    return active


_SECONDARY_TOOLS_HINT = (
    "You are the tool-orchestration helper for this turn. "
    "Call tools if you still need facts. "
    "Do not write the final user-facing answer — another model will speak to the user."
)


def _messages_for_secondary_tools(messages: list[dict]) -> list[dict]:
    """Transcript for secondary tool rounds (hint: tools only, no final voice)."""
    return list(messages) + [{"role": "system", "content": _SECONDARY_TOOLS_HINT}]


def _should_finalize_on_primary(
    *,
    active: dict,
    secondary: dict | None,
    call_provider: dict | None,
    tool_calls: list | None,
) -> bool:
    """Secondary produced a text answer — primary should speak to the user."""
    if not secondary or call_provider is None:
        return False
    if call_provider is not secondary and call_provider.get("id") != secondary.get("id"):
        return False
    return not (tool_calls or [])


def _vision_required_error(cfg: dict) -> JSONResponse:
    lang = cfg.get("language") or "en"
    if lang == "ro":
        message = (
            "Providerul activ nu suportă imagini. Configurează un LLM Vision sau un provider "
            "auxiliar (secundar) pentru poze, sau alege un model vision la providerul principal."
        )
    else:
        message = (
            "The active provider/model does not support images. Configure a Vision LLM or "
            "auxiliary (secondary) provider for images, or choose a vision-capable primary model."
        )
    return JSONResponse(
        status_code=400,
        content={"error": {"message": message, "type": "invalid_request_error"}},
    )


def _provider_upstream_error(exc: Exception) -> JSONResponse:
    from services.provider_errors import sanitize_error_message

    return JSONResponse(
        status_code=502,
        content={
            "error": {
                "message": sanitize_error_message(str(exc)),
                "type": "upstream_error",
            },
        },
    )


def _should_skip_repeated_tool(name: str, args: dict, fingerprints: list[str], fp: str) -> bool:
    if name in lt.HA_MUTATING_TOOLS:
        return False
    if name in et.HA_ENTITY_TOOLS:
        if name == "ha_get_state":
            return False
        if name == "ha_list_entities" and args.get("offset"):
            return False
    if name == "ha_get_dashboard" and args.get("include_cards"):
        return False
    return fingerprints.count(fp) >= _AGENT_REPEAT_LIMIT


def _maybe_extend_tool_rounds(tool_calls: list[dict], round_idx: int, round_limit: int) -> int:
    if round_idx >= round_limit - 1 and any(name in lt.HA_MUTATING_TOOLS for name in _tool_names(tool_calls)):
        return round_limit + 1
    return round_limit


def _agent_incomplete_notice(tool_names: list[str]) -> str:
    unique = sorted({n for n in tool_names if n})
    preview = ", ".join(unique[:4])
    if len(unique) > 4:
        preview += ", …"
    detail = f" ({preview})" if preview else ""
    return (
        "\n\n---\n"
        "I ran out of agent steps before finishing all requested actions"
        f"{detail}. Ask me to continue and I will pick up where I left off."
    )


def _parse_tool_args(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def _clip_detail(value, n: int = 56) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _tool_detail(name: str, args: dict) -> str:
    args = args or {}
    if name == "search_web":
        return _clip_detail(args.get("query"))
    if name == "generate_image":
        return _clip_detail(args.get("prompt"))
    if name == "run_skill":
        return _clip_detail(args.get("skill_name"))
    if name in {"media_list", "media_read", "media_delete"}:
        return _clip_detail(args.get("path") or args.get("search") or "")
    if name in _FRIGATE_TOOL_NAMES:
        return _clip_detail(
            args.get("camera") or args.get("event_id") or args.get("label") or ""
        )
    if name in mt.TOOL_NAMES:
        return _clip_detail(mt.tool_detail(name, args))
    if bt.is_bridge_tool(name):
        return _clip_detail(bt.tool_detail(name, args))
    if name == "ha_call_service":
        call = f"{args.get('domain') or ''}.{args.get('service') or ''}".strip(".")
        entity = str(args.get("entity_id") or "").strip()
        return _clip_detail(" ".join(p for p in (call, entity) if p))
    if name == "ha_update_entity":
        bits = [
            args.get("entity_id") or "",
            args.get("name") or args.get("area_name") or args.get("area_id") or "",
        ]
        return _clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_set_state":
        return _clip_detail(f"{args.get('entity_id') or ''} → {args.get('state') or ''}".strip())
    if name == "ha_get_entity_registry":
        return _clip_detail(args.get("entity_id"))
    if name == "ha_get_device":
        return _clip_detail(args.get("device_id"))
    if name == "ha_update_device":
        bits = [
            args.get("device_id") or "",
            args.get("area_name") or args.get("area_id") or args.get("name_by_user") or "",
        ]
        return _clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_create_area":
        return _clip_detail(args.get("name"))
    if name == "ha_update_area":
        return _clip_detail(f"{args.get('area_id') or ''} {args.get('name') or ''}".strip())
    if name == "ha_create_label":
        return _clip_detail(args.get("name"))
    if name == "ha_update_label":
        return _clip_detail(f"{args.get('label_id') or ''} {args.get('name') or ''}".strip())
    if name == "ha_get_history":
        ids = args.get("entity_ids") if isinstance(args.get("entity_ids"), list) else []
        preview = args.get("entity_id") or (", ".join(str(i) for i in ids[:2]) if ids else "")
        hours = args.get("hours")
        return _clip_detail(f"{preview} {hours}h".strip() if hours else preview)
    if name == "ha_get_logbook":
        bits = [args.get("entity_id") or "", f"{args.get('hours')}h" if args.get("hours") else ""]
        return _clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_get_entity_source":
        return _clip_detail(args.get("entity_id") or args.get("search") or args.get("domain"))
    if name == "ha_expose_entity":
        ids = args.get("entity_ids") if isinstance(args.get("entity_ids"), list) else []
        preview = args.get("entity_id") or (", ".join(str(i) for i in ids[:2]) if ids else "")
        flag = "show" if args.get("should_expose") else "hide"
        return _clip_detail(f"{flag} {preview}".strip())
    if name in {"ha_trigger_automation", "ha_run_script", "ha_activate_scene"}:
        return _clip_detail(args.get("entity_id"))
    if name == "ha_get_automation":
        return _clip_detail(args.get("entity_id") or args.get("search") or args.get("name"))
    if name in {"ha_delete_automation", "ha_delete_script", "ha_delete_scene"}:
        return _clip_detail(args.get("entity_id") or args.get("search") or args.get("name"))
    if name == "ha_create_floor":
        return _clip_detail(args.get("name"))
    if name == "ha_update_floor":
        return _clip_detail(f"{args.get('floor_id') or ''} {args.get('name') or ''}".strip())
    if name == "ha_get_config_entry":
        return _clip_detail(args.get("entry_id"))
    if name == "ha_reload_config_entry":
        return _clip_detail(args.get("entry_id"))
    if name == "ha_get_statistics":
        sid = args.get("statistic_id") or args.get("entity_id") or ""
        return _clip_detail(f"{sid} {args.get('period') or 'hour'}".strip())
    if name == "ha_upsert_card":
        card = args.get("card") if isinstance(args.get("card"), dict) else {}
        bits = [
            args.get("view_path") or args.get("view_title") or "",
            args.get("section_index") if args.get("section_index") is not None else "",
            card.get("type") or "",
            card.get("entity") or "",
        ]
        return _clip_detail(" · ".join(str(b) for b in bits if b != ""))
    if name == "ha_delete_card":
        bits = [
            args.get("view_path") or args.get("view_title") or "",
            args.get("card_path") or "",
            args.get("card_index") if args.get("card_index") is not None else "",
        ]
        return _clip_detail(" · ".join(str(b) for b in bits if b != ""))
    if name == "ha_upsert_view":
        return _clip_detail(args.get("title") or args.get("view_path") or args.get("path") or args.get("view_title"))
    if name == "ha_create_dashboard":
        return _clip_detail(f"{args.get('title') or ''} {args.get('url_path') or ''}".strip())
    if name == "ha_delete_view":
        return _clip_detail(args.get("view_path") or args.get("view_title") or args.get("view_index"))
    if name == "ha_update_dashboard":
        return _clip_detail(f"{args.get('url_path') or ''} {args.get('title') or ''}".strip())
    if name == "ha_delete_dashboard":
        return _clip_detail(args.get("url_path"))
    if name == "ha_append_card_yaml":
        card = args.get("card") if isinstance(args.get("card"), dict) else {}
        bits = [
            args.get("dashboard_url") or args.get("url_path") or "Overview",
            args.get("view_path") or args.get("view_title") or "",
            card.get("type") or "",
        ]
        return _clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_get_dashboard":
        bits = [
            args.get("url_path") or "Overview",
            args.get("view_path") or args.get("view_title") or "",
        ]
        return _clip_detail(" · ".join(str(b) for b in bits if b))
    for key in ("entity_id", "path", "url_path", "view_path", "suggestion_id", "what", "source", "domain", "search"):
        val = args.get(key)
        if val:
            extra = args.get("search") if key == "domain" else None
            return _clip_detail(f"{val} {extra}".strip() if extra else val)
    return ""


_TRACE_TTL = 600.0
_traces: dict[str, dict] = {}
# One active background job per conversation session (session_id → trace_id).
_session_jobs: dict[str, str] = {}


class TraceCancelled(Exception):
    """Raised when a chat trace is cancelled via /v1/chat/cancel."""

    def __init__(self, trace_id: str = ""):
        self.trace_id = trace_id
        super().__init__("cancelled")


def _sanitize_trace_id(raw) -> str:
    value = str(raw or "").strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{8,48}", value):
        return value
    return ""


def _trace_gc() -> None:
    now = time.time()
    stale = [key for key, bucket in _traces.items() if now - bucket.get("ts", 0) > _TRACE_TTL]
    for key in stale:
        bucket = _traces.pop(key, None) or {}
        sid = str(bucket.get("session_id") or "")
        if sid and _session_jobs.get(sid) == key:
            _session_jobs.pop(sid, None)


def _trace_start(
    trace_id: str,
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    model: str | None = None,
    provider_name: str | None = None,
    route: dict | None = None,
) -> None:
    if not trace_id:
        return
    _trace_gc()
    _traces[trace_id] = {
        "events": [],
        "done": False,
        "cancelled": False,
        "ts": time.time(),
        "session_id": str(session_id or ""),
        "user_id": str(user_id or ""),
        "status": "running",
        "error": "",
        "model": str(model or "").strip(),
        "provider": str(provider_name or "").strip(),
        "route": dict(route) if isinstance(route, dict) else {},
    }


def _trace_cancelled(trace_id: str) -> bool:
    if not trace_id or trace_id not in _traces:
        return False
    return bool(_traces[trace_id].get("cancelled"))


def _trace_cancel(trace_id: str) -> bool:
    if not trace_id or trace_id not in _traces:
        return False
    bucket = _traces[trace_id]
    if bucket.get("done") or bucket.get("cancelled"):
        return False
    bucket["cancelled"] = True
    bucket["status"] = "cancelled"
    bucket["ts"] = time.time()
    return True


async def _check_trace(trace_id: str) -> None:
    if _trace_cancelled(trace_id):
        raise TraceCancelled(trace_id)


def _trace_push(trace_id: str, event: dict) -> dict:
    payload = dict(event)
    if trace_id and trace_id in _traces:
        bucket = _traces[trace_id]
        payload["i"] = len(bucket["events"])
        bucket["events"].append(payload)
        bucket["ts"] = time.time()
    return payload


def _trace_done(trace_id: str, *, error: str = "") -> None:
    if not trace_id or trace_id not in _traces:
        return
    bucket = _traces[trace_id]
    bucket["done"] = True
    bucket["ts"] = time.time()
    if error:
        bucket["error"] = str(error)[:500]
        if not bucket.get("cancelled"):
            bucket["status"] = "error"
    elif bucket.get("cancelled"):
        bucket["status"] = "cancelled"
    else:
        bucket["status"] = "done"
    sid = str(bucket.get("session_id") or "")
    if sid and _session_jobs.get(sid) == trace_id:
        _session_jobs.pop(sid, None)


def _session_job_running(session_id: str | None) -> str | None:
    """Return active trace_id for session, or None."""
    sid = str(session_id or "").strip()
    if not sid:
        return None
    tid = _session_jobs.get(sid)
    if not tid:
        return None
    bucket = _traces.get(tid)
    if not bucket or bucket.get("done"):
        _session_jobs.pop(sid, None)
        return None
    return tid


def _register_session_job(session_id: str | None, trace_id: str) -> None:
    sid = str(session_id or "").strip()
    if sid and trace_id:
        _session_jobs[sid] = trace_id


def _activity_status_payload(bucket: dict | None, after: int = -1) -> dict:
    if not bucket:
        return {"events": [], "after": after, "done": False, "cancelled": False, "status": "unknown"}
    events = [ev for ev in bucket["events"] if int(ev.get("i", 0)) > after]
    last = events[-1]["i"] if events else after
    status = bucket.get("status") or ("done" if bucket.get("done") else "running")
    return {
        "events": events,
        "after": last,
        "done": bool(bucket.get("done")),
        "cancelled": bool(bucket.get("cancelled")),
        "status": status,
        "session_id": bucket.get("session_id") or "",
        "error": bucket.get("error") or "",
        "model": bucket.get("model") or "",
        "provider": bucket.get("provider") or "",
    }


_REASONING_DETAIL_MAX = 8000
# Stored CoT is replayed to DeepSeek on later tool turns — keep more than the UI shows.
_REASONING_STORE_MAX = 40_000


def _clip_reasoning(text: str | None) -> str:
    raw = (text or "").strip()
    if len(raw) <= _REASONING_DETAIL_MAX:
        return raw
    return raw[:_REASONING_DETAIL_MAX] + "…"


def _store_reasoning(text: str | None) -> str:
    raw = (text or "").strip()
    return raw[:_REASONING_STORE_MAX]


def _message_reasoning(message: dict | None) -> str:
    if not isinstance(message, dict):
        return ""
    return _clip_reasoning(message.get("reasoning_content") or "")


def _message_reasoning_full(message: dict | None) -> str:
    if not isinstance(message, dict):
        return ""
    return _store_reasoning(message.get("reasoning_content") or "")


def _compact_activity(events: list | None) -> list[dict]:
    """Keep the last status per step id (running → done) for storage."""
    if not events:
        return []
    latest: dict[str, dict] = {}
    order: list[str] = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        # Live token previews are for the UI poll only — don't persist the full reply.
        if ev.get("name") in ("assistant", "route"):
            continue
        eid = str(ev.get("id") or "")
        if not eid:
            continue
        if eid not in latest:
            order.append(eid)
        row = dict(latest.get(eid) or {"id": eid})
        for key in ("id", "name", "detail", "status", "ms"):
            val = ev.get(key)
            if val not in (None, ""):
                row[key] = val
        latest[eid] = row
    out = []
    for eid in order:
        row = dict(latest[eid])
        if row.get("status") == "running":
            row["status"] = "done"
        out.append(row)
    return out


_TOOL_ARG_CHARS = 400
_TOOL_RESULT_CHARS = 240
# How many recent stored turns replay their tool calls to the model.
_TOOL_REPLAY_TURNS = 6


def _tool_trace(messages: list[dict], start: int) -> list[dict]:
    """Compact record of the tools this turn actually ran, for the transcript.

    Stored so the next turn can replay real calls instead of a bare sentence
    claiming the job is done.
    """
    results: dict[str, str] = {}
    for msg in messages[start:]:
        if msg.get("role") == "tool":
            results[str(msg.get("tool_call_id") or "")] = str(msg.get("content") or "")
    trace: list[dict] = []
    for msg in messages[start:]:
        if msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            fn = call.get("function") or {}
            name = str(fn.get("name") or "")
            if not name:
                continue
            call_id = str(call.get("id") or "")
            trace.append({
                "id": call_id,
                "name": name,
                "arguments": str(fn.get("arguments") or "{}")[:_TOOL_ARG_CHARS],
                "result": results.get(call_id, "")[:_TOOL_RESULT_CHARS],
            })
    return trace


def _activity_meta(
    trace_id: str,
    events: list | None = None,
    attachments: list | None = None,
    reasoning_content: str | None = None,
    tool_calls: list | None = None,
    *,
    model: str | None = None,
    provider_name: str | None = None,
    route: dict | None = None,
) -> dict | None:
    merged = list(events or [])
    if trace_id and trace_id in _traces:
        stored = _traces[trace_id].get("events") or []
        if stored:
            merged = list(stored)
    compact = _compact_activity(merged)
    meta: dict = {}
    if compact:
        meta["activity"] = compact
    if attachments:
        meta["attachments"] = attachments
    if tool_calls:
        meta["tool_calls"] = tool_calls
    model_name = str(model or "").strip()
    if model_name:
        meta["model"] = model_name
    prov = str(provider_name or "").strip()
    if prov:
        meta["provider"] = prov
    if isinstance(route, dict):
        for key in ("role", "reason", "klass", "auto"):
            if key in route:
                meta[f"route_{key}" if key != "auto" else "route_auto"] = route[key]
    reasoning = _store_reasoning(reasoning_content)
    if reasoning:
        meta["reasoning_content"] = reasoning
    elif compact:
        # Recover CoT from the last think activity step when explicit field missing
        for ev in reversed(compact):
            if ev.get("name") == "think" and ev.get("detail"):
                meta["reasoning_content"] = _store_reasoning(str(ev.get("detail") or ""))
                break
    return meta or None


def _reasoning_from_row_meta(meta: dict | None) -> str:
    if not isinstance(meta, dict):
        return ""
    direct = _store_reasoning(meta.get("reasoning_content") or "")
    if direct:
        return direct
    for ev in reversed(meta.get("activity") or []):
        if isinstance(ev, dict) and ev.get("name") == "think" and ev.get("detail"):
            return _store_reasoning(str(ev.get("detail") or ""))
    return ""


def _markdown_for_generated_attachments(
    attachments: list[dict],
    session_id: str | None = None,
    existing_text: str = "",
) -> str:
    """Inline markdown for images the model created.

    Frigate snapshots and files opened from /media ride in the same list, but the
    chat already draws those from the message attachments — emitting markdown for
    them too put a second, broken copy under the snapshot labelled
    "Generated image".
    """
    parts: list[str] = []
    haystack = existing_text or ""
    for att in attachments or []:
        if str(att.get("source") or "") != "generated":
            continue
        att_id = str(att.get("id") or "").strip()
        if not att_id:
            continue
        url = cm.attachment_public_url(att_id, session_id or "")
        if att_id in haystack or url in haystack:
            continue
        parts.append(f"![Generated image]({url})")
    return "\n\n".join(parts)


def _finalize_image_only_result(
    *,
    model: str | None,
    session_id: str | None,
    generated_attachments: list[dict],
    activity_events: list | None = None,
) -> dict:
    """Build a chat.completion payload after Imagine — no second LLM round (avoids Ingress 504)."""
    md = _markdown_for_generated_attachments(generated_attachments, session_id, "")
    content = md or "Image generated."
    return {
        "id": f"img-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "hassai-bridge",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "hassai_activity": activity_events or [],
        "hassai_generated_attachments": generated_attachments,
    }


def _only_image_gen_tools(tool_calls: list[dict]) -> bool:
    names = [n for n in _tool_names(tool_calls) if n]
    return bool(names) and all(n == "generate_image" for n in names)


def _cancelled_openai_response(model, activity_events: list | None = None) -> dict:
    return {
        "id": f"cancel-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "hassai-bridge",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": ""},
            "finish_reason": "stop",
        }],
        "hassai_cancelled": True,
        "hassai_activity": activity_events or [],
    }


def _activity_sse(event: dict) -> str:
    payload = {"hassai": "activity", **event}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def _fire_activity(on_event, event: dict) -> None:
    if not on_event:
        return
    result = on_event(event)
    if asyncio.iscoroutine(result):
        await result


async def _invoke_internal_tool(
    fn_name: str,
    args: dict,
    *,
    search_enabled: bool,
    provider: dict | None = None,
    image_gen_provider: dict | None = None,
    user_id: str = "",
    session_id: str | None = None,
    generated_attachments: list | None = None,
) -> tuple[str, bool]:
    """Run one bridge-handled tool. Returns (result_text, search_used)."""
    if fn_name == "search_web" and search_enabled:
        query = (args.get("query") or "").strip()[:200]
        if not query:
            return "Error: empty search query.", False
        log.info("AI requested search: %s", query)
        try:
            search_ctx = await search_and_fetch(query)
        except Exception as e:
            log.error("Search failed: %s", e)
            search_ctx = ""
        return (
            f"[Web search results for '{query}' — use this to answer accurately. "
            "Summarize clearly in your own words, do not paste raw text or cite sources.]\n"
            + (search_ctx or "No results found."),
            True,
        )

    if fn_name == "generate_image":
        gen_provider = image_gen_provider or provider
        if not gen_provider or not pc.supports_image_generation(gen_provider):
            return (
                "Error: image generation is not available. Configure an Image Generation LLM "
                "(Grok) for this provider in Settings.",
                False,
            )
        prompt = (args.get("prompt") or "").strip()
        if not prompt:
            return "Error: empty image prompt.", False
        try:
            n = int(args.get("n") or 1)
        except (TypeError, ValueError):
            n = 1
        model = (args.get("model") or "").strip() or None
        log.info("AI requested image generation: %s", _clip_detail(prompt, 80))
        try:
            from services import grok as gk

            result = await gk.generate_image(
                gen_provider,
                prompt,
                model=model,
                n=n,
                user_id=user_id,
                session_id=session_id,
            )
        except Exception as e:
            log.error("Image generation failed: %s", e)
            return f"Error: image generation failed — {e}", False
        if generated_attachments is not None and result.get("attachments"):
            generated_attachments.extend(result["attachments"])
        return result.get("text") or "Image generated.", False

    if fn_name == "run_skill":
        skill_name = (args.get("skill_name") or "").strip()
        input_data = args.get("input_data") or {}
        log.info("AI requested skill '%s': %s", skill_name, input_data)
        skill_result = skills.run_skill(skill_name, input_data)
        body = (
            skill_result.get("message", "")
            if skill_result.get("success")
            else f"Error: {skill_result.get('message', 'unknown error')}"
        )
        return f"[Skill '{skill_name}' result]\n{body}", False

    if fn_name in _MEDIA_TOOL_NAMES:
        return await _run_media_tool(fn_name, args, user_id, generated_attachments), False

    if fn_name in _FRIGATE_TOOL_NAMES:
        return await _run_frigate_tool(fn_name, args, user_id, generated_attachments), False

    if fn_name in mt.TOOL_NAMES:
        log.info("AI requested memory tool '%s': %s", fn_name, args)
        return await asyncio.to_thread(mt.run_tool, fn_name, args, user_id), False

    if bt.is_bridge_tool(fn_name):
        log.info("AI requested bridge tool '%s': %s", fn_name, args)
        return await bt.run_tool(fn_name, args, user_id=user_id), False

    if ha_api.is_ha_tool(fn_name):
        log.info("AI requested HA tool '%s': %s", fn_name, args)
        ha_result = await ha_api.run_ha_tool(fn_name, args)
        return f"[Home Assistant — {fn_name}]\n{ha_result}", False

    return f"Error: unknown tool '{fn_name}'", False


async def _append_internal_tool_results(
    augmented: list,
    tool_calls: list[dict],
    *,
    search_enabled: bool,
    fingerprints: list[str],
    on_event=None,
    trace_id: str = "",
    provider: dict | None = None,
    image_gen_provider: dict | None = None,
    user_id: str = "",
    session_id: str | None = None,
    generated_attachments: list | None = None,
    cfg: dict | None = None,
) -> bool:
    """Append tool-role messages for internal calls. Returns search_used."""
    if cfg is None:
        cfg = load_config()
    search_used = False
    for tc in tool_calls:
        await _check_trace(trace_id)
        fn = tc.get("function") or {}
        fn_name = fn.get("name") or ""
        if not _is_internal_tool(fn_name, cfg):
            continue
        tc_id = tc.get("id") or f"call_{fn_name}"
        args = _parse_tool_args(fn.get("arguments"))
        detail = _tool_detail(fn_name, args)
        fp = _tool_fingerprint(fn_name, args)
        await _fire_activity(on_event, {
            "id": tc_id, "name": fn_name, "detail": detail, "status": "running",
        })
        started = time.time()
        if _should_skip_repeated_tool(fn_name, args, fingerprints, fp):
            log.info("Skipping repeated tool %s", fp[:80])
            content = (
                "Repeated tool call skipped — you already received this result. "
                "Do not call the same tool with the same arguments again. "
                "Continue with a different action or give the final answer."
            )
            await _fire_activity(on_event, {
                "id": tc_id, "name": fn_name, "detail": detail,
                "status": "skip", "ms": int((time.time() - started) * 1000),
            })
        else:
            fingerprints.append(fp)
            content, used_search = await _invoke_internal_tool(
                fn_name,
                args,
                search_enabled=search_enabled,
                provider=provider,
                image_gen_provider=image_gen_provider,
                user_id=user_id,
                session_id=session_id,
                generated_attachments=generated_attachments,
            )
            search_used = search_used or used_search
            await _fire_activity(on_event, {
                "id": tc_id, "name": fn_name, "detail": detail,
                "status": "done", "ms": int((time.time() - started) * 1000),
            })
        # Gemini's OpenAI-compat layer requires `name` on tool results
        # (maps to function_response.name). Other providers tolerate omission.
        augmented.append({
            "role": "tool",
            "tool_call_id": tc_id,
            "name": fn_name,
            "content": content,
        })
    return search_used

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
        "help.stats": "• `/stats [overview|users|memory|providers]` — Usage statistics",
        "help.consolidation": "• `/consolidation [on|off|daily|weekly|every Nh|now]` — Auto memory consolidation schedule",
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


        "lang.current": "🌐 **Language:** {lang}\n\nUse `/lang en` or `/lang ro` to change.",
        "lang.ok": "🌐 Language changed to **{lang}**",
        "lang.invalid": "❌ Unsupported language `{arg}`. Available: `en`, `ro`.",

        "consolidation.status": "🧠 **Auto consolidation:** {status}",
        "consolidation.hint": "Usage: `/consolidation on|off` · `daily [hour]` · `weekly [hour]` · `every 6h` · `now`",
        "consolidation.ok": "✅ Auto consolidation: **{status}**",
        "consolidation.now_ok": "✅ Consolidation finished for your memories.",
        "consolidation.now_fail": "❌ Consolidation failed: {error}",
        "consolidation.invalid": "❌ Invalid args.\n\n`/consolidation on|off` · `daily [0-23]` · `weekly [0-23]` · `every 6h` · `now`",

        "stats.title_overview": "📊 **Usage Statistics (last {days} days):**",
        "stats.totalRequests": "Total Requests",
        "stats.totalTokens": "Total Tokens",
        "stats.promptTokens": "Prompt",
        "stats.completionTokens": "Completion",
        "stats.searchRequests": "Search Requests",
        "stats.streamRequests": "Stream / Non-stream",
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
        "help.stats": "• `/stats [overview|users|memory|providers]` — Statistici utilizare",
        "help.consolidation": "• `/consolidation [on|off|daily|weekly|every Nh|now]` — Program consolidare automată memorie",
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


        "lang.current": "🌐 **Limbă:** {lang}\n\nFolosește `/lang en` sau `/lang ro` pentru a schimba.",
        "lang.ok": "🌐 Limba schimbată la **{lang}**",
        "lang.invalid": "❌ Limbă nesuportată `{arg}`. Disponibile: `en`, `ro`.",

        "consolidation.status": "🧠 **Consolidare automată:** {status}",
        "consolidation.hint": "Utilizare: `/consolidation on|off` · `daily [ora]` · `weekly [ora]` · `every 6h` · `now`",
        "consolidation.ok": "✅ Consolidare automată: **{status}**",
        "consolidation.now_ok": "✅ Consolidarea memoriilor tale s-a terminat.",
        "consolidation.now_fail": "❌ Consolidarea a eșuat: {error}",
        "consolidation.invalid": "❌ Argumente invalide.\n\n`/consolidation on|off` · `daily [0-23]` · `weekly [0-23]` · `every 6h` · `now`",

        "stats.title_overview": "📊 **Statistici utilizare (ultimele {days} zile):**",
        "stats.totalRequests": "Total cereri",
        "stats.totalTokens": "Total tokeni",
        "stats.promptTokens": "Prompt",
        "stats.completionTokens": "Completare",
        "stats.searchRequests": "Cereri cu căutare",
        "stats.streamRequests": "Stream / Non-stream",
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
                   "setmodel", "setprovider", "set2nd",
                   "stats", "consolidation", "lang", "version", "help"):
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

    elif command in ("/consolidation", "/consolidare"):
        from config import save_config
        from services.consolidation_schedule import format_status, normalize_auto_consolidation
        from services.memory_engine import consolidate_memories

        mem = cfg.setdefault("memory", {})
        ac = normalize_auto_consolidation(mem.get("auto_consolidation"))
        lang = cfg.get("language", "en")

        def _save_ac(block: dict) -> str:
            mem["auto_consolidation"] = normalize_auto_consolidation(block)
            save_config(cfg)
            return T("consolidation.ok", status=format_status(mem["auto_consolidation"], lang=lang))

        if not arg:
            return (
                f"{T('consolidation.status', status=format_status(ac, lang=lang))}\n\n"
                f"{T('consolidation.hint')}"
            )

        parts = arg.lower().split()
        action = parts[0]

        if action in ("on", "enable", "activ", "activeaza", "activează"):
            ac["enabled"] = True
            return _save_ac(ac)

        if action in ("off", "disable", "dezactiv", "dezactiveaza", "dezactivează"):
            ac["enabled"] = False
            return _save_ac(ac)

        if action in ("now", "acum", "run"):
            try:
                active = get_active_provider()
                await consolidate_memories(user_id, provider=active)
                return T("consolidation.now_ok")
            except Exception as e:
                return T("consolidation.now_fail", error=str(e))

        if action in ("daily", "zilnic"):
            hour = ac["hour"]
            if len(parts) > 1:
                try:
                    hour = int(parts[1])
                except ValueError:
                    return T("consolidation.invalid")
            if not 0 <= hour <= 23:
                return T("consolidation.invalid")
            ac["enabled"] = True
            ac["schedule"] = "daily"
            ac["hour"] = hour
            return _save_ac(ac)

        if action in ("weekly", "saptamanal", "săptămânal"):
            hour = ac["hour"]
            if len(parts) > 1:
                try:
                    hour = int(parts[1])
                except ValueError:
                    return T("consolidation.invalid")
            if not 0 <= hour <= 23:
                return T("consolidation.invalid")
            ac["enabled"] = True
            ac["schedule"] = "weekly"
            ac["hour"] = hour
            return _save_ac(ac)

        if action in ("every", "interval", "fiecare"):
            raw_h = parts[1] if len(parts) > 1 else ""
            raw_h = raw_h.rstrip("hH")
            try:
                hours = int(raw_h)
            except ValueError:
                return T("consolidation.invalid")
            if not 1 <= hours <= 168:
                return T("consolidation.invalid")
            ac["enabled"] = True
            ac["schedule"] = "interval"
            ac["interval_hours"] = hours
            return _save_ac(ac)

        return T("consolidation.invalid")

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
        sec = s["secondary"]
        lines = [T("stats.title_overview", days=30), ""]
        lines.append(f"• **{T('stats.totalRequests')}:** {s['total_requests']:,}")
        lines.append(f"• **{T('stats.totalTokens')}:** {tok['total']:,} ({T('stats.promptTokens')}: {tok['prompt']:,} / {T('stats.completionTokens')}: {tok['completion']:,})")
        lines.append(f"• **{T('stats.searchRequests')}:** {s['search_requests']:,}")
        lines.append(f"• **{T('stats.streamRequests')}:** {s['stream_requests']:,} / {s['non_stream_requests']:,}")
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


def _estimate_tokens(text) -> int:
    """Estimate token count using word-based heuristic."""
    return cc.estimate_tokens(text)


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
        content = m.get("content")
        role = m.get("role", "user")

        if not cc.message_has_payload(m) and role != "tool":
            continue

        if (
            cleaned
            and cleaned[-1].get("role") == role
            and role != "tool"
            # Merging away a tool call would leave its result orphaned.
            and not cleaned[-1].get("tool_calls")
            and not m.get("tool_calls")
            and isinstance(cleaned[-1].get("content"), str)
            and isinstance(content, str)
            and not cc.has_images(content)
        ):
            prev_content = cc.content_text(cleaned[-1].get("content"))
            next_content = cc.content_text(content)
            if next_content and prev_content:
                cleaned[-1]["content"] = prev_content + "\n" + next_content
            elif next_content:
                cleaned[-1]["content"] = next_content
            # Keep DeepSeek/Grok CoT when merging consecutive assistants
            prev_r = cleaned[-1].get("reasoning_content") or ""
            next_r = m.get("reasoning_content") or ""
            if next_r and next_r not in prev_r:
                cleaned[-1]["reasoning_content"] = (
                    f"{prev_r}\n{next_r}".strip() if prev_r else next_r
                )
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

    system_tokens = sum(_estimate_tokens(m.get("content")) for m in system_msgs)
    budget = max_tokens - system_tokens
    if budget <= 0:
        return system_msgs

    # First pass: total cost of all non-system messages
    total_others = sum(_estimate_tokens(m.get("content")) for m in other_msgs)
    if total_others <= budget:
        return system_msgs + other_msgs  # everything fits

    # Keep recent messages verbatim, compress older ones into a summary
    kept_recent = []
    used = 0
    for msg in reversed(other_msgs):
        cost = _estimate_tokens(msg.get("content"))
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
            content = cc.summary_snippet(m.get("content"))
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


def _context_budget(provider: dict) -> int:
    return pc.context_budget(provider)


def _trim_messages_kv_friendly(messages: list[dict], max_tokens: int) -> list[dict]:
    """Trim oldest conversation turns only — no summary injection (KV-cache friendly).

    Preserves message order (including volatile context prefixed on the last user
    turn) instead of hoisting every system message to the front.
    """
    if not messages:
        return messages

    def token_count(msgs: list[dict]) -> int:
        return sum(_estimate_tokens(m.get("content")) for m in msgs)

    if token_count(messages) <= max_tokens:
        return messages

    kept = list(messages)
    leading_system = 0
    while leading_system < len(kept) and kept[leading_system].get("role") == "system":
        leading_system += 1

    while token_count(kept) > max_tokens:
        drop_idx = None
        for i in range(leading_system, len(kept)):
            if kept[i].get("role") in ("user", "assistant", "tool"):
                drop_idx = i
                break
        if drop_idx is None:
            break
        kept.pop(drop_idx)

    return kept

# ══════════════════════════════════════════════════
# AI-driven search via function-calling (tool_calls)
# Like hass_memory/brain/toolbox.py — reliable, no marker parsing.
# ══════════════════════════════════════════════════

_MEDIA_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "media_list",
            "description": (
                "List files and folders in the Home Assistant /media and /share folders "
                "(photos, videos, documents). Call with no path to see the roots, then pass a path "
                "to open a folder. search= looks for a name inside that folder."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Folder under /media or /share"},
                    "search": {"type": "string", "description": "Match part of a file name"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_read",
            "description": (
                "Open one file from /media or /share. Documents (PDF, TXT, MD, CSV, JSON, YAML) come "
                "back as text; a photo is shown in the chat. Videos and audio return details only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File under /media or /share"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "media_delete",
            "description": (
                "Delete one file from /media or /share. Irreversible — confirm=true is required, "
                "and only when the user asked for the deletion."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File under /media or /share"},
                    "confirm": {"type": "boolean"},
                },
                "required": ["path", "confirm"],
            },
        },
    },
]


async def _run_media_tool(
    fn_name: str,
    args: dict,
    user_id: str,
    generated_attachments: list | None,
) -> str:
    from services import media_tools as mt

    path = str(args.get("path") or "").strip()
    log.info("AI requested media tool '%s': %s", fn_name, path or "(roots)")
    try:
        if fn_name == "media_list":
            return mt.list_media(path, search=str(args.get("search") or ""))
        if fn_name == "media_delete":
            return mt.delete_media(path, confirm=args.get("confirm") is True)

        info = mt.read_media(path)
        kind = info.get("kind")
        if kind == "document":
            return f"[{info['name']}]\n{info.get('text') or '(empty file)'}"
        if kind == "image":
            att = cm.save_uploaded_file(user_id, info["bytes"], filename=info["name"])
            if generated_attachments is not None:
                generated_attachments.append(att)
            return f"Showing {info['name']} in the chat."
        return (
            f"{info['name']} — {kind}, {info['size']} bytes. "
            "Binary file; it cannot be read as text."
        )
    except ValueError as exc:
        return f"Error: {exc}"
    except OSError as exc:
        return f"Error: {exc}"


_FRIGATE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "frigate_list_cameras",
            "description": (
                "List Frigate camera names. Use before asking about a specific camera "
                "when the name is unclear (front yard, driveway, etc.)."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "frigate_events",
            "description": (
                "Recent Frigate detections (person, car, animal, …) from the real NVR — "
                "not AI image generation. Default: text-only summary for the user "
                "(who/when/camera/still on camera). Pass camera= / label= to filter. "
                "Set include_snapshot=true only when the user explicitly asks to see/show "
                "a photo or snap — attaches one newest snapshot, not every event."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "camera": {
                        "type": "string",
                        "description": "Frigate camera name (e.g. front_door). Optional.",
                    },
                    "label": {
                        "type": "string",
                        "description": "Object label filter: person, car, dog, … Optional.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "How many events to list in text (default 8, max 25).",
                    },
                    "include_snapshot": {
                        "type": "boolean",
                        "description": (
                            "Default false. True only when the user wants a photo — "
                            "attaches one newest snapshot, not a gallery."
                        ),
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "frigate_snapshot",
            "description": (
                "Fetch a real Frigate camera/event snapshot into the chat (not Imagine). "
                "Prefer camera= for the latest frame, or event_id= from frigate_events "
                "when the user asks for the photo of a specific detection."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "camera": {"type": "string", "description": "Frigate camera name"},
                    "event_id": {"type": "string", "description": "Frigate event id"},
                },
            },
        },
    },
]


async def _run_frigate_tool(
    fn_name: str,
    args: dict,
    user_id: str,
    generated_attachments: list | None,
) -> str:
    from services import frigate_tools as ft

    log.info("AI requested Frigate tool '%s': %s", fn_name, args)
    try:
        if fn_name == "frigate_list_cameras":
            return await ft.list_cameras()

        if fn_name == "frigate_events":
            result = await ft.list_events(
                camera=str(args.get("camera") or ""),
                label=str(args.get("label") or ""),
                limit=args.get("limit") or 8,
                include_snapshot=bool(args.get("include_snapshot")),
            )
        elif fn_name == "frigate_snapshot":
            result = await ft.snapshot(
                camera=str(args.get("camera") or ""),
                event_id=str(args.get("event_id") or ""),
            )
        else:
            return f"Error: unknown Frigate tool {fn_name}"

        text = result.get("text") or "OK"
        images = list(result.get("images") or [])
        if result.get("image") and not images:
            images = [result["image"]]
        if images and generated_attachments is not None:
            for image in images:
                if not image or not image.get("bytes"):
                    continue
                att = cm.save_uploaded_file(
                    user_id,
                    image["bytes"],
                    filename=image.get("filename") or "frigate.jpg",
                )
                generated_attachments.append(att)
            if "Attached" not in text and "Showing" not in text:
                text = f"{text}\nShowing snapshot in the chat."
        return text
    except ValueError as exc:
        return f"Error: {exc}"
    except Exception as exc:
        log.error("Frigate tool %s failed: %s", fn_name, exc)
        return f"Error: Frigate request failed — {exc}"


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


async def _stream_with_keepalive_sse(gen, interval: float = _KEEPALIVE_INTERVAL, trace_id: str = ""):
    """Wrap an async generator with periodic SSE keepalive comments.

    Prevents client disconnect during long prompt processing by sending
    SSE comments (`: keepalive\\n\\n`) which are ignored by spec-compliant clients.
    Uses asyncio.shield to prevent cancelling the upstream read on timeout.
    """
    gen_iter = gen.__aiter__()
    next_task = None
    while True:
        if trace_id and _trace_cancelled(trace_id):
            raise TraceCancelled(trace_id)
        if next_task is None:
            next_task = asyncio.ensure_future(gen_iter.__anext__())
        try:
            chunk = await asyncio.wait_for(asyncio.shield(next_task), timeout=interval)
            next_task = None
            yield chunk
        except asyncio.TimeoutError:
            if trace_id and _trace_cancelled(trace_id):
                raise TraceCancelled(trace_id)
            # Upstream read still in progress — send keepalive without cancelling it
            yield ": keepalive\n\n"
        except StopAsyncIteration:
            break


def _validate_api_key(request: Request):
    """Validate API key, or allow trusted Web UI / HA Ingress sessions."""
    from core.auth import require_api_key_or_webui

    require_api_key_or_webui(request)


def _extract_user_id(request: Request, body: dict) -> str:
    """Identify the HA / Bridge user from the request.

    Priority:
    1. API key → username mapping (Assist / integration)
    2. HA Ingress headers (X-Remote-User-*) — auto-creates Settings user + API key
    3. body fields (not 'webui')
    4. config users.default_user
    """
    from core.identity import ensure_from_request

    cfg = load_config()
    users_cfg = cfg.get("users", {})
    api_key_map = users_cfg.get("api_keys", {})
    default_user = users_cfg.get("default_user", "").strip()

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token in api_key_map:
            return api_key_map[token]

    assist_key = request.headers.get("x-assist-key", "").strip()
    if assist_key and assist_key in api_key_map:
        return api_key_map[assist_key]

    profile = ensure_from_request(request)
    if profile:
        return profile["username"]

    for field in ("username", "user_name", "user_id", "user"):
        val = str(body.get(field, "") or "").strip()
        if val and val not in ("webui",):
            return val

    if default_user:
        return default_user

    return "default"


@router.get("/v1/chat/activity/{trace_id}")
async def chat_activity(trace_id: str, request: Request, after: int = -1):
    """Live agent steps for the Web UI (polling; Ingress cannot rely on SSE)."""
    _validate_api_key(request)
    _trace_gc()
    safe_id = _sanitize_trace_id(trace_id)
    bucket = _traces.get(safe_id) if safe_id else None
    return _activity_status_payload(bucket, after)


@router.get("/v1/chat/jobs/{trace_id}")
async def chat_job_status(trace_id: str, request: Request):
    """Background chat job status (same bucket as activity)."""
    _validate_api_key(request)
    _trace_gc()
    safe_id = _sanitize_trace_id(trace_id)
    bucket = _traces.get(safe_id) if safe_id else None
    payload = _activity_status_payload(bucket, -1)
    payload.pop("events", None)
    payload.pop("after", None)
    if not bucket:
        return JSONResponse(
            status_code=404,
            content={"error": {"message": "Job not found", "type": "not_found"}, **payload},
        )
    return payload


@router.post("/v1/chat/cancel/{trace_id}")
async def chat_cancel(trace_id: str, request: Request):
    """Cancel an in-flight chat/agent trace (Stop button on Web UI)."""
    _validate_api_key(request)
    _trace_gc()
    safe_id = _sanitize_trace_id(trace_id)
    if not safe_id:
        return JSONResponse(
            status_code=400,
            content={"error": {"message": "Invalid trace_id", "type": "invalid_request_error"}},
        )
    cancelled = _trace_cancel(safe_id)
    return {"ok": True, "cancelled": cancelled}


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model")
    stream = body.get("stream", False)
    background = bool(body.get("background"))
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")
    user_id = _extract_user_id(request, body)
    session_id = str(body.get("session_id") or "").strip() or None
    trace_id = _sanitize_trace_id(body.get("trace_id"))
    thinking_override = _parse_thinking_override(body.get("thinking"))
    cfg = load_config()
    search_enabled = cfg["searxng"].get("enabled", False)

    # Build effective tools list: client tools + search_web + skills + HA
    all_tools = list(tools or []) if tools else []
    if search_enabled:
        all_tools.append(_SEARCH_WEB_TOOL)
    all_tools.extend(_build_skill_tools())
    all_tools.extend(_MEDIA_TOOLS)
    from services import frigate_tools as ft

    if ft.is_enabled():
        all_tools.extend(_FRIGATE_TOOLS)
    all_tools.extend(mt.build_tools(cfg))
    all_tools.extend(bt.build_tools(cfg))
    all_tools.extend(ha_api.build_ha_tools(cfg))

    # The last user turn is read before routing: Auto mode classifies the turn
    # to decide which provider answers it.
    last_user_message: dict | None = None
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_message = msg
            last_user_msg = cc.content_text(msg.get("content"))
            break

    request_has_images = cc.messages_have_images(messages)
    route = provider_router.resolve(
        cfg,
        active=get_active_provider(),
        session_id=session_id or "",
        user_text=last_user_msg,
        has_images=request_has_images,
        tools_active=bool(all_tools),
        prompt_tokens=sum(_estimate_tokens(m.get("content")) for m in messages),
    )
    active = route["provider"]
    if route["auto"]:
        log.info(
            "[%s] Auto route → %s / %s (class=%s, %s)",
            user_id, active.get("name", "?"), route.get("model") or "?",
            route["klass"], route["reason"],
        )

    image_gen_provider = providers.resolve_image_generation_provider(active)
    if image_gen_provider and pc.supports_image_generation(image_gen_provider) and not request_has_images:
        all_tools.append(pc.build_image_generation_tool(image_gen_provider))

    route_klass = route.get("klass") or tp.route_class(
        last_user_msg,
        has_images=request_has_images,
        tools_active=bool(all_tools),
    )
    effective_tools, compact_tools = tp.filter_chat_tools(
        all_tools,
        provider=active,
        cfg=cfg,
        user_text=last_user_msg,
        route_klass=route_klass,
        search_enabled=search_enabled,
    )
    effective_tools = effective_tools if effective_tools else None
    if compact_tools and effective_tools:
        log.debug(
            "[%s] Compact tools: %s → %s (class=%s)",
            user_id, len(all_tools), len(effective_tools), route_klass,
        )

    # Authenticate when an API key is configured
    _validate_api_key(request)

    if background and session_id:
        busy_tid = _session_job_running(session_id)
        if busy_tid:
            return JSONResponse(
                status_code=409,
                content={
                    "error": {
                        "message": "A reply is already generating for this chat. Wait or press Stop.",
                        "type": "conflict",
                        "trace_id": busy_tid,
                    },
                },
            )

    # ── Message size validation (#16) ──
    total_size = sum(cc.content_size(m.get("content")) for m in messages)
    if total_size > 6_000_000:
        return JSONResponse(
            status_code=413,
            content={"error": {"message": "Message content too large (max 6MB)", "type": "invalid_request_error"}},
        )
    for msg in messages:
        if cc.content_size(msg.get("content")) > 2_000_000:
            return JSONResponse(
                status_code=413,
                content={"error": {"message": "Single message too large (max 2MB)", "type": "invalid_request_error"}},
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
    log.info(
        f"[{user_id}] Request: \"{last_user_msg[:80]}\" "
        f"(provider={active.get('name','?')}, stream={stream}, background={background})"
    )
    augmented: list[dict] = []

    # 1) System prompt: global base + optional per-provider personality overlay
    secondary = providers.get_secondary_provider(active)
    global_prompt, provider_personality = resolve_provider_personality(active, cfg)

    # 2) Memory + history retrieval (parallel)
    history_limit = tp.effective_history_limit(cfg, active)
    memories, history = await asyncio.gather(
        retrieve_relevant_memories(user_id, last_user_msg),
        asyncio.to_thread(get_conversation_history, user_id, history_limit, session_id),
    )

    mem_ctx = build_memory_context(memories, user_id=user_id, message=last_user_msg)

    from core.identity import user_context_for_prompt

    user_ctx = user_context_for_prompt(user_id, request)

    # 3) System prompt: stable prefix (KV-cache friendly); memory goes on last user turn
    bridge_hint = bt.system_hint(cfg)
    memory_hint = mt.system_hint(cfg)
    stable_parts = build_stable_system_parts(
        global_prompt=global_prompt,
        provider_personality=provider_personality,
        bridge_hint=bridge_hint or "",
        memory_hint=memory_hint or "",
        agentic=_agentic_instruction(),
    )
    stable_extras = []
    if user_ctx:
        stable_extras.append(user_ctx)
    if search_enabled:
        stable_extras.append(_build_search_instruction(cfg))
    ha_tool_names_for_hint = [
        str(t.get("function", {}).get("name") or "")
        for t in (effective_tools or [])
        if str(t.get("function", {}).get("name") or "").startswith("ha_")
    ]
    ha_hint = ha_api.ha_system_hint(
        cfg,
        tool_names=ha_tool_names_for_hint or None,
        compact=compact_tools,
    )
    if ha_hint:
        stable_extras.append(ha_hint)
    from services import frigate_tools as ft

    frigate_hint = ft.system_hint()
    if frigate_hint and any(
        str(t.get("function", {}).get("name") or "") in _FRIGATE_TOOL_NAMES
        for t in (effective_tools or [])
    ):
        stable_extras.append(frigate_hint)

    if stable_parts or stable_extras:
        augmented.append({"role": "system", "content": "\n\n".join(stable_parts + stable_extras)})

    # 4) Conversation history — only add DB history if incoming messages
    #    don't already contain a conversation (HA sends full history)
    incoming_roles = {m.get("role") for m in messages}
    has_incoming_history = "assistant" in incoming_roles and "user" in incoming_roles
    if history and not has_incoming_history:
        # Only the most recent turns replay their tool calls; older ones keep just
        # the text so a long conversation does not carry every tool result along.
        replay_from = len(history) - tp.tool_replay_turns(
            cfg, active,
        )
        for index, row in enumerate(history):
            augmented.extend(
                cc.row_to_messages(
                    row, user_id=user_id, replay_tools=index >= replay_from,
                )
            )

    # 5) Current messages — clients replay the transcript without CoT, so restore
    #    it from the stored history (DeepSeek requires it back alongside tools).
    augmented.extend(cc.backfill_reasoning(messages, history) if has_incoming_history else messages)

    if mem_ctx:
        _inject_late_user_context(augmented, mem_ctx)

    user_attachments: list[dict] = []
    if last_user_message is not None:
        user_attachments = cm.persist_attachments_from_content(user_id, last_user_message.get("content"))

    # Save only the latest user turn. Clients (Web UI / Assist) may send a
    # full transcript; re-inserting every message would duplicate the thread.
    if last_user_message is not None:
        stored_text = last_user_msg or (
            "(image)" if user_attachments and any(
                (a.get("kind") or "image") != "document" for a in user_attachments
            ) else "(document)" if user_attachments else ""
        )
        if stored_text:
            stored_text = cm.strip_document_blocks(stored_text)
        user_meta = {"attachments": user_attachments} if user_attachments else None
        add_conversation_message(user_id, "user", stored_text, session_id=session_id, meta=user_meta)

    # ── Strip any <<SEARCH markers that leaked into stored assistant messages ──
    for m in augmented:
        c = m.get("content") or ""
        if c and m.get("role") == "assistant" and "<<SEARCH" in c:
            cleaned = _strip_search_markers(c).strip()
            m["content"] = cleaned if cleaned else "(search attempted)"

    # ── Sanitize role order + trim to fit context window ──
    augmented = _sanitize_message_roles(augmented)
    max_ctx = _context_budget(active)
    if pc.supports_kv_cache(active):
        augmented = _trim_messages_kv_friendly(augmented, max_ctx)
    else:
        augmented = _trim_messages(augmented, max_ctx)
    # Trimming cuts from the front and can separate a call from its result.
    augmented = cc.drop_orphan_tool_messages(augmented)

    # Frigate / Imagine snaps live on assistant turns for the UI. Never replay them
    # as assistant image_url to the LLM (DeepSeek Vision HTTP 400, etc.).
    augmented = cc.strip_non_user_images(augmented)

    request_has_images = cc.messages_have_images(augmented)
    image_provider: dict | None = None
    chat_provider = active
    if request_has_images and not providers.provider_supports_vision(active):
        image_provider = providers.resolve_image_provider(active, secondary)
        if not image_provider:
            _trace_done(trace_id)
            return _vision_required_error(cfg)
        chat_provider = image_provider
        log.info(
            "[%s] Routing image request to %s (primary lacks vision)",
            user_id,
            chat_provider.get("name", "?"),
        )

    thinking_cfg = pc.resolve_thinking(
        chat_provider,
        override=thinking_override,
        user_text=last_user_msg,
        tools_active=bool(effective_tools),
    )
    if thinking_cfg:
        log.info(
            "[%s] Provider thinking mode=%s enabled=%s effort=%s auto=%s",
            user_id,
            thinking_cfg.get("mode"),
            thinking_cfg.get("enabled"),
            thinking_cfg.get("effort"),
            thinking_cfg.get("auto_reason") or "-",
        )

    # Log prompt size for optimization tracking
    _prompt_tokens = sum(_estimate_tokens(m.get("content")) for m in augmented)
    log.info(f"Prompt: {len(augmented)} msgs, ~{_prompt_tokens} tokens (budget {max_ctx})")

    # ── First LLM call ──
    _req_start = time.time()
    _search_used = False
    _secondary_used_for_recall = False  # tracks if secondary/vision handled a re-call (search/skill)
    _image_provider_used = image_provider is not None
    _trace_start(
        trace_id,
        session_id=session_id,
        user_id=user_id,
        model=chat_provider.get("model", ""),
        provider_name=chat_provider.get("name", ""),
        route={
            "role": route.get("role") or "",
            "reason": route.get("reason") or "",
            "klass": route.get("klass") or "",
            "auto": bool(route.get("auto")),
        },
    )
    activity_events: list[dict] = []

    async def on_activity(event: dict):
        activity_events.append(_trace_push(trace_id, event))

    # Tell the Web UI which model Auto actually picked (not the Settings default).
    # Pushed to the live trace only — not stored as a thinking/tool step.
    if route.get("auto") or chat_provider.get("model"):
        _trace_push(trace_id, {
            "id": "route",
            "name": "route",
            "detail": chat_provider.get("model") or "",
            "status": "done",
            "provider": chat_provider.get("name") or "",
            "role": route.get("role") or "",
            "reason": route.get("reason") or "",
        })

    async def emit_think(
        think_id: str,
        status: str,
        started: float | None = None,
        detail: str = "",
    ):
        payload = {"id": think_id, "name": "think", "detail": detail, "status": status}
        if status != "running" and started is not None:
            payload["ms"] = int((time.time() - started) * 1000)
        await on_activity(payload)

    if not stream and not background:
        think_t0 = time.time()
        await emit_think("think-0", "running")
        tried: list[str] = []
        while True:
            try:
                await _check_trace(trace_id)
                result = await providers.chat_completion(
                    augmented,
                    model=model,
                    tools=effective_tools,
                    tool_choice=tool_choice,
                    provider=chat_provider,
                    thinking=pc.thinking_for_provider(thinking_cfg, chat_provider),
                    cache_conv_id=session_id,
                )
                break
            except TraceCancelled:
                log.info("[%s] Chat cancelled trace=%s (before first call)", user_id, trace_id)
                _trace_done(trace_id)
                return JSONResponse(content=_cancelled_openai_response(model, activity_events))
            except Exception as e:
                log.error(f"Provider [{chat_provider.get('name', '?')}] request failed: {e}")
                provider_router.record_failure(chat_provider.get("id", ""))
                tried.append(chat_provider.get("id", ""))
                # Auto mode moves to the next healthy candidate instead of
                # handing the user an error from a provider they never picked.
                alternate = provider_router.failover(
                    cfg,
                    tried=tried,
                    session_id=session_id or "",
                    user_text=last_user_msg,
                    has_images=request_has_images,
                    tools_active=bool(effective_tools),
                )
                if alternate is None:
                    _trace_done(trace_id)
                    return _provider_upstream_error(e)
                log.warning(
                    "[%s] Falling back to %s after %s failed",
                    user_id, alternate.get("name", "?"), chat_provider.get("name", "?"),
                )
                chat_provider = alternate
                route = {**route, "reason": "failover"}
                thinking_cfg = pc.resolve_thinking(
                    chat_provider,
                    override=thinking_override,
                    user_text=last_user_msg,
                    tools_active=bool(effective_tools),
                )
        provider_router.record_success(chat_provider.get("id", ""))
        first_msg = result.get("choices", [{}])[0].get("message", {})
        pc.log_provider_usage(chat_provider, result.get("usage"), user_id=user_id)
        await emit_think("think-0", "done", think_t0, _message_reasoning(first_msg))

        # ── Handle tool_calls (search_web, run_skill, HA, or forward to client) ──
        # Agentic loop: keep tools available and continue until the model
        # stops calling them (or we hit the round cap).
        fingerprints: list[str] = []
        generated_attachments: list[dict] = []
        max_rounds = _agent_max_rounds(cfg)
        round_limit = max_rounds
        _round = 0
        tool_trace_start = len(augmented)
        last_call_provider = chat_provider
        try:
            while _round < round_limit:
                await _check_trace(trace_id)
                msg = result.get("choices", [{}])[0].get("message", {})
                tool_calls = msg.get("tool_calls") or []
                if not tool_calls:
                    break

                internal_calls = [
                    tc for tc in tool_calls
                    if _is_internal_tool((tc.get("function") or {}).get("name") or "", cfg)
                ]
                if not internal_calls:
                    msg["content"] = ""
                    _trace_done(trace_id)
                    result["hassai_activity"] = activity_events
                    return JSONResponse(content=result)

                round_limit = _maybe_extend_tool_rounds(internal_calls, _round, round_limit)
                log.info("Agent round %s/%s — %s tool(s)", _round + 1, round_limit, len(internal_calls))
                say = _say_event(_round, msg.get("content") or "")
                if say:
                    await on_activity(say)
                augmented.append(pc.assistant_turn(last_call_provider, msg))
                if await _append_internal_tool_results(
                    augmented,
                    internal_calls,
                    search_enabled=search_enabled,
                    fingerprints=fingerprints,
                    on_event=on_activity,
                    trace_id=trace_id,
                    provider=active,
                    image_gen_provider=image_gen_provider,
                    user_id=user_id,
                    session_id=session_id,
                    generated_attachments=generated_attachments,
                    cfg=cfg,
                ):
                    _search_used = True

                # Imagine can take 30–90s; a second LLM round often trips HA Ingress 504.
                # When this round was only generate_image and we have images, finish now.
                if generated_attachments and _only_image_gen_tools(internal_calls):
                    result = _finalize_image_only_result(
                        model=model,
                        session_id=session_id,
                        generated_attachments=generated_attachments,
                        activity_events=activity_events,
                    )
                    log.info(
                        "Finalizing after image generation without LLM recall (%s image(s))",
                        len(generated_attachments),
                    )
                    break

                re_provider = _recall_provider(
                    internal_calls, active, secondary,
                    image_provider=image_provider,
                    image_gen_provider=image_gen_provider,
                )
                if secondary and re_provider is secondary:
                    _secondary_used_for_recall = True
                elif image_provider and re_provider is image_provider:
                    _secondary_used_for_recall = True
                last = _round >= round_limit - 1
                # Last round has no tools — always speak with primary (not secondary).
                if last and secondary and (
                    re_provider is secondary
                    or re_provider.get("id") == secondary.get("id")
                ):
                    re_provider = active
                think_id = f"think-{_round + 1}"
                think_t0 = time.time()
                await emit_think(think_id, "running")
                try:
                    await _check_trace(trace_id)
                    recall_msgs = (
                        _messages_for_secondary_tools(augmented)
                        if secondary and (
                            re_provider is secondary
                            or re_provider.get("id") == secondary.get("id")
                        )
                        else augmented
                    )
                    result = await providers.chat_completion(
                        recall_msgs,
                        model=model,
                        tools=None if last else effective_tools,
                        tool_choice=tool_choice,
                        provider=re_provider,
                        thinking=pc.thinking_for_provider(thinking_cfg, re_provider),
                        cache_conv_id=session_id,
                    )
                except TraceCancelled:
                    raise
                except Exception as e:
                    log.error("Provider re-call failed (round %s): %s", _round + 1, e)
                    _trace_done(trace_id)
                    return _provider_upstream_error(e)
                last_call_provider = re_provider
                round_msg = result.get("choices", [{}])[0].get("message", {})
                pc.log_provider_usage(re_provider, result.get("usage"), user_id=user_id)
                await emit_think(think_id, "done", think_t0, _message_reasoning(round_msg))
                # Secondary returned text without tools → discard and finalize on primary.
                if _should_finalize_on_primary(
                    active=active,
                    secondary=secondary,
                    call_provider=re_provider,
                    tool_calls=round_msg.get("tool_calls"),
                ):
                    think_id_f = f"think-{_round + 1}-final"
                    think_t0_f = time.time()
                    await emit_think(think_id_f, "running")
                    try:
                        await _check_trace(trace_id)
                        result = await providers.chat_completion(
                            augmented,
                            model=model,
                            tools=None,
                            tool_choice=tool_choice,
                            provider=active,
                            thinking=pc.thinking_for_provider(thinking_cfg, active),
                            cache_conv_id=session_id,
                        )
                    except TraceCancelled:
                        raise
                    except Exception as e:
                        log.error("Primary finalize failed (round %s): %s", _round + 1, e)
                        _trace_done(trace_id)
                        return _provider_upstream_error(e)
                    last_call_provider = active
                    round_msg = result.get("choices", [{}])[0].get("message", {})
                    pc.log_provider_usage(active, result.get("usage"), user_id=user_id)
                    await emit_think(think_id_f, "done", think_t0_f, _message_reasoning(round_msg))
                _round += 1
        except TraceCancelled:
            log.info("[%s] Chat cancelled trace=%s (agent loop)", user_id, trace_id)
            _trace_done(trace_id)
            return JSONResponse(content=_cancelled_openai_response(model, activity_events))

        # If final result still has non-internal tool_calls, forward to client
        final_msg = result.get("choices", [{}])[0].get("message", {})
        pending_internal = [
            (tc.get("function") or {}).get("name")
            for tc in (final_msg.get("tool_calls") or [])
            if _is_internal_tool((tc.get("function") or {}).get("name") or "", cfg)
        ]
        if final_msg.get("tool_calls"):
            remaining = [
                tc for tc in final_msg["tool_calls"]
                if not _is_internal_tool(tc.get("function", {}).get("name") or "", cfg)
            ]
            if remaining:
                final_msg["tool_calls"] = remaining
                final_msg["content"] = ""
                _trace_done(trace_id)
                result["hassai_activity"] = activity_events
                return JSONResponse(content=result)
            else:
                del final_msg["tool_calls"]

        assistant_content = final_msg.get("content", "") or ""
        image_markdown = _markdown_for_generated_attachments(
            generated_attachments, session_id, assistant_content,
        )
        if image_markdown and image_markdown not in assistant_content:
            assistant_content = (
                f"{assistant_content}\n\n{image_markdown}".strip()
                if assistant_content
                else image_markdown
            )
            result["choices"][0]["message"]["content"] = assistant_content
        if pending_internal:
            notice = _agent_incomplete_notice(pending_internal)
            assistant_content = (assistant_content + notice).strip()
            result["choices"][0]["message"]["content"] = assistant_content

        # Strip any legacy <<SEARCH>> markers from content
        if assistant_content and _SEARCH_MARKER_STRIP.search(assistant_content):
            assistant_content = _strip_search_markers(assistant_content)
            result["choices"][0]["message"]["content"] = assistant_content

        cleaned_notes = cc.strip_photo_notes(assistant_content)
        if cleaned_notes != assistant_content:
            assistant_content = cleaned_notes
            result["choices"][0]["message"]["content"] = assistant_content

        # Save & extract memories
        turn_tools = _tool_trace(augmented, tool_trace_start)
        if assistant_content or generated_attachments or turn_tools:
            add_conversation_message(
                user_id, "assistant", assistant_content,
                session_id=session_id,
                meta=_activity_meta(
                    trace_id,
                    activity_events,
                    generated_attachments,
                    reasoning_content=_message_reasoning_full(final_msg),
                    tool_calls=turn_tools,
                    model=chat_provider.get("model", ""),
                    provider_name=chat_provider.get("name", ""),
                    route=route,
                ),
            )
            if assistant_content:
                all_msgs = messages + [{"role": "assistant", "content": assistant_content}]
                asyncio.create_task(_safe_extract(user_id, all_msgs, provider=active, active=active))

        # Track usage statistics
        _elapsed_ms = int((time.time() - _req_start) * 1000)
        log.info(f"[{user_id}] Response: {len(assistant_content or '')} chars, {_elapsed_ms}ms, search={_search_used}")
        try:
            usage = result.get("usage", {})
            # chat_provider, not active: vision rerouting and Auto-mode failover
            # can move the call, and billing must follow the provider that ran.
            stat_prov = (
                image_provider
                if _image_provider_used
                else (secondary if _secondary_used_for_recall and secondary else chat_provider)
            )
            cache_hit, cache_miss = pc.cache_tokens_from_usage(stat_prov, usage)
            add_usage_stat(
                user_id=user_id, provider_id=stat_prov.get("id", ""),
                provider_name=stat_prov.get("name", ""), provider_type=stat_prov.get("type", ""),
                model=result.get("model", model or stat_prov.get("model", "")),
                tokens_prompt=usage.get("prompt_tokens", 0),
                tokens_completion=usage.get("completion_tokens", 0),
                tokens_total=usage.get("total_tokens", 0),
                response_time_ms=int((time.time() - _req_start) * 1000),
                stream=False, search_used=_search_used,
                                secondary_used=_image_provider_used or _secondary_used_for_recall,
                cache_hit_tokens=cache_hit,
                cache_miss_tokens=cache_miss,
                cost_usd=pricing.estimate_cost(
                    stat_prov,
                    {**usage, "cache_hit_tokens": cache_hit, "cache_miss_tokens": cache_miss},
                    cfg,
                ),
                route_reason=route["reason"],
            )
        except Exception:
            pass

        _trace_done(trace_id)
        result["hassai_activity"] = activity_events
        result["hassai_route"] = {
            "provider": chat_provider.get("name", ""),
            "model": chat_provider.get("model", ""),
            "reason": route["reason"],
            "klass": route["klass"],
            "auto": route["auto"],
        }
        return JSONResponse(content=result)

    # ── Streaming path ──
    # Tool-call chunks are accumulated silently; content/reasoning pass through.
    # After tools run, we start another stream — same agentic loop as JSON.

    async def stream_wrapper():
        nonlocal augmented
        full_response = ""
        fingerprints: list[str] = []
        generated_attachments: list[dict] = []
        search_used = False
        secondary_used = _image_provider_used
        rounds_left = _agent_max_rounds(cfg)
        sse_buf: list[str] = []
        round_i = 0
        tool_trace_start = len(augmented)
        stream_call_provider = chat_provider
        last_content_push = 0.0
        stream_usage: dict = {}
        last_think_reasoning = ""

        async def on_stream_activity(event: dict):
            pushed = _trace_push(trace_id, event)
            sse_buf.append(_activity_sse(pushed))

        async def flush_activity():
            while sse_buf:
                yield sse_buf.pop(0)

        async def push_assistant_preview(force: bool = False):
            """Ingress often buffers SSE; activity poll carries live token text."""
            nonlocal last_content_push
            if not full_response and not force:
                return
            now = time.time()
            if not force and (now - last_content_push) < 0.05:
                return
            last_content_push = now
            await on_stream_activity({
                "id": "assistant-out",
                "name": "assistant",
                # The Web UI renders this, not the raw SSE chunks, so the photo
                # marker has to be filtered here to stay off the screen.
                "detail": cc.strip_photo_notes(full_response),
                "status": "running",
            })

        current_gen = providers.chat_completion_stream(
            augmented,
            model=model,
            tools=effective_tools,
            tool_choice=tool_choice,
            provider=chat_provider,
            thinking=pc.thinking_for_provider(thinking_cfg, chat_provider),
            cache_conv_id=session_id,
        )

        try:
            while True:
                await _check_trace(trace_id)
                tc_accum: dict[int, dict] = {}
                tc_chunks: list[str] = []
                has_tool_calls = False
                pending_gemini_extra: dict | None = None
                # Text of this round only. If the round turns out to call tools,
                # this was narration and gets pulled back out of the reply.
                round_text = ""
                round_text_started = 0.0
                hold_secondary_voice = bool(
                    secondary
                    and stream_call_provider
                    and (
                        stream_call_provider is secondary
                        or stream_call_provider.get("id") == secondary.get("id")
                    )
                )
                think_id = f"think-{round_i}"
                think_t0 = time.time()
                think_open = True
                think_reasoning = ""
                last_reasoning_push = 0.0
                await on_stream_activity({"id": think_id, "name": "think", "detail": "", "status": "running"})
                async for part in flush_activity():
                    yield part

                async for chunk in _stream_with_keepalive_sse(current_gen, trace_id=trace_id):
                    if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                        try:
                            data = json.loads(chunk[6:])
                            if isinstance(data.get("usage"), dict):
                                stream_usage = data["usage"]
                            delta = data.get("choices", [{}])[0].get("delta", {})
                        except (json.JSONDecodeError, IndexError, KeyError):
                            yield chunk
                            continue

                        content = delta.get("content") or ""
                        reasoning = delta.get("reasoning_content") or delta.get("reasoning")
                        tool_calls_delta = delta.get("tool_calls")
                        finish_reason = data.get("choices", [{}])[0].get("finish_reason")
                        # Gemini may put thought_signature on delta itself (before tool_calls).
                        delta_extra = delta.get("extra_content") if isinstance(delta.get("extra_content"), dict) else None
                        if delta_extra and gm.is_gemini_provider(stream_call_provider):
                            pending_gemini_extra = delta_extra

                        if tool_calls_delta:
                            has_tool_calls = True
                            tc_chunks.append(chunk)
                            for i, tc in enumerate(tool_calls_delta):
                                if gm.is_gemini_provider(stream_call_provider):
                                    idx = gm.allocate_stream_tool_index(
                                        tc, tc_accum, fallback_i=i if not tc_accum else max(tc_accum.keys(), default=-1) + 1,
                                    )
                                    if idx not in tc_accum:
                                        tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                                    gm.merge_tool_call_delta(tc_accum[idx], tc)
                                    if pending_gemini_extra:
                                        gm.attach_message_extra_content(tc_accum[idx], pending_gemini_extra)
                                        pending_gemini_extra = None
                                else:
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

                        if has_tool_calls and finish_reason:
                            # Some Gemini chunks put complete tool_calls on message, not delta.
                            msg_tcs = (data.get("choices", [{}])[0].get("message") or {}).get("tool_calls")
                            if msg_tcs and gm.is_gemini_provider(stream_call_provider):
                                for i, tc in enumerate(msg_tcs):
                                    idx = gm.allocate_stream_tool_index(tc, tc_accum, fallback_i=i)
                                    if idx not in tc_accum:
                                        tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                                    gm.merge_tool_call_delta(tc_accum[idx], tc)
                            continue

                        if reasoning:
                            think_reasoning += reasoning
                            last_think_reasoning = think_reasoning
                            now = time.time()
                            if think_open and (
                                now - last_reasoning_push >= 0.35
                                or len(think_reasoning) <= 120
                            ):
                                last_reasoning_push = now
                                await on_stream_activity({
                                    "id": think_id,
                                    "name": "think",
                                    "detail": _clip_reasoning(think_reasoning),
                                    "status": "running",
                                })
                                async for part in flush_activity():
                                    yield part
                            yield chunk
                            continue

                        if content:
                            if think_open:
                                think_open = False
                                if think_reasoning:
                                    last_think_reasoning = think_reasoning
                                await on_stream_activity({
                                    "id": think_id,
                                    "name": "think",
                                    "detail": _clip_reasoning(think_reasoning),
                                    "status": "done",
                                    "ms": int((time.time() - think_t0) * 1000),
                                })
                                async for part in flush_activity():
                                    yield part
                            if not round_text:
                                round_text_started = time.time()
                            round_text += content
                            # Secondary tool rounds: never stream voice to the user.
                            if hold_secondary_voice:
                                continue
                            full_response += content
                            # Hold the first moments back: narration is short and
                            # the tool call lands right after it, so waiting here
                            # keeps it from flashing in the chat before we can
                            # tell it apart from a real answer.
                            if time.time() - round_text_started >= 0.4:
                                await push_assistant_preview()
                                async for part in flush_activity():
                                    yield part
                        yield chunk

                    elif chunk.strip() == "data: [DONE]":
                        break
                    else:
                        yield chunk

                if think_open:
                    think_open = False
                    if think_reasoning:
                        last_think_reasoning = think_reasoning
                    await on_stream_activity({
                        "id": think_id,
                        "name": "think",
                        "detail": _clip_reasoning(think_reasoning),
                        "status": "done",
                        "ms": int((time.time() - think_t0) * 1000),
                    })
                    async for part in flush_activity():
                        yield part

                if has_tool_calls and tc_accum and round_text:
                    # Narration, not the answer — move it to the step timeline.
                    if not hold_secondary_voice:
                        full_response = full_response[: len(full_response) - len(round_text)]
                    say = _say_event(round_i, round_text)
                    if say:
                        await on_stream_activity(say)
                    round_text = ""

                await push_assistant_preview(force=True)
                async for part in flush_activity():
                    yield part

                if not (has_tool_calls and tc_accum):
                    if _should_finalize_on_primary(
                        active=active,
                        secondary=secondary,
                        call_provider=stream_call_provider,
                        tool_calls=None,
                    ):
                        # Discard any secondary prose; primary speaks to the user.
                        round_text = ""
                        stream_call_provider = active
                        round_i += 1
                        current_gen = providers.chat_completion_stream(
                            augmented,
                            model=model,
                            tools=None,
                            tool_choice=tool_choice,
                            provider=active,
                            thinking=pc.thinking_for_provider(thinking_cfg, active),
                            cache_conv_id=session_id,
                        )
                        continue
                    yield "data: [DONE]\n\n"
                    break

                if rounds_left <= 0:
                    pending = [
                        td["name"] for td in tc_accum.values()
                        if _is_internal_tool(td.get("name") or "", cfg)
                    ]
                    if pending:
                        notice = _agent_incomplete_notice(pending)
                        full_response += notice
                        notice_payload = json.dumps({
                            "id": "hassai-incomplete",
                            "object": "chat.completion.chunk",
                            "choices": [{
                                "index": 0,
                                "delta": {"role": "assistant", "content": notice},
                                "finish_reason": None,
                            }],
                        })
                        yield f"data: {notice_payload}\n\n"
                    yield "data: [DONE]\n\n"
                    break

                if gm.is_gemini_provider(stream_call_provider):
                    internal_tcs = [
                        gm.build_tool_call(td, fallback_idx=idx)
                        for idx, td in sorted(tc_accum.items())
                        if _is_internal_tool(td["name"], cfg)
                    ]
                else:
                    internal_tcs = [
                        {
                            "id": td["id"] or f"call_{idx}",
                            "type": "function",
                            "function": {"name": td["name"], "arguments": td["arguments"]},
                        }
                        for idx, td in sorted(tc_accum.items())
                        if _is_internal_tool(td["name"], cfg)
                    ]
                if not internal_tcs:
                    for tc_chunk in tc_chunks:
                        yield tc_chunk
                    yield "data: [DONE]\n\n"
                    break

                log.info("Agent stream round — %s tool(s), %s left", len(internal_tcs), rounds_left)
                assistant_turn = {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": internal_tcs,
                }
                # DeepSeek/Grok thinking + tools: reasoning_content must always be present
                if pc.needs_reasoning_in_tool_loop(stream_call_provider):
                    assistant_turn["reasoning_content"] = think_reasoning or ""
                augmented.append(pc.assistant_turn(stream_call_provider, assistant_turn))
                prev_generated = len(generated_attachments)
                if await _append_internal_tool_results(
                    augmented,
                    internal_tcs,
                    search_enabled=search_enabled,
                    fingerprints=fingerprints,
                    on_event=on_stream_activity,
                    trace_id=trace_id,
                    provider=active,
                    image_gen_provider=image_gen_provider,
                    user_id=user_id,
                    session_id=session_id,
                    generated_attachments=generated_attachments,
                    cfg=cfg,
                ):
                    search_used = True
                new_generated = generated_attachments[prev_generated:]
                if new_generated:
                    image_md = _markdown_for_generated_attachments(new_generated, session_id, full_response)
                    if image_md:
                        full_response += (("\n\n" if full_response else "") + image_md)
                        yield _sse_content_delta(image_md)
                async for part in flush_activity():
                    yield part

                # Same Ingress-safe shortcut as non-stream: don't start another LLM round
                if generated_attachments and _only_image_gen_tools(internal_tcs):
                    log.info(
                        "Stream finalize after image generation without LLM recall (%s image(s))",
                        len(generated_attachments),
                    )
                    yield "data: [DONE]\n\n"
                    break

                await _check_trace(trace_id)
                re_provider = _recall_provider(
                    internal_tcs, active, secondary,
                    image_provider=image_provider,
                    image_gen_provider=image_gen_provider,
                )
                if secondary and re_provider is secondary:
                    secondary_used = True
                elif image_provider and re_provider is image_provider:
                    secondary_used = True
                if any(name in lt.HA_MUTATING_TOOLS for name in _tool_names(internal_tcs)) and rounds_left <= 1:
                    rounds_left += 1
                rounds_left -= 1
                round_i += 1
                # Last round has no tools — always speak with primary (not secondary).
                if rounds_left <= 0 and secondary and (
                    re_provider is secondary
                    or re_provider.get("id") == secondary.get("id")
                ):
                    re_provider = active
                stream_call_provider = re_provider
                recall_msgs = (
                    _messages_for_secondary_tools(augmented)
                    if secondary and (
                        re_provider is secondary
                        or re_provider.get("id") == secondary.get("id")
                    )
                    else augmented
                )
                current_gen = providers.chat_completion_stream(
                    recall_msgs,
                    model=model,
                    tools=None if rounds_left <= 0 else effective_tools,
                    tool_choice=tool_choice,
                    provider=re_provider,
                    thinking=pc.thinking_for_provider(thinking_cfg, re_provider),
                    cache_conv_id=session_id,
                )

            turn_tools = _tool_trace(augmented, tool_trace_start)
            if full_response or generated_attachments or turn_tools:
                clean_response = _strip_search_markers(full_response) if "<<SEARCH" in full_response else full_response
                clean_response = cc.strip_photo_notes(clean_response)
                add_conversation_message(
                    user_id, "assistant", clean_response,
                    session_id=session_id,
                    meta=_activity_meta(
                        trace_id,
                        attachments=generated_attachments,
                        reasoning_content=_store_reasoning(last_think_reasoning),
                        tool_calls=turn_tools,
                        model=chat_provider.get("model", ""),
                        provider_name=chat_provider.get("name", ""),
                        route=route,
                    ),
                )
                if clean_response:
                    all_msgs = messages + [{"role": "assistant", "content": clean_response}]
                    asyncio.create_task(_safe_extract(user_id, all_msgs, provider=active, active=active))

            _stream_elapsed = int((time.time() - _req_start) * 1000)
            log.info(f"[{user_id}] Stream response: {len(full_response)} chars, {_stream_elapsed}ms, search={search_used}")
            provider_router.record_success(chat_provider.get("id", ""))
            try:
                stat_prov = (
                    image_provider
                    if _image_provider_used
                    else (secondary if secondary_used and secondary else chat_provider)
                )
                if stream_usage:
                    pc.log_provider_usage(stat_prov, stream_usage, user_id=user_id)
                    cache_hit, cache_miss = pc.cache_tokens_from_usage(stat_prov, stream_usage)
                    add_usage_stat(
                        user_id=user_id, provider_id=stat_prov.get("id", ""),
                        provider_name=stat_prov.get("name", ""), provider_type=stat_prov.get("type", ""),
                        model=model or stream_usage.get("model") or stat_prov.get("model", ""),
                        tokens_prompt=int(stream_usage.get("prompt_tokens") or _prompt_tokens),
                        tokens_completion=int(
                            stream_usage.get("completion_tokens")
                            or _estimate_tokens(full_response)
                        ),
                        tokens_total=int(
                            stream_usage.get("total_tokens")
                            or (
                                int(stream_usage.get("prompt_tokens") or _prompt_tokens)
                                + int(
                                    stream_usage.get("completion_tokens")
                                    or _estimate_tokens(full_response)
                                )
                            )
                        ),
                        response_time_ms=int((time.time() - _req_start) * 1000),
                        stream=True, search_used=search_used,
                                                secondary_used=secondary_used,
                        cache_hit_tokens=cache_hit,
                        cache_miss_tokens=cache_miss,
                        cost_usd=pricing.estimate_cost(
                            stat_prov,
                            {
                                **stream_usage,
                                "cache_hit_tokens": cache_hit,
                                "cache_miss_tokens": cache_miss,
                            },
                            cfg,
                        ),
                        route_reason=route["reason"],
                    )
                else:
                    add_usage_stat(
                        user_id=user_id, provider_id=stat_prov.get("id", ""),
                        provider_name=stat_prov.get("name", ""), provider_type=stat_prov.get("type", ""),
                        model=model or stat_prov.get("model", ""),
                        tokens_prompt=_prompt_tokens, tokens_completion=_estimate_tokens(full_response),
                        tokens_total=_prompt_tokens + _estimate_tokens(full_response),
                        response_time_ms=int((time.time() - _req_start) * 1000),
                        stream=True, search_used=search_used,
                                                secondary_used=secondary_used,
                        cost_usd=pricing.estimate_cost(
                            stat_prov,
                            {
                                "prompt_tokens": _prompt_tokens,
                                "completion_tokens": _estimate_tokens(full_response),
                            },
                            cfg,
                        ),
                        route_reason=route["reason"],
                    )
            except Exception:
                pass
        except TraceCancelled:
            log.info("[%s] Stream cancelled trace=%s", user_id, trace_id)
            async for part in flush_activity():
                yield part
            yield "data: [DONE]\n\n"
        except Exception as e:
            from services.provider_errors import sanitize_error_message

            safe = sanitize_error_message(f"Provider error: {e}")
            log.error("[%s] Stream/background job failed: %s", user_id, e)
            provider_router.record_failure(chat_provider.get("id", ""))
            await on_stream_activity({
                "id": "assistant-out",
                "name": "assistant",
                "detail": safe,
                "status": "done",
            })
            async for part in flush_activity():
                yield part
            _trace_done(trace_id, error=safe)
            yield "data: [DONE]\n\n"
        finally:
            if trace_id and trace_id in _traces and not _traces[trace_id].get("done"):
                _trace_done(trace_id)

    if background:
        if not trace_id:
            return JSONResponse(
                status_code=400,
                content={
                    "error": {
                        "message": "background requires a valid trace_id",
                        "type": "invalid_request_error",
                    },
                },
            )
        _register_session_job(session_id, trace_id)

        async def _background_job():
            try:
                async for _chunk in stream_wrapper():
                    pass
            except Exception as e:
                log.error("[%s] Background chat job crashed: %s", user_id, e)
                if trace_id in _traces and not _traces[trace_id].get("done"):
                    _trace_done(trace_id, error=str(e)[:500])
            finally:
                if session_id and _session_jobs.get(session_id) == trace_id:
                    _session_jobs.pop(session_id, None)

        asyncio.create_task(_background_job())
        log.info("[%s] Background chat job started trace=%s session=%s", user_id, trace_id, session_id)
        return JSONResponse(
            status_code=202,
            content={
                "id": f"hassai-job-{trace_id}",
                "object": "hassai.chat.job",
                "created": int(time.time()),
                "model": model or chat_provider.get("model", ""),
                "status": "running",
                "session_id": session_id,
                "trace_id": trace_id,
                "choices": [],
            },
        )

    async def _guarded_stream():
        try:
            async for chunk in stream_wrapper():
                yield chunk
        except Exception as e:
            log.error(f"[{user_id}] Stream failed: {e}")
            _trace_done(trace_id, error=str(e)[:500])
            async for chunk in _sse_error(f"Provider error: {e}"):
                yield chunk

    return StreamingResponse(
        _guarded_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


async def _sse_error(message: str):
    from services.provider_errors import sanitize_error_message

    safe = sanitize_error_message(message)
    payload = json.dumps({
        "id": "hassai-error",
        "object": "chat.completion.chunk",
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": safe},
            "finish_reason": "stop",
        }],
    })
    yield f"data: {payload}\n\n"
    yield "data: [DONE]\n\n"


def _sse_content_delta(content: str) -> str:
    payload = json.dumps({
        "id": f"hassai-img-{int(time.time())}",
        "object": "chat.completion.chunk",
        "choices": [{
            "index": 0,
            "delta": {"role": "assistant", "content": content},
            "finish_reason": None,
        }],
    })
    return f"data: {payload}\n\n"


# Per-user extraction locks to prevent concurrent duplicate extractions (#6)
_extraction_locks: dict[str, asyncio.Lock] = {}
_EXTRACTION_TIMEOUT = 30.0  # seconds (#8)


async def _safe_extract(
    user_id: str,
    messages: list[dict],
    provider: dict | None = None,
    *,
    active: dict | None = None,
):
    """Safely run memory extraction in background with per-user lock and timeout."""
    active = active or providers.get_active_provider()
    # Memory extraction uses the primary provider (not secondary).
    if provider is None:
        provider = active
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
