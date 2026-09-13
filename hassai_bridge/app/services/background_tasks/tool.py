"""LLM-facing background_tasks tool."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from services.background_tasks import manager

log = logging.getLogger("hassai.bg_tool")

TOOL_NAME = "background_tasks"

_ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$", re.I)


def system_hint(cfg: dict | None = None) -> str:
    from core.config import load_config

    cfg = cfg or load_config()
    bg = (cfg.get("background_tasks") or {})
    if bg.get("enabled", True) is False:
        return ""
    notify = str(bg.get("notify_service") or "").strip()
    notify_bit = (
        f" When a task finishes, results are also sent to HA notify `{notify}` (Settings override)."
        if notify
        else (
            " When a task finishes, results are also pushed to the logged-in user's "
            "Companion phone notify when Home Assistant can resolve it "
            "(person → device_tracker → notify.mobile_app_*)."
        )
    )
    return (
        "Background tasks: use background_tasks for remind_me / wait_for_state / monitor_entities "
        "when the user needs a timed reminder, waiting, or monitoring that outlives this turn. "
        "For “remind me in X minutes…”, create kind=remind_me (delay_seconds + message) — "
        "do not invent HA timer+automation unless the user asks for Core-native persistence outside the add-on. "
        "Results are posted back to this chat by the backend."
        + notify_bit
        + " Do not invent entity_id values."
    )


TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Create, inspect, list, or cancel persistent background tasks run by HASSAI Bridge. "
            "Use when the request needs a timed reminder, waiting for a condition, monitoring over a "
            "period, or long-running observation without blocking the current chat. "
            "Kinds (v1): remind_me, monitor_entities, wait_for_state. "
            "Do not promise the task started until create returns ok. "
            "Results are posted back to this conversation by the backend even if the chat is closed "
            "(and to the configured HA notify service when set). "
            "Identity and destination conversation are set by the backend."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "get", "list", "cancel"],
                    "description": "create | get | list | cancel",
                },
                "task_id": {
                    "type": "string",
                    "description": "Required for get and cancel",
                },
                "kind": {
                    "type": "string",
                    "enum": ["remind_me", "monitor_entities", "wait_for_state"],
                    "description": "Required for create",
                },
                "title": {
                    "type": "string",
                    "description": "Short title for the chat card",
                },
                "spec": {
                    "type": "object",
                    "description": (
                        "Kind-specific config. remind_me: message, delay_seconds (or delay_minutes; "
                        "max 7 days). monitor_entities: entity_ids[], duration_seconds, "
                        "optional states_of_interest[]. wait_for_state: entity_id, state, "
                        "timeout_seconds, optional stable_for_seconds, accept_already_true."
                    ),
                },
                "idempotency_key": {
                    "type": "string",
                    "description": "Optional; repeating the same key returns the existing task",
                },
                "status_filter": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional for list",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for list (default 20)",
                },
            },
            "required": ["action"],
        },
    },
}


def _entity_ids_from_args(args: dict) -> list[str]:
    kind = str(args.get("kind") or "").strip()
    spec = args.get("spec") if isinstance(args.get("spec"), dict) else {}
    ids: list[str] = []
    if kind == "monitor_entities":
        raw = spec.get("entity_ids") or spec.get("entities") or []
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, list):
            ids = [str(e).strip() for e in raw if str(e).strip()]
    elif kind == "wait_for_state":
        eid = str(spec.get("entity_id") or "").strip()
        if not eid and isinstance(spec.get("entity_ids"), list) and spec["entity_ids"]:
            eid = str(spec["entity_ids"][0] or "").strip()
        if eid:
            ids = [eid]
    return ids


async def _resolve_entities(entity_ids: list[str]) -> tuple[list[str], list[str], str | None]:
    """Return (valid, missing, error). Skips live HA check when unavailable."""
    cleaned: list[str] = []
    for eid in entity_ids:
        if not _ENTITY_RE.match(eid):
            return [], [eid], f"invalid entity_id format: {eid}"
        if eid not in cleaned:
            cleaned.append(eid)
    if not cleaned:
        return [], [], None
    try:
        from services import homeassistant as ha

        missing: list[str] = []
        for eid in cleaned:
            try:
                st = await ha._core("GET", f"/states/{eid}")
                if not isinstance(st, dict) or "state" not in st:
                    missing.append(eid)
            except Exception:
                missing.append(eid)
        if missing:
            return cleaned, missing, f"unknown entity_id(s): {', '.join(missing)}"
        return cleaned, [], None
    except Exception as exc:
        # HA unreachable — still allow create if IDs look valid (tests / offline)
        log.debug("entity resolve skipped (HA unavailable): %s", exc)
        return cleaned, [], None


def run_tool(
    args: dict,
    *,
    user_id: str = "",
    session_id: str | None = None,
    cfg: dict | None = None,
) -> str:
    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or "").strip().lower()
    if not user_id:
        return json.dumps({"ok": False, "error": "no user context"}, ensure_ascii=False)

    if action == "create":
        out = manager.create_task(
            owner_id=user_id,
            session_id=session_id or "",
            kind=str(args.get("kind") or ""),
            title=str(args.get("title") or ""),
            spec=args.get("spec") if isinstance(args.get("spec"), dict) else {},
            idempotency_key=str(args.get("idempotency_key") or "") or None,
            cfg=cfg,
        )
        return json.dumps(out, ensure_ascii=False, default=str)

    if action == "get":
        tid = str(args.get("task_id") or "").strip()
        if not tid:
            return json.dumps({"ok": False, "error": "task_id required"}, ensure_ascii=False)
        return json.dumps(manager.get_task(tid, owner_id=user_id), ensure_ascii=False, default=str)

    if action == "list":
        filt = args.get("status_filter")
        if isinstance(filt, str):
            filt = [filt]
        if not isinstance(filt, list):
            filt = None
        return json.dumps(
            manager.list_tasks(
                user_id,
                status_filter=filt,
                limit=int(args.get("limit") or 20),
                session_id=None,
            ),
            ensure_ascii=False,
            default=str,
        )

    if action == "cancel":
        tid = str(args.get("task_id") or "").strip()
        if not tid:
            return json.dumps({"ok": False, "error": "task_id required"}, ensure_ascii=False)
        return json.dumps(manager.cancel_task(tid, owner_id=user_id), ensure_ascii=False, default=str)

    return json.dumps(
        {"ok": False, "error": "action must be create|get|list|cancel"},
        ensure_ascii=False,
    )


async def run_tool_async(
    args: dict,
    *,
    user_id: str = "",
    session_id: str | None = None,
    cfg: dict | None = None,
) -> str:
    args = args if isinstance(args, dict) else {}
    action = str(args.get("action") or "").strip().lower()
    if action == "create":
        ids = _entity_ids_from_args(args)
        if ids:
            _valid, _missing, err = await _resolve_entities(ids)
            if err and _missing:
                return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
            if err and not _missing:
                return json.dumps({"ok": False, "error": err}, ensure_ascii=False)
    return run_tool(args, user_id=user_id, session_id=session_id, cfg=cfg)
