"""Summarize and finish monitor / wait tasks; lease-aware worker steps."""

from __future__ import annotations

import logging
import socket
import time
from typing import Any

from core.config import load_config
from services.background_tasks import manager, store
from services.background_tasks import ha_events

log = logging.getLogger("hassai.bg_worker")

_WORKER_ID = f"{socket.gethostname()}-{id(object())}"


def _unavailable(state: str) -> bool:
    return str(state or "").lower() in {"unavailable", "unknown", ""}


def summarize_monitor(task: dict) -> dict:
    spec = task.get("spec") or {}
    entity_ids = list(spec.get("entity_ids") or [])
    interest = set(str(s).lower() for s in (spec.get("states_of_interest") or []))
    obs = store.list_observations(task["task_id"], limit=5000)
    events = store.list_events(task["task_id"], limit=500)
    gaps = []
    for ev in events:
        if ev.get("event_type") == "gap_end":
            detail = ev.get("detail") or {}
            gaps.append({
                "seconds": float(detail.get("gap_seconds") or 0),
                "from": detail.get("from"),
                "to": detail.get("to"),
            })
    progress = task.get("progress") or {}
    if progress.get("coverage_gaps"):
        gaps = list(progress.get("coverage_gaps") or []) + gaps

    unavailable_intervals = 0
    unavailable_seconds = 0.0
    last_by_entity: dict[str, str] = {}
    last_ts_by_entity: dict[str, float] = {}
    interesting_hits = 0
    prev_state: dict[str, str] = {}
    prev_ts: dict[str, float] = {}

    started = float(task.get("started_at") or task.get("created_at") or time.time())
    ended = time.time()
    deadline = float(task.get("deadline_at") or ended)
    observed_until = min(ended, deadline)
    observed_seconds = max(0.0, observed_until - started)

    for row in obs:
        eid = row.get("entity_id") or ""
        new_state = str(row.get("new_state") or "")
        ts = float(row.get("ts") or 0)
        old = prev_state.get(eid)
        if old is not None and _unavailable(old) and not _unavailable(new_state):
            # closed an unavailable stretch
            pass
        if old is not None and not _unavailable(old) and _unavailable(new_state):
            unavailable_intervals += 1
        if old is not None and _unavailable(old):
            unavailable_seconds += max(0.0, ts - float(prev_ts.get(eid) or ts))
        if interest and new_state.lower() in interest:
            interesting_hits += 1
        prev_state[eid] = new_state
        prev_ts[eid] = ts
        last_by_entity[eid] = new_state
        last_ts_by_entity[eid] = ts

    # trailing unavailable until end
    for eid, st in prev_state.items():
        if _unavailable(st):
            unavailable_seconds += max(0.0, observed_until - float(prev_ts.get(eid) or observed_until))

    total_gap = float(progress.get("total_gap_seconds") or 0)
    if not total_gap and gaps:
        total_gap = sum(float(g.get("seconds") or 0) for g in gaps)

    return {
        "kind": "monitor_entities",
        "entity_ids": entity_ids,
        "observed_seconds": round(observed_seconds, 1),
        "observation_count": len(obs),
        "coverage_gaps": gaps[-20:],
        "total_gap_seconds": round(total_gap, 1),
        "unavailable_intervals": unavailable_intervals,
        "total_unavailable_seconds": round(unavailable_seconds, 1),
        "interesting_hits": interesting_hits,
        "last_observed_state": last_by_entity,
        "note": (
            "Lack of observations does not mean lack of problems."
            if total_gap > 0 or unavailable_intervals
            else ""
        ),
    }


def format_monitor_message(task: dict, result: dict, *, lang: str | None = None) -> str:
    from services.background_tasks import i18n as bg_i18n

    lang = lang or bg_i18n.lang_from_cfg()
    title = task.get("title") or bg_i18n.t(lang, "fallback_title")
    gaps = result.get("total_gap_seconds") or 0
    lines = [
        bg_i18n.t(lang, "monitor_done", title=title),
        bg_i18n.t(lang, "monitor_watched", entities=", ".join(result.get("entity_ids") or [])),
        bg_i18n.t(
            lang,
            "monitor_observed",
            seconds=result.get("observed_seconds"),
            count=result.get("observation_count"),
        ),
        bg_i18n.t(
            lang,
            "monitor_unavail",
            intervals=result.get("unavailable_intervals"),
            seconds=result.get("total_unavailable_seconds"),
        ),
    ]
    if gaps:
        lines.append(bg_i18n.t(lang, "monitor_gaps", gaps=gaps))
    last = result.get("last_observed_state") or {}
    if last:
        bits = [f"{k}={v}" for k, v in list(last.items())[:8]]
        lines.append(bg_i18n.t(lang, "monitor_last", states=", ".join(bits)))
    return "\n".join(lines)


def format_wait_message(task: dict, result: dict, *, lang: str | None = None) -> str:
    from services.background_tasks import i18n as bg_i18n

    lang = lang or bg_i18n.lang_from_cfg()
    title = task.get("title") or bg_i18n.t(lang, "fallback_title")
    if result.get("matched"):
        return bg_i18n.t(
            lang,
            "wait_matched",
            title=title,
            entity_id=result.get("entity_id"),
            state=result.get("state"),
            seconds=result.get("waited_seconds"),
        )
    return bg_i18n.t(
        lang,
        "wait_timeout",
        title=title,
        seconds=result.get("waited_seconds"),
        entity_id=result.get("entity_id"),
        state=result.get("state"),
        last=result.get("last_state") or "—",
    )


def format_remind_message(task: dict, result: dict | None = None, *, lang: str | None = None) -> str:
    from services.background_tasks import i18n as bg_i18n

    lang = lang or bg_i18n.lang_from_cfg()
    title = task.get("title") or bg_i18n.t(lang, "fallback_title")
    result = result if isinstance(result, dict) else {}
    message = str(result.get("message") or (task.get("spec") or {}).get("message") or "").strip()
    return bg_i18n.t(lang, "remind_done", title=title, message=message or "—")


async def _current_state(entity_id: str) -> str | None:
    try:
        from services import homeassistant as ha

        st = await ha._core("GET", f"/states/{entity_id}")
        if isinstance(st, dict):
            return str(st.get("state") or "")
    except Exception as exc:
        log.debug("state fetch failed %s: %s", entity_id, exc)
    return None


async def process_task(task: dict) -> None:
    tid = task["task_id"]
    cfg = load_config()
    bg = manager._bg_cfg(cfg)
    if not store.try_acquire_lease(tid, _WORKER_ID, bg["worker_lease_seconds"]):
        return

    try:
        task = store.get_task(tid) or task
        if task.get("cancel_requested_at"):
            await _finish_cancelled(task)
            return

        ok, reason = manager.permissions_still_ok(
            task.get("permission_scope") or {},
            cfg,
            task.get("session_id"),
            kind=task.get("kind"),
        )
        if not ok:
            store.update_task(
                tid,
                status="blocked",
                error={"code": "approval_required", "reason": reason},
                next_run_at=time.time() + 30,
            )
            store.add_event(tid, "blocked", {"reason": reason})
            from services.background_tasks import delivery

            await delivery.notify_blocked(tid)
            return

        if task.get("status") == "scheduled":
            store.update_task(tid, status="running", started_at=time.time())
            store.add_event(tid, "started", {})
            ha_events.refresh_watch_index()
            task = store.get_task(tid) or task

        kind = task.get("kind")
        now = time.time()
        deadline = float(task.get("deadline_at") or now)

        if kind == "wait_for_state":
            await _step_wait(task, now, deadline)
        elif kind == "monitor_entities":
            await _step_monitor(task, now, deadline)
        elif kind == "remind_me":
            await _step_remind(task, now, deadline)
        else:
            store.update_task(
                tid,
                status="failed",
                error={"code": "unsupported_kind", "reason": kind},
            )
            store.add_event(tid, "failed", {"reason": "unsupported_kind"})
            from services.background_tasks import delivery

            await delivery.enqueue_result(tid)
    except Exception as exc:
        log.exception("process_task %s failed", tid)
        store.update_task(
            tid,
            status="failed",
            error={"code": "worker_error", "reason": str(exc)},
        )
        store.add_event(tid, "failed", {"reason": str(exc)})
        from services.background_tasks import delivery

        await delivery.enqueue_result(tid)
    finally:
        store.release_lease(tid, _WORKER_ID)
        ha_events.refresh_watch_index()


async def _finish_cancelled(task: dict) -> None:
    from services.background_tasks import delivery

    tid = task["task_id"]
    partial = None
    if task.get("kind") == "monitor_entities":
        partial = summarize_monitor(task)
    store.update_task(
        tid,
        status="cancelled",
        result=partial,
        error={"code": "cancelled", "reason": "user cancelled"},
        next_run_at=None,
    )
    store.add_event(tid, "cancelled", {})
    await delivery.enqueue_result(tid)


async def _step_wait(task: dict, now: float, deadline: float) -> None:
    from services.background_tasks import delivery

    tid = task["task_id"]
    spec = task.get("spec") or {}
    entity_id = str(spec.get("entity_id") or "")
    want = str(spec.get("state") or "")
    stable_for = float(spec.get("stable_for_seconds") or 0)
    accept_already = bool(spec.get("accept_already_true"))
    started = float(task.get("started_at") or task.get("created_at") or now)

    # Prefer latest observation; fall back to live fetch
    obs = store.list_observations(tid, limit=5000)
    last_state = None
    matched_at = None
    for row in obs:
        if row.get("entity_id") != entity_id:
            continue
        last_state = str(row.get("new_state") or "")
        if last_state == want:
            # transition check
            if not accept_already:
                old = str(row.get("old_state") or "")
                if old == want:
                    continue
            matched_at = float(row.get("ts") or now)

    if last_state is None:
        live = await _current_state(entity_id)
        last_state = live
        if live == want and accept_already:
            matched_at = now
        elif live == want and not accept_already:
            # Need a transition — seed baseline without matching
            store.add_observation(
                tid, entity_id=entity_id, old_state="", new_state=live or "", ts=now,
            )

    if matched_at is not None:
        if stable_for > 0 and (now - matched_at) < stable_for:
            store.update_task(
                tid,
                progress={
                    "phase": "stabilizing",
                    "last_state": last_state,
                    "matched_at": matched_at,
                },
                next_run_at=matched_at + stable_for,
            )
            return
        result = {
            "kind": "wait_for_state",
            "matched": True,
            "entity_id": entity_id,
            "state": want,
            "last_state": last_state,
            "waited_seconds": round(max(0.0, (matched_at or now) - started), 1),
            "timed_out": False,
        }
        store.update_task(tid, status="completed", result=result, progress={"phase": "done"})
        store.add_event(tid, "completed", {"matched": True})
        await delivery.enqueue_result(tid)
        return

    if now >= deadline:
        result = {
            "kind": "wait_for_state",
            "matched": False,
            "entity_id": entity_id,
            "state": want,
            "last_state": last_state,
            "waited_seconds": round(max(0.0, deadline - started), 1),
            "timed_out": True,
        }
        store.update_task(tid, status="completed", result=result, progress={"phase": "timeout"})
        store.add_event(tid, "completed", {"timed_out": True})
        await delivery.enqueue_result(tid)
        return

    store.update_task(
        tid,
        progress={"phase": "waiting", "last_state": last_state},
        next_run_at=min(now + 5.0, deadline),
    )


async def _step_monitor(task: dict, now: float, deadline: float) -> None:
    from services.background_tasks import delivery

    tid = task["task_id"]
    # Soft progress heartbeat
    obs_n = len(store.list_observations(tid, limit=5000))
    store.update_task(
        tid,
        progress={
            **(task.get("progress") or {}),
            "phase": "monitoring",
            "observation_count": obs_n,
            "seconds_left": max(0.0, deadline - now),
        },
    )
    if now < deadline:
        store.update_task(tid, next_run_at=min(now + 15.0, deadline))
        return
    result = summarize_monitor(task)
    store.update_task(tid, status="completed", result=result, progress={"phase": "done"})
    store.add_event(tid, "completed", {"observation_count": result.get("observation_count")})
    await delivery.enqueue_result(tid)


def remind_result(task: dict) -> dict:
    spec = task.get("spec") or {}
    return {
        "kind": "remind_me",
        "message": str(spec.get("message") or "").strip(),
        "delay_seconds": float(spec.get("delay_seconds") or 0),
    }


async def _step_remind(task: dict, now: float, deadline: float) -> None:
    from services.background_tasks import delivery

    tid = task["task_id"]
    if now < deadline:
        store.update_task(
            tid,
            progress={
                "phase": "waiting",
                "seconds_left": max(0.0, deadline - now),
            },
            next_run_at=deadline,
        )
        return
    result = remind_result(task)
    store.update_task(tid, status="completed", result=result, progress={"phase": "done"})
    store.add_event(tid, "completed", {"remind": True})
    await delivery.enqueue_result(tid)
