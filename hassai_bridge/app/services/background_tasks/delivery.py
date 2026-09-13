"""Deliver completed task results into the original conversation."""

from __future__ import annotations

import logging
import time

from core.config import load_config
from core.database import add_conversation_message
from services.background_tasks import i18n as bg_i18n
from services.background_tasks import store

log = logging.getLogger("hassai.bg_delivery")


def _public_card(task: dict) -> dict:
    return {
        "task_id": task.get("task_id"),
        "kind": task.get("kind"),
        "title": task.get("title"),
        "status": task.get("status"),
        "cancel_requested_at": task.get("cancel_requested_at"),
        "progress": task.get("progress") or {},
        "result": task.get("result"),
        "error": task.get("error"),
        "spec": task.get("spec") or {},
        "deadline_at": task.get("deadline_at"),
        "feed_seq": task.get("feed_seq") or 0,
    }


def _message_body(task: dict, *, lang: str | None = None) -> str:
    from services.background_tasks import worker as worker_mod

    lang = lang or bg_i18n.lang_from_cfg()
    kind = task.get("kind")
    result = task.get("result") or {}
    title = task.get("title") or bg_i18n.t(lang, "fallback_title")
    if task.get("status") == "cancelled":
        extra = bg_i18n.t(lang, "cancelled_extra") if result else ""
        return bg_i18n.t(lang, "cancelled", title=title, extra=extra)
    if task.get("status") == "failed":
        err = task.get("error") or {}
        return bg_i18n.t(
            lang,
            "failed",
            title=title,
            code=err.get("code") or "error",
            reason=err.get("reason") or bg_i18n.t(lang, "unknown"),
        )
    if task.get("status") == "blocked":
        err = task.get("error") or {}
        return bg_i18n.t(
            lang,
            "blocked",
            title=title,
            reason=err.get("reason") or bg_i18n.t(lang, "permission_required"),
        )
    if kind == "monitor_entities":
        return worker_mod.format_monitor_message(
            task, result if isinstance(result, dict) else {}, lang=lang,
        )
    if kind == "wait_for_state":
        return worker_mod.format_wait_message(
            task, result if isinstance(result, dict) else {}, lang=lang,
        )
    if kind == "remind_me":
        return worker_mod.format_remind_message(
            task, result if isinstance(result, dict) else {}, lang=lang,
        )
    return bg_i18n.t(lang, "status_line", title=title, status=task.get("status"))


def _notify_title(task: dict, *, lang: str | None = None) -> str:
    lang = lang or bg_i18n.lang_from_cfg()
    title = str(task.get("title") or bg_i18n.t(lang, "fallback_title")).strip()
    prefix = "HASSAI"
    if task.get("kind") == "remind_me":
        prefix = bg_i18n.t(lang, "notify_remind_prefix")
    raw = f"{prefix}: {title}"
    return raw if len(raw) <= 80 else raw[:77].rstrip() + "…"


def _notify_body(body: str) -> str:
    text = " ".join(str(body or "").replace("**", "").split())
    if len(text) <= 220:
        return text
    return text[:217].rstrip() + "…"


async def _maybe_ha_notify(task: dict, body: str, *, cfg: dict | None = None) -> None:
    """Best-effort phone notify after a result is posted to chat."""
    from services.background_tasks import manager

    cfg = cfg or load_config()
    bg = manager._bg_cfg(cfg)
    if not bg.get("notify_on_complete", True):
        return
    service = str(bg.get("notify_service") or "").strip()
    if not service:
        return
    if "." not in service:
        service = f"notify.{service}"
    domain, svc = service.split(".", 1)
    title = _notify_title(task)
    message = _notify_body(body)
    if not message:
        return
    try:
        from services import homeassistant as ha

        await ha._core(
            "POST",
            f"/services/{domain}/{svc}",
            json_body={"message": message, "title": title},
        )
        log.info("bg notify sent via %s for task %s", service, task.get("task_id"))
    except Exception as exc:
        log.warning(
            "bg notify failed for task %s via %s: %s",
            task.get("task_id"),
            service,
            exc,
        )


def _post_message(task: dict, body: str, *, meta_extra: dict | None = None) -> None:
    meta = {
        "background_task_id": task["task_id"],
        "background_task": _public_card(task),
    }
    if meta_extra:
        meta.update(meta_extra)
    add_conversation_message(
        task["owner_id"],
        "assistant",
        body,
        session_id=task.get("session_id") or None,
        meta=meta,
    )
    store.touch_feed(task["task_id"])


def post_created_card(task: dict) -> None:
    """Persist a chat card as soon as the task is scheduled."""
    if not task or not task.get("task_id"):
        return
    delivery_id = store.new_delivery_id(task["task_id"], "created")
    existing = store.get_delivery(delivery_id)
    if existing and existing.get("status") == "delivered":
        return
    lang = bg_i18n.lang_from_cfg(load_config())
    title = task.get("title") or bg_i18n.t(lang, "fallback_title")
    kind = task.get("kind") or "task"
    spec = task.get("spec") or {}
    if kind == "monitor_entities":
        detail = ", ".join(spec.get("entity_ids") or []) or bg_i18n.t(lang, "entities_fallback")
        dur = int(float(spec.get("duration_seconds") or 0))
        body = bg_i18n.t(lang, "created_monitor", title=title, detail=detail, dur=dur)
    elif kind == "wait_for_state":
        body = bg_i18n.t(
            lang,
            "created_wait",
            title=title,
            entity_id=spec.get("entity_id"),
            state=spec.get("state"),
        )
    elif kind == "remind_me":
        delay = int(float(spec.get("delay_seconds") or 0))
        msg = str(spec.get("message") or "").strip() or "—"
        body = bg_i18n.t(lang, "created_remind", title=title, delay=delay, message=msg)
    else:
        body = bg_i18n.t(lang, "created_generic", title=title)
    try:
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=task["task_id"],
            kind="created",
            status="pending",
            message_meta={"task_id": task["task_id"]},
        )
        _post_message(task, body)
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=task["task_id"],
            kind="created",
            status="delivered",
            attempts=1,
            last_error="",
        )
    except Exception as exc:
        log.exception("post_created_card failed")
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=task["task_id"],
            kind="created",
            status="failed",
            last_error=str(exc),
            attempts=1,
        )


async def notify_blocked(task_id: str) -> None:
    """One-shot chat notice when a task becomes blocked on permissions."""
    task = store.get_task(task_id)
    if not task:
        return
    delivery_id = store.new_delivery_id(task_id, "blocked")
    existing = store.get_delivery(delivery_id)
    if existing and existing.get("status") == "delivered":
        return
    store.upsert_delivery(
        delivery_id=delivery_id,
        task_id=task_id,
        kind="blocked",
        status="pending",
        message_meta={"task_id": task_id},
    )
    try:
        lang = bg_i18n.lang_from_cfg(load_config())
        _post_message(task, _message_body(task, lang=lang))
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=task_id,
            kind="blocked",
            status="delivered",
            attempts=1,
            last_error="",
        )
    except Exception as exc:
        log.exception("notify_blocked failed")
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=task_id,
            kind="blocked",
            status="failed",
            last_error=str(exc),
            attempts=1,
        )


async def enqueue_result(task_id: str) -> None:
    task = store.get_task(task_id)
    if not task:
        return
    delivery_id = store.new_delivery_id(task_id, "result")
    existing = store.get_delivery(delivery_id)
    if existing and existing.get("status") == "delivered":
        return
    store.upsert_delivery(
        delivery_id=delivery_id,
        task_id=task_id,
        kind="result",
        status="pending",
        message_meta={"task_id": task_id},
        attempts=int((existing or {}).get("attempts") or 0),
    )
    await try_deliver(delivery_id)


async def try_deliver(delivery_id: str) -> bool:
    row = store.get_delivery(delivery_id)
    if not row:
        return False
    if row.get("status") == "delivered":
        return True
    task = store.get_task(row["task_id"])
    if not task:
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=row["task_id"],
            kind=row.get("kind") or "result",
            status="failed",
            last_error="task missing",
            attempts=int(row.get("attempts") or 0) + 1,
        )
        return False
    lang = bg_i18n.lang_from_cfg(load_config())
    body = _message_body(task, lang=lang)
    meta = {
        "background_task_id": task["task_id"],
        "background_task": _public_card(task),
    }
    try:
        add_conversation_message(
            task["owner_id"],
            "assistant",
            body,
            session_id=task.get("session_id") or None,
            meta=meta,
        )
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=task["task_id"],
            kind=row.get("kind") or "result",
            status="delivered",
            message_meta=meta,
            attempts=int(row.get("attempts") or 0) + 1,
            last_error="",
        )
        store.touch_feed(task["task_id"])
        if (row.get("kind") or "result") == "result":
            try:
                await _maybe_ha_notify(task, body)
            except Exception:
                log.exception("unexpected notify error for %s", task.get("task_id"))
        return True
    except Exception as exc:
        log.exception("delivery failed %s", delivery_id)
        store.upsert_delivery(
            delivery_id=delivery_id,
            task_id=row["task_id"],
            kind=row.get("kind") or "result",
            status="failed",
            last_error=str(exc),
            attempts=int(row.get("attempts") or 0) + 1,
            message_meta=meta,
        )
        return False


async def retry_pending(limit: int = 10) -> None:
    for row in store.list_pending_deliveries(limit=limit):
        if int(row.get("attempts") or 0) > 20:
            continue
        if row.get("status") == "failed" and (time.time() - float(row.get("updated_at") or 0)) < 5:
            continue
        kind = row.get("kind") or "result"
        if kind == "created":
            task = store.get_task(row["task_id"])
            if task:
                post_created_card(task)
            continue
        if kind == "blocked":
            await notify_blocked(row["task_id"])
            continue
        await try_deliver(row["delivery_id"])
