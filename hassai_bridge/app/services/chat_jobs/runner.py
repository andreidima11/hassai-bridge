"""Claim and finish durable chat jobs after restart / timeout / cancel."""

from __future__ import annotations

import logging
import time

from services.chat_jobs import delivery, manager, store

log = logging.getLogger("hassai.chat_jobs.runner")

_INTERRUPT_MSG = {
    "en": "Generation was interrupted when the add-on restarted. Please send the question again.",
    "ro": "Generarea a fost întreruptă la restartul add-on-ului. Te rog trimite din nou întrebarea.",
}


def _lang() -> str:
    try:
        from core.config import load_config

        return str((load_config() or {}).get("language") or "en").lower()[:2]
    except Exception:
        return "en"


def interrupt_message() -> str:
    lang = _lang()
    return _INTERRUPT_MSG.get(lang) or _INTERRUPT_MSG["en"]


async def recover_on_boot() -> None:
    """After add-on restart: cancel orphaned running LLM turns cleanly.

    Re-executing mid-tool is unsafe without full checkpoints; we mark failed,
    update the placeholder, and notify so the UI never stays on «Gândește».
    Queued jobs with cancel stay cancelled; deadline-expired fail as timeout.
    """
    now = time.time()
    for job in store.list_recoverable():
        jid = job["job_id"]
        store.update_job(jid, lease_owner="", lease_until=None)

        if job.get("cancel_requested_at"):
            manager.mark_cancelled(jid)
            await delivery.enqueue_result(
                jid,
                content=str((job.get("progress") or {}).get("assistant_preview") or ""),
                meta={},
            )
            continue

        deadline = float(job.get("deadline_at") or 0)
        if deadline and now >= deadline:
            msg = "Job timed out." if _lang() != "ro" else "Job-ul a expirat."
            manager.mark_failed(jid, message=msg, code="timeout")
            store.append_event(jid, {
                "id": "assistant-out",
                "name": "assistant",
                "detail": msg,
                "status": "done",
            })
            await delivery.enqueue_result(jid, content=msg, meta={})
            continue

        status = job.get("status") or "queued"
        if status == "blocked":
            # Keep blocked — user must approve; bump feed so UI sees it
            store.touch_feed(jid)
            continue

        # running/queued mid-flight: fail cleanly (no unsafe tool replay)
        msg = interrupt_message()
        manager.mark_failed(jid, message=msg, code="interrupted")
        store.append_event(jid, {
            "id": "assistant-out",
            "name": "assistant",
            "detail": msg,
            "status": "done",
        })
        await delivery.enqueue_result(jid, content=msg, meta={})
        log.info("chat job recovered as interrupted job=%s", jid)

    log.info("chat jobs recovery done")


async def process_due_jobs() -> None:
    """Handle cancel flags / deadlines on claimable jobs (no LLM re-entry yet).

    Live turns still run via asyncio.create_task in chat.py; this tick finishes
    jobs that were cancelled or timed out while the in-process task died.
    """
    cfg_lease = manager._cj_cfg()["worker_lease_seconds"]
    for job in store.list_claimable(limit=manager._cj_cfg()["max_concurrent"]):
        jid = job["job_id"]
        worker_id = f"cj-{int(time.time())}"
        if not store.try_acquire_lease(jid, worker_id, cfg_lease):
            continue
        try:
            fresh = store.get_job(jid) or job
            if fresh.get("status") in store.TERMINAL_STATUSES:
                continue
            if fresh.get("cancel_requested_at"):
                preview = str((fresh.get("progress") or {}).get("assistant_preview") or "")
                manager.mark_cancelled(jid)
                store.append_event(jid, {
                    "id": "assistant-out",
                    "name": "assistant",
                    "detail": preview,
                    "status": "done",
                })
                await delivery.enqueue_result(jid, content=preview, meta={})
                continue
            deadline = float(fresh.get("deadline_at") or 0)
            if deadline and time.time() >= deadline:
                msg = "Job timed out." if _lang() != "ro" else "Job-ul a expirat."
                manager.mark_failed(jid, message=msg, code="timeout")
                store.append_event(jid, {
                    "id": "assistant-out",
                    "name": "assistant",
                    "detail": msg,
                    "status": "done",
                })
                await delivery.enqueue_result(jid, content=msg, meta={})
                continue
            # Still running in-process — renew lease lightly by releasing
        finally:
            store.release_lease(jid, worker_id)


def record_tool_fingerprint(job_id: str, fingerprint: str, result: str) -> None:
    """Persist tool call result so a future resume can skip re-execution."""
    job = store.get_job(job_id)
    if not job:
        return
    spec = dict(job.get("spec") or {})
    fps = dict(spec.get("tool_fingerprints") or {})
    if fingerprint and fingerprint not in fps:
        fps[fingerprint] = {"result": str(result or "")[:8000], "ts": time.time()}
        spec["tool_fingerprints"] = fps
        store.update_job(job_id, spec=spec)


def tool_fingerprint_hit(job_id: str, fingerprint: str) -> str | None:
    job = store.get_job(job_id)
    if not job or not fingerprint:
        return None
    fps = (job.get("spec") or {}).get("tool_fingerprints") or {}
    hit = fps.get(fingerprint)
    if isinstance(hit, dict):
        return hit.get("result")
    return None
