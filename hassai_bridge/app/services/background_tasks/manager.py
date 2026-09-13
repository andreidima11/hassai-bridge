"""Task manager: validate, create, get, list, cancel."""

from __future__ import annotations

import logging
import time
from typing import Any

from core.config import load_config
from services import ha_tool_access as hta
from services import tool_enable as te
from services.background_tasks import store

log = logging.getLogger("hassai.bg_tasks")

KINDS = frozenset({"monitor_entities", "wait_for_state", "remind_me"})
MAX_REMIND_SECONDS = 7 * 24 * 3600  # 7 days


def _bg_cfg(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    raw = dict((cfg.get("background_tasks") or {}))
    return {
        "enabled": bool(raw.get("enabled", True)),
        "max_active_per_user": max(1, min(int(raw.get("max_active_per_user") or 5), 50)),
        "max_monitor_hours": max(0.05, min(float(raw.get("max_monitor_hours") or 24), 168)),
        "max_result_days": max(1, min(int(raw.get("max_result_days") or 30), 365)),
        "worker_lease_seconds": max(10, min(int(raw.get("worker_lease_seconds") or 30), 300)),
        "notify_service": str(raw.get("notify_service") or "").strip(),
        "notify_on_complete": bool(raw.get("notify_on_complete", True)),
        "max_remind_seconds": max(
            60,
            min(int(raw.get("max_remind_seconds") or MAX_REMIND_SECONDS), MAX_REMIND_SECONDS),
        ),
    }


def snapshot_permissions(cfg: dict | None, session_id: str | None) -> dict:
    cfg = cfg or load_config()
    return {
        "ha_entities": te.effectively_enabled("ha:entities", cfg, session_id),
        "ha_categories": sorted(hta.enabled_categories(cfg)),
        "bridge_tools": dict((cfg.get("bridge_tools") or {})),
        "captured_at": time.time(),
    }


def permissions_still_ok(
    scope: dict | None,
    cfg: dict | None,
    session_id: str | None,
    *,
    kind: str | None = None,
) -> tuple[bool, str]:
    if kind == "remind_me":
        return True, ""
    scope = scope or {}
    if not scope.get("ha_entities", True):
        return False, "entities permission was not granted at create time"
    if not te.effectively_enabled("ha:entities", cfg or load_config(), session_id):
        return False, "ha:entities is OFF in Settings"
    return True, ""


def _validate_spec(
    kind: str,
    spec: dict,
    *,
    max_hours: float,
    max_remind_seconds: int = MAX_REMIND_SECONDS,
) -> tuple[dict, str | None]:
    spec = dict(spec or {})
    if kind == "remind_me":
        message = str(spec.get("message") or "").strip()
        if not message:
            return {}, "remind_me requires message"
        if len(message) > 500:
            message = message[:500].rstrip()
        delay = float(spec.get("delay_seconds") or spec.get("delay") or 0)
        if delay <= 0 and spec.get("delay_minutes"):
            delay = float(spec.get("delay_minutes")) * 60.0
        if delay <= 0:
            return {}, "remind_me requires delay_seconds or delay_minutes (> 0)"
        delay = max(1.0, min(delay, float(max_remind_seconds)))
        return {
            "delay_seconds": delay,
            "message": message,
        }, None

    if kind == "monitor_entities":
        entities = spec.get("entity_ids") or spec.get("entities") or []
        if isinstance(entities, str):
            entities = [entities]
        if not isinstance(entities, list) or not entities:
            return {}, "monitor_entities requires entity_ids (non-empty list)"
        cleaned = []
        for e in entities[:50]:
            eid = str(e or "").strip()
            if eid and eid not in cleaned:
                cleaned.append(eid)
        if not cleaned:
            return {}, "monitor_entities requires at least one entity_id"
        duration = float(spec.get("duration_seconds") or spec.get("duration") or 0)
        if duration <= 0 and spec.get("duration_minutes"):
            duration = float(spec.get("duration_minutes")) * 60.0
        if duration <= 0:
            duration = 1800.0
        max_sec = max_hours * 3600.0
        if duration > max_sec:
            duration = max_sec
        states_of_interest = spec.get("states_of_interest")
        if isinstance(states_of_interest, str):
            states_of_interest = [states_of_interest]
        if not isinstance(states_of_interest, list):
            states_of_interest = []
        return {
            "entity_ids": cleaned,
            "duration_seconds": duration,
            "states_of_interest": [str(s).strip() for s in states_of_interest if str(s).strip()][:20],
        }, None

    if kind == "wait_for_state":
        entity_id = str(spec.get("entity_id") or "").strip()
        if not entity_id and isinstance(spec.get("entity_ids"), list) and spec["entity_ids"]:
            entity_id = str(spec["entity_ids"][0] or "").strip()
        if not entity_id:
            return {}, "wait_for_state requires entity_id"
        state = spec.get("state")
        if state is None or str(state).strip() == "":
            return {}, "wait_for_state requires state"
        timeout = float(spec.get("timeout_seconds") or spec.get("timeout") or 0)
        if timeout <= 0 and spec.get("timeout_minutes"):
            timeout = float(spec.get("timeout_minutes")) * 60.0
        if timeout <= 0:
            timeout = 1800.0
        max_sec = max_hours * 3600.0
        if timeout > max_sec:
            timeout = max_sec
        stable = float(spec.get("stable_for_seconds") or 0)
        stable = max(0.0, min(stable, 600.0))
        accept = bool(spec.get("accept_already_true", False))
        return {
            "entity_id": entity_id,
            "state": str(state).strip(),
            "timeout_seconds": timeout,
            "stable_for_seconds": stable,
            "accept_already_true": accept,
        }, None

    return {}, f"unsupported kind: {kind}"


def create_task(
    *,
    owner_id: str,
    session_id: str,
    kind: str,
    title: str = "",
    spec: dict | None = None,
    idempotency_key: str | None = None,
    cfg: dict | None = None,
) -> dict:
    cfg = cfg or load_config()
    bg = _bg_cfg(cfg)
    if not bg["enabled"]:
        return {"ok": False, "error": "background_tasks are disabled in Settings"}
    kind = str(kind or "").strip()
    if kind not in KINDS:
        return {"ok": False, "error": f"kind must be one of: {', '.join(sorted(KINDS))}"}

    key = str(idempotency_key or "").strip()
    if key:
        existing = store.get_by_idempotency(owner_id, key)
        if existing:
            return {"ok": True, "task": public_task(existing), "deduplicated": True}

    if store.count_active(owner_id) >= bg["max_active_per_user"]:
        return {
            "ok": False,
            "error": f"active task limit reached ({bg['max_active_per_user']} per user)",
        }

    if kind != "remind_me":
        ok_perm, reason = permissions_still_ok({"ha_entities": True}, cfg, session_id, kind=kind)
        if not ok_perm:
            return {"ok": False, "error": reason}

    cleaned, err = _validate_spec(
        kind,
        spec or {},
        max_hours=bg["max_monitor_hours"],
        max_remind_seconds=bg["max_remind_seconds"],
    )
    if err:
        return {"ok": False, "error": err}

    if kind == "remind_me":
        duration = float(cleaned.get("delay_seconds") or 60)
    else:
        duration = cleaned.get("duration_seconds") or cleaned.get("timeout_seconds") or 1800
    now = time.time()
    deadline = now + float(duration)
    # Reminders sleep until due; monitors/waits start immediately.
    next_run = deadline if kind == "remind_me" else now
    scope = snapshot_permissions(cfg, session_id)
    if kind == "remind_me":
        scope = {**scope, "ha_entities": False}
    task_id = store.new_task_id()
    title = str(title or "").strip() or _default_title(kind, cleaned)
    try:
        task = store.insert_task(
            task_id=task_id,
            owner_id=owner_id,
            session_id=session_id or "",
            kind=kind,
            title=title,
            spec=cleaned,
            status="scheduled",
            deadline_at=deadline,
            next_run_at=next_run,
            permission_scope=scope,
            idempotency_key=key or None,
        )
    except Exception as exc:
        # Unique idempotency race
        if key:
            existing = store.get_by_idempotency(owner_id, key)
            if existing:
                return {"ok": True, "task": public_task(existing), "deduplicated": True}
        log.exception("create_task failed")
        return {"ok": False, "error": str(exc)}

    try:
        from services.background_tasks import ha_events

        ha_events.refresh_watch_index()
    except Exception:
        pass

    try:
        from services.background_tasks import delivery as bg_delivery

        bg_delivery.post_created_card(task)
        task = store.get_task(task_id) or task
    except Exception:
        log.exception("post_created_card failed for %s", task_id)

    return {
        "ok": True,
        "task": public_task(task),
        "deduplicated": False,
        "hint": (
            "Task saved and scheduled. It continues even if this chat is closed. "
            "Use background_tasks get/list/cancel; the result is posted back to this conversation."
        ),
    }


def _default_title(kind: str, spec: dict) -> str:
    if kind == "monitor_entities":
        ids = spec.get("entity_ids") or []
        return f"Monitor {', '.join(ids[:3])}{'…' if len(ids) > 3 else ''}"
    if kind == "wait_for_state":
        return f"Wait {spec.get('entity_id')}={spec.get('state')}"
    if kind == "remind_me":
        msg = str(spec.get("message") or "").strip()
        delay = int(float(spec.get("delay_seconds") or 0))
        if msg:
            short = msg if len(msg) <= 40 else msg[:37].rstrip() + "…"
            return f"Remind in {delay}s: {short}"
        return f"Remind in {delay}s"
    return kind


def public_task(task: dict | None) -> dict | None:
    if not task:
        return None
    return {
        "task_id": task.get("task_id"),
        "kind": task.get("kind"),
        "title": task.get("title"),
        "status": task.get("status"),
        "session_id": task.get("session_id"),
        "created_at": task.get("created_at"),
        "started_at": task.get("started_at"),
        "deadline_at": task.get("deadline_at"),
        "updated_at": task.get("updated_at"),
        "cancel_requested_at": task.get("cancel_requested_at"),
        "progress": task.get("progress") or {},
        "result": task.get("result"),
        "error": task.get("error"),
        "spec": task.get("spec") or {},
        "feed_seq": task.get("feed_seq") or 0,
    }


def get_task(task_id: str, *, owner_id: str) -> dict:
    task = store.get_task(task_id)
    if not task or task.get("owner_id") != owner_id:
        return {"ok": False, "error": "task not found"}
    return {
        "ok": True,
        "task": public_task(task),
        "events": store.list_events(task_id, limit=50),
        "observations_count": len(store.list_observations(task_id, limit=5000)),
    }


def list_tasks(
    owner_id: str,
    *,
    status_filter: list[str] | None = None,
    limit: int = 20,
    session_id: str | None = None,
) -> dict:
    rows = store.list_tasks(
        owner_id, status_filter=status_filter, limit=limit, session_id=session_id,
    )
    return {"ok": True, "tasks": [public_task(t) for t in rows]}


def cancel_task(task_id: str, *, owner_id: str) -> dict:
    task = store.get_task(task_id)
    if not task or task.get("owner_id") != owner_id:
        return {"ok": False, "error": "task not found"}
    updated = store.request_cancel(task_id)
    return {
        "ok": True,
        "task": public_task(updated),
        "hint": "Cancel requested. No new steps will be scheduled; partial results are kept.",
    }


def feed(session_id: str, after_seq: int = 0, *, owner_id: str | None = None) -> dict:
    rows = store.feed_since(session_id, after_seq)
    if owner_id:
        rows = [t for t in rows if t.get("owner_id") == owner_id]
    return {
        "ok": True,
        "tasks": [public_task(t) for t in rows],
        "after": max([int(t.get("feed_seq") or 0) for t in rows] + [int(after_seq or 0)]),
    }
