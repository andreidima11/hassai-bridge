"""Cursor-style mid-loop approval for risky tools.

The agent loop parks on an asyncio.Future until the Web UI posts
approve / decline (or the request times out / the trace is cancelled).
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from services.lovelace_tools import HA_MUTATING_TOOLS

# Extra mutating tools outside HA_MUTATING_TOOLS.
_EXTRA_RISKY = frozenset({
    "media_delete",
    "browser_interact",
    "hassai_set_setting",
    "hassai_switch_provider",
    "ha_delete_helper",
    "ha_create_helper",
    "ha_update_helper",
    "ha_recorder_purge",
    "ha_recorder_purge_entities",
    "ha_hacs_install",
    "ha_hacs_remove",
})

RISKY_TOOLS = frozenset(HA_MUTATING_TOOLS | _EXTRA_RISKY)

APPROVAL_TIMEOUT_SEC = 300  # 5 minutes → auto-decline
DECLINED_RESULT = "User declined this action."
TIMEOUT_RESULT = "User did not approve this action in time (auto-declined)."

# trace_id → {call_id → pending dict}
_pending: dict[str, dict[str, dict[str, Any]]] = {}
# session_id → set of conversation-scoped allow keys
_conversation_allow: dict[str, set[str]] = {}


def is_risky(name: str | None) -> bool:
    return bool(name) and str(name) in RISKY_TOOLS


def needs_approval(name: str | None, args: dict | None = None) -> bool:
    """True when the UI must gate this call (before execution)."""
    return is_risky(name)


def conversation_allow_key(name: str, args: dict | None = None) -> str:
    """Coarse key for 'Allow for this chat' — tool name + domain.service when present."""
    args = args if isinstance(args, dict) else {}
    if name == "ha_call_service":
        domain = str(args.get("domain") or "").strip().lower()
        service = str(args.get("service") or "").strip().lower()
        if domain and service:
            return f"{name}:{domain}.{service}"
    if name == "browser_interact":
        action = str(args.get("action") or "").strip().lower()
        return f"{name}:{action or '*'}"
    return str(name or "")


def is_conversation_allowed(session_id: str | None, name: str, args: dict | None = None) -> bool:
    sid = str(session_id or "").strip()
    if not sid:
        return False
    keys = _conversation_allow.get(sid) or set()
    full = conversation_allow_key(name, args)
    return full in keys or str(name) in keys


def grant_conversation(session_id: str | None, name: str, args: dict | None = None) -> None:
    sid = str(session_id or "").strip()
    if not sid or not name:
        return
    bucket = _conversation_allow.setdefault(sid, set())
    bucket.add(conversation_allow_key(name, args))
    # Also allow the bare tool name so repeated similar calls are less noisy.
    bucket.add(str(name))


def clear_conversation(session_id: str | None) -> None:
    sid = str(session_id or "").strip()
    if sid:
        _conversation_allow.pop(sid, None)


def inject_confirm(args: dict | None) -> dict:
    """Satisfy legacy confirm=true handlers after UI approval."""
    out = dict(args or {})
    out["confirm"] = True
    return out


def args_preview(name: str, args: dict | None, *, limit: int = 280) -> str:
    """Short human-readable preview for the approval bubble."""
    raw = args if isinstance(args, dict) else {}
    # Prefer a few meaningful keys; fall back to compact JSON.
    prefer = (
        "action", "url", "path", "entity_id", "domain", "service", "name",
        "what", "file_path", "dashboard", "view_path", "area_id", "key",
    )
    bits: list[str] = []
    for key in prefer:
        if key not in raw:
            continue
        val = raw[key]
        if val is None or val == "" or val is False:
            continue
        if isinstance(val, (dict, list)):
            continue
        bits.append(f"{key}={val}")
        if len(bits) >= 4:
            break
    if bits:
        text = ", ".join(bits)
    else:
        try:
            text = json.dumps(raw, ensure_ascii=False, default=str)
        except Exception:
            text = str(raw)
    text = text.replace("\n", " ").strip()
    if len(text) > limit:
        return text[: limit - 1] + "…"
    return text


def register_pending(
    trace_id: str,
    call_id: str,
    *,
    name: str,
    args: dict | None,
    detail: str = "",
) -> asyncio.Future:
    """Create (or replace) a pending approval Future for this tool call."""
    tid = str(trace_id or "").strip()
    cid = str(call_id or "").strip()
    if not tid or not cid:
        raise ValueError("trace_id and call_id required")
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    bucket = _pending.setdefault(tid, {})
    old = bucket.get(cid)
    if old and isinstance(old.get("future"), asyncio.Future) and not old["future"].done():
        old["future"].cancel()
    bucket[cid] = {
        "future": fut,
        "name": name,
        "args": dict(args or {}),
        "detail": detail,
        "ts": time.time(),
    }
    return fut


def resolve(
    trace_id: str,
    call_id: str,
    *,
    decision: str,
    scope: str = "once",
    session_id: str | None = None,
) -> dict:
    """Resolve a pending approval. decision: approve | decline."""
    tid = str(trace_id or "").strip()
    cid = str(call_id or "").strip()
    dec = str(decision or "").strip().lower()
    if dec not in {"approve", "decline"}:
        return {"ok": False, "error": "decision must be approve or decline"}
    bucket = _pending.get(tid) or {}
    row = bucket.get(cid)
    if not row:
        return {"ok": False, "error": "No pending approval for this call"}
    fut = row.get("future")
    if not isinstance(fut, asyncio.Future) or fut.done():
        bucket.pop(cid, None)
        if not bucket:
            _pending.pop(tid, None)
        return {"ok": False, "error": "Approval already resolved"}
    if dec == "approve" and str(scope or "once").lower() == "conversation":
        grant_conversation(session_id, row.get("name") or "", row.get("args"))
    fut.set_result({
        "decision": dec,
        "scope": str(scope or "once").lower(),
    })
    bucket.pop(cid, None)
    if not bucket:
        _pending.pop(tid, None)
    return {"ok": True, "decision": dec, "call_id": cid}


def cancel_trace(trace_id: str) -> None:
    """Cancel all pending approvals for a cancelled chat trace."""
    tid = str(trace_id or "").strip()
    bucket = _pending.pop(tid, None) or {}
    for row in bucket.values():
        fut = row.get("future")
        if isinstance(fut, asyncio.Future) and not fut.done():
            fut.cancel()


async def wait_decision(
    future: asyncio.Future,
    *,
    timeout: float = APPROVAL_TIMEOUT_SEC,
) -> dict:
    """Await UI decision. Returns {decision: approve|decline|timeout|cancelled}."""
    try:
        result = await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
        if isinstance(result, dict):
            return result
        return {"decision": "decline"}
    except asyncio.TimeoutError:
        if not future.done():
            future.set_result({"decision": "timeout"})
        return {"decision": "timeout"}
    except asyncio.CancelledError:
        return {"decision": "cancelled"}


def pending_for_trace(trace_id: str) -> list[dict]:
    tid = str(trace_id or "").strip()
    out = []
    for cid, row in (_pending.get(tid) or {}).items():
        out.append({
            "call_id": cid,
            "name": row.get("name"),
            "detail": row.get("detail") or "",
            "args_preview": args_preview(row.get("name") or "", row.get("args")),
        })
    return out
