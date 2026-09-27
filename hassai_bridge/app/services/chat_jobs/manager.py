"""Chat job manager — create, cancel, public views, config."""

from __future__ import annotations

import logging
import time
from typing import Any

from core.config import load_config
from core.identity import get_profile
from services.chat_jobs import store

log = logging.getLogger("hassai.chat_jobs")


def _cj_cfg(cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    raw = dict(cfg.get("chat_jobs") or {})
    bg = dict(cfg.get("background_tasks") or {})
    return {
        "enabled": raw.get("enabled", True) is not False,
        "max_job_seconds": max(60, min(int(raw.get("max_job_seconds") or 1800), 7200)),
        "worker_lease_seconds": max(15, min(int(raw.get("worker_lease_seconds") or 60), 300)),
        "max_concurrent": max(1, min(int(raw.get("max_concurrent") or 3), 8)),
        "max_result_days": max(1, min(int(raw.get("max_result_days") or 30), 365)),
        "notify_on_complete": (
            raw.get("notify_on_complete")
            if "notify_on_complete" in raw
            else bg.get("notify_on_complete", True)
        ) is not False,
        "public_base_url": str(raw.get("public_base_url") or "").strip().rstrip("/"),
        "feed_poll_seconds": max(1, min(int(raw.get("feed_poll_seconds") or 2), 30)),
    }


def snapshot_notify_scope(owner_id: str, *, cfg: dict | None = None) -> dict:
    """Pin identity + preferred notify at job create (no sole-phone guess)."""
    cfg = cfg or load_config()
    prof = get_profile(owner_id) or {}
    ha_id = str(prof.get("ha_id") or "").strip()
    notify_service = str(prof.get("notify_service") or "").strip()
    return {
        "ha_id": ha_id,
        "display_name": str(prof.get("display_name") or owner_id),
        "notify_service": notify_service,
        "notify_on_complete": _cj_cfg(cfg)["notify_on_complete"],
    }


def public_job(job: dict | None) -> dict | None:
    if not job:
        return None
    return {
        "job_id": job.get("job_id"),
        "trace_id": job.get("job_id"),
        "session_id": job.get("session_id"),
        "status": job.get("status"),
        "created_at": job.get("created_at"),
        "started_at": job.get("started_at"),
        "deadline_at": job.get("deadline_at"),
        "updated_at": job.get("updated_at"),
        "cancel_requested_at": job.get("cancel_requested_at"),
        "progress": job.get("progress") or {},
        "result": job.get("result"),
        "error": job.get("error"),
        "feed_seq": job.get("feed_seq") or 0,
        "done": job.get("status") in store.TERMINAL_STATUSES,
        "cancelled": job.get("status") == "cancelled" or bool(job.get("cancel_requested_at")),
    }


def create_job(
    *,
    job_id: str,
    owner_id: str,
    session_id: str,
    spec: dict | None = None,
    assistant_message_id: int | None = None,
    cfg: dict | None = None,
) -> dict:
    cfg = cfg or load_config()
    cj = _cj_cfg(cfg)
    now = time.time()
    deadline = now + float(cj["max_job_seconds"])
    scope = snapshot_notify_scope(owner_id, cfg=cfg)
    existing = store.get_job(job_id)
    if existing:
        return existing
    return store.insert_job(
        job_id=job_id,
        owner_id=owner_id,
        session_id=session_id or "",
        spec=spec or {},
        status="queued",
        deadline_at=deadline,
        permission_scope=scope,
        progress={"phase": "queued", "assistant_preview": ""},
        assistant_message_id=assistant_message_id,
    )


def get_job(job_id: str, *, owner_id: str | None = None) -> dict | None:
    if owner_id:
        return store.get_job_for_owner(job_id, owner_id)
    return store.get_job(job_id)


def cancel_job(job_id: str, *, owner_id: str) -> dict:
    job = store.get_job_for_owner(job_id, owner_id)
    if not job:
        return {"ok": False, "error": "not_found"}
    store.request_cancel(job_id)
    return {"ok": True, "job": public_job(store.get_job(job_id))}


def feed(session_id: str, after_seq: int = 0, *, owner_id: str) -> dict:
    raw = store.feed_since(session_id, after_seq, owner_id=owner_id)
    return {
        "jobs": [public_job(j) for j in raw.get("jobs") or []],
        "after": raw.get("after", after_seq),
    }


def activity_payload(job_id: str, *, owner_id: str | None, after: int = -1) -> dict | None:
    job = store.get_job(job_id)
    if not job:
        return None
    if owner_id and str(job.get("owner_id") or "") != str(owner_id):
        return None
    events = store.list_events(job_id, after=after)
    last = after
    if events:
        last = int(events[-1].get("i", after))
    status = job.get("status") or "unknown"
    done = status in store.TERMINAL_STATUSES
    cancelled = status == "cancelled"
    err = ""
    if isinstance(job.get("error"), dict):
        err = str(job["error"].get("message") or job["error"].get("reason") or "")
    elif job.get("error"):
        err = str(job.get("error"))
    return {
        "events": events,
        "after": last,
        "done": done,
        "cancelled": cancelled,
        "status": (
            "cancelled" if cancelled
            else ("error" if status == "failed" else ("done" if done else status))
        ),
        "session_id": job.get("session_id") or "",
        "error": err,
        "model": str((job.get("spec") or {}).get("model") or ""),
        "provider": str((job.get("spec") or {}).get("provider") or ""),
        "progress": job.get("progress") or {},
        "job": public_job(job),
    }


def mark_running(job_id: str) -> None:
    store.update_job(job_id, status="running", started_at=time.time(), next_run_at=time.time())


def mark_blocked(job_id: str, reason: str) -> None:
    store.update_job(
        job_id,
        status="blocked",
        error={"code": "blocked", "reason": reason},
        next_run_at=None,
    )


def mark_completed(job_id: str, *, result: dict | None = None, progress: dict | None = None) -> None:
    fields: dict[str, Any] = {
        "status": "completed",
        "result": result or {},
        "lease_owner": "",
        "lease_until": None,
    }
    if progress is not None:
        fields["progress"] = progress
    store.update_job(job_id, **fields)


def mark_failed(job_id: str, *, message: str, code: str = "error") -> None:
    store.update_job(
        job_id,
        status="failed",
        error={"code": code, "message": str(message or "")[:500], "reason": str(message or "")[:500]},
        lease_owner="",
        lease_until=None,
    )


def mark_cancelled(job_id: str) -> None:
    store.update_job(
        job_id,
        status="cancelled",
        lease_owner="",
        lease_until=None,
    )
