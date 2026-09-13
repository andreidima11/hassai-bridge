"""Long-lived Home Assistant state_changed subscription."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from services.background_tasks import store

log = logging.getLogger("hassai.bg_ha_events")

_listener_task: asyncio.Task | None = None
_connected = False
_gap_open_at: float | None = None
_watched: dict[str, set[str]] = {}  # entity_id → set(task_id)


def is_connected() -> bool:
    return _connected


def refresh_watch_index() -> None:
    """Rebuild entity → tasks map from active tasks."""
    global _watched
    mapping: dict[str, set[str]] = {}
    for task in store.list_active_for_entities():
        tid = str(task.get("task_id") or "")
        spec = task.get("spec") or {}
        kind = task.get("kind")
        ids: list[str] = []
        if kind == "monitor_entities":
            ids = list(spec.get("entity_ids") or [])
        elif kind == "wait_for_state":
            eid = str(spec.get("entity_id") or "").strip()
            if eid:
                ids = [eid]
        for eid in ids:
            mapping.setdefault(eid, set()).add(tid)
    _watched = mapping


def _open_gaps(reason: str) -> None:
    global _gap_open_at
    if _gap_open_at is not None:
        return
    _gap_open_at = time.time()
    for task in store.list_active_for_entities():
        store.add_event(
            task["task_id"],
            "gap_start",
            {"reason": reason, "ts": _gap_open_at},
        )


def _close_gaps() -> None:
    global _gap_open_at
    if _gap_open_at is None:
        return
    ended = time.time()
    duration = max(0.0, ended - _gap_open_at)
    for task in store.list_active_for_entities():
        store.add_event(
            task["task_id"],
            "gap_end",
            {"reason": "reconnected", "gap_seconds": duration, "from": _gap_open_at, "to": ended},
        )
        progress = dict(task.get("progress") or {})
        gaps = list(progress.get("coverage_gaps") or [])
        gaps.append({"from": _gap_open_at, "to": ended, "seconds": duration})
        progress["coverage_gaps"] = gaps[-50:]
        progress["total_gap_seconds"] = float(progress.get("total_gap_seconds") or 0) + duration
        store.update_task(task["task_id"], progress=progress)
    _gap_open_at = None


def _handle_state_changed(event: dict) -> None:
    data = event.get("data") or {}
    entity_id = str(data.get("entity_id") or "").strip()
    if not entity_id:
        return
    task_ids = _watched.get(entity_id) or set()
    if not task_ids:
        return
    old = data.get("old_state") or {}
    new = data.get("new_state") or {}
    old_state = str((old.get("state") if isinstance(old, dict) else "") or "")
    new_state = str((new.get("state") if isinstance(new, dict) else "") or "")
    ts = time.time()
    try:
        # HA event time is usually ms epoch in context, but we use local receive time
        ctx = event.get("time_fired")
        if isinstance(ctx, str) and ctx:
            # leave as receive time; ISO parsing optional
            pass
    except Exception:
        pass
    for tid in list(task_ids):
        store.add_observation(
            tid,
            entity_id=entity_id,
            old_state=old_state,
            new_state=new_state,
            payload={"attributes": (new.get("attributes") if isinstance(new, dict) else {})},
            ts=ts,
        )
        # Nudge wait_for_state / monitors to run soon
        store.update_task(tid, next_run_at=time.time())


async def _run_loop() -> None:
    global _connected
    token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
    if not token:
        log.warning("background HA listener: no SUPERVISOR_TOKEN — disabled")
        return
    url = os.environ.get("HASSAI_HA_WS", "ws://supervisor/core/websocket")
    try:
        from websockets.asyncio.client import connect as ws_connect
    except ImportError:
        from websockets import connect as ws_connect  # type: ignore

    backoff = 1.0
    while True:
        try:
            refresh_watch_index()
            async with ws_connect(url, open_timeout=10, close_timeout=5, ping_interval=20) as ws:
                hello = json.loads(await ws.recv())
                if hello.get("type") != "auth_required":
                    raise RuntimeError(f"unexpected hello: {hello.get('type')}")
                await ws.send(json.dumps({"type": "auth", "access_token": token}))
                auth = json.loads(await ws.recv())
                if auth.get("type") != "auth_ok":
                    raise RuntimeError(f"auth failed: {auth}")
                msg_id = 1
                await ws.send(json.dumps({
                    "id": msg_id,
                    "type": "subscribe_events",
                    "event_type": "state_changed",
                }))
                # Wait for success result
                while True:
                    data = json.loads(await ws.recv())
                    if data.get("type") == "result" and data.get("id") == msg_id:
                        if not data.get("success"):
                            raise RuntimeError(f"subscribe failed: {data.get('error')}")
                        break
                _connected = True
                backoff = 1.0
                _close_gaps()
                log.info("HA state_changed listener connected")
                refresh_watch_index()
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("type") != "event":
                        continue
                    ev = data.get("event") or {}
                    if ev.get("event_type") != "state_changed":
                        continue
                    try:
                        _handle_state_changed(ev)
                    except Exception:
                        log.exception("state_changed handler failed")
        except asyncio.CancelledError:
            _connected = False
            raise
        except Exception as exc:
            _connected = False
            log.warning("HA listener disconnected: %s", exc)
            _open_gaps(str(exc))
            await asyncio.sleep(backoff)
            backoff = min(60.0, backoff * 1.7)


def start_listener() -> asyncio.Task | None:
    global _listener_task
    if _listener_task and not _listener_task.done():
        return _listener_task
    _listener_task = asyncio.create_task(_run_loop(), name="bg-ha-events")
    return _listener_task


async def stop_listener() -> None:
    global _listener_task
    if _listener_task:
        _listener_task.cancel()
        try:
            await _listener_task
        except Exception:
            pass
        _listener_task = None
