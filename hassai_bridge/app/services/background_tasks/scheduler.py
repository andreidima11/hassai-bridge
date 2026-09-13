"""Background task scheduler loop."""

from __future__ import annotations

import asyncio
import logging
import time

from core.config import load_config
from services.background_tasks import delivery, ha_events, manager, store, worker

log = logging.getLogger("hassai.bg_scheduler")

_task: asyncio.Task | None = None
_started = False
_last_cleanup_at = 0.0


async def recover_on_boot() -> None:
    """Resume or close tasks after add-on restart; open a coverage gap marker."""
    now = time.time()
    for task in store.list_recoverable():
        tid = task["task_id"]
        store.update_task(tid, lease_owner="", lease_until=None)
        if task.get("cancel_requested_at"):
            await worker._finish_cancelled(task)
            continue
        deadline = float(task.get("deadline_at") or 0)
        if deadline and now >= deadline:
            if task.get("kind") == "monitor_entities":
                result = worker.summarize_monitor(task)
                store.update_task(tid, status="completed", result=result)
                store.add_event(tid, "completed", {"reason": "deadline_after_restart"})
                await delivery.enqueue_result(tid)
            elif task.get("kind") == "wait_for_state":
                spec = task.get("spec") or {}
                result = {
                    "kind": "wait_for_state",
                    "matched": False,
                    "entity_id": spec.get("entity_id"),
                    "state": spec.get("state"),
                    "last_state": None,
                    "waited_seconds": round(
                        max(0.0, deadline - float(task.get("started_at") or task.get("created_at") or now)),
                        1,
                    ),
                    "timed_out": True,
                }
                store.update_task(tid, status="completed", result=result)
                store.add_event(tid, "completed", {"timed_out": True, "reason": "deadline_after_restart"})
                await delivery.enqueue_result(tid)
            elif task.get("kind") == "remind_me":
                result = worker.remind_result(task)
                store.update_task(tid, status="completed", result=result)
                store.add_event(tid, "completed", {"remind": True, "reason": "deadline_after_restart"})
                await delivery.enqueue_result(tid)
            continue
        # Resume — keep blocked as blocked; otherwise ensure runnable
        status = task.get("status") or "scheduled"
        if status == "blocked":
            store.update_task(tid, next_run_at=now)
        else:
            # Reminders wake at deadline; others resume immediately.
            wake = now
            if task.get("kind") == "remind_me" and deadline and deadline > now:
                wake = deadline
            store.update_task(
                tid,
                status="scheduled" if status not in ("running",) else status,
                next_run_at=wake,
            )

    # Single gap marker for reconnect (avoids duplicate gap_start events)
    ha_events._gap_open_at = None
    ha_events._open_gaps("addon_restart")
    ha_events.refresh_watch_index()
    log.info("background tasks recovery done")


async def _tick() -> None:
    global _last_cleanup_at
    cfg = load_config()
    bg = manager._bg_cfg(cfg)
    if not bg["enabled"]:
        return
    ha_events.refresh_watch_index()
    claimable = store.list_claimable(limit=10)
    for task in claimable:
        try:
            await worker.process_task(task)
        except Exception:
            log.exception("scheduler tick failed for %s", task.get("task_id"))
    try:
        await delivery.retry_pending(limit=5)
    except Exception:
        log.exception("delivery retry failed")
    now = time.time()
    if now - _last_cleanup_at > 3600:
        try:
            n = store.cleanup_old_results(bg["max_result_days"])
            if n:
                log.info("cleaned %s old background tasks", n)
        except Exception:
            log.exception("bg cleanup failed")
        _last_cleanup_at = now


async def _loop() -> None:
    await asyncio.sleep(3)
    try:
        await recover_on_boot()
    except Exception:
        log.exception("bg recovery failed")
    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("bg scheduler tick error")
        await asyncio.sleep(2.0)


def start() -> asyncio.Task:
    global _task, _started
    if _task and not _task.done():
        return _task
    ha_events.start_listener()
    _task = asyncio.create_task(_loop(), name="bg-scheduler")
    _started = True
    return _task


async def stop() -> None:
    global _task
    if _task:
        _task.cancel()
        try:
            await _task
        except Exception:
            pass
        _task = None
    await ha_events.stop_listener()
