"""Mirror chat activity events into durable chat_job_events + in-memory traces."""

from __future__ import annotations

import logging
from typing import Any

from services.chat_jobs import store

log = logging.getLogger("hassai.chat_jobs.activity")


def push_event(job_id: str, event: dict) -> dict:
    """Persist event and return payload with durable seq as `i`."""
    if not job_id:
        return dict(event or {})
    try:
        seq = store.append_event(job_id, event)
    except Exception:
        log.debug("chat job event persist failed", exc_info=True)
        return dict(event or {})
    out = dict(event or {})
    out["i"] = seq
    return out


def hydrate_trace_bucket(job_id: str) -> dict[str, Any] | None:
    """Build an in-memory-like bucket from SQLite for poll clients after restart."""
    job = store.get_job(job_id)
    if not job:
        return None
    events = store.list_events(job_id, after=-1)
    status = job.get("status") or "unknown"
    done = status in store.TERMINAL_STATUSES
    cancelled = status == "cancelled"
    err = ""
    if isinstance(job.get("error"), dict):
        err = str(job["error"].get("message") or job["error"].get("reason") or "")
    return {
        "events": events,
        "done": done,
        "cancelled": cancelled,
        "ts": float(job.get("updated_at") or job.get("created_at") or 0),
        "session_id": job.get("session_id") or "",
        "user_id": job.get("owner_id") or "",
        "status": (
            "cancelled" if cancelled
            else ("error" if status == "failed" else ("done" if done else "running"))
        ),
        "error": err,
        "model": str((job.get("spec") or {}).get("model") or ""),
        "provider": str((job.get("spec") or {}).get("provider") or ""),
        "route": dict((job.get("spec") or {}).get("route") or {}),
    }
