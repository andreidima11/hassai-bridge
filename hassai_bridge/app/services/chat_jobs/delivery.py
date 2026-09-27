"""Finalize chat jobs into conversation placeholders + HA private notify."""

from __future__ import annotations

import logging
import time

from core.config import load_config
from core.database import update_conversation_message
from services.chat_jobs import manager, store

log = logging.getLogger("hassai.chat_jobs.delivery")


def _delivery_id(job_id: str, kind: str = "result") -> str:
    return f"cjdl_{job_id}_{kind}"


def ensure_placeholder(
    *,
    owner_id: str,
    session_id: str,
    job_id: str,
) -> int | None:
    """Insert empty assistant row tagged with chat_job_id. Returns message id."""
    from core.database import add_conversation_message

    meta = {
        "chat_job_id": job_id,
        "chat_job": {"status": "running", "job_id": job_id},
    }
    msg_id = add_conversation_message(
        owner_id,
        "assistant",
        "",
        session_id=session_id,
        meta=meta,
        return_id=True,
    )
    if msg_id:
        store.update_job(job_id, assistant_message_id=int(msg_id))
    return int(msg_id) if msg_id else None


def finalize_assistant(
    job: dict,
    *,
    content: str,
    meta: dict | None = None,
    status: str = "completed",
) -> None:
    """Update the placeholder assistant message (or insert if missing)."""
    job_id = str(job.get("job_id") or "")
    owner_id = str(job.get("owner_id") or "")
    session_id = str(job.get("session_id") or "")
    msg_id = job.get("assistant_message_id")
    merged_meta = dict(meta or {})
    merged_meta["chat_job_id"] = job_id
    merged_meta["chat_job"] = {
        "status": status,
        "job_id": job_id,
        "done": status in store.TERMINAL_STATUSES,
    }
    text = str(content or "")
    if msg_id:
        ok = update_conversation_message(int(msg_id), content=text, meta=merged_meta)
        if ok:
            return
    # Fallback insert (placeholder lost)
    from core.database import add_conversation_message

    add_conversation_message(
        owner_id, "assistant", text, session_id=session_id, meta=merged_meta
    )


async def enqueue_result(job_id: str, *, content: str = "", meta: dict | None = None) -> None:
    job = store.get_job(job_id)
    if not job:
        return
    did = _delivery_id(job_id, "result")
    existing = store.get_delivery(did)
    if existing and existing.get("status") == "delivered":
        return
    store.upsert_delivery(
        did,
        job_id=job_id,
        kind="result",
        status="pending",
        payload={"content": content, "meta": meta or {}},
    )
    await try_deliver(did)


async def try_deliver(delivery_id: str) -> bool:
    row = store.get_delivery(delivery_id)
    if not row or row.get("status") == "delivered":
        return bool(row and row.get("status") == "delivered")
    job = store.get_job(str(row.get("job_id") or ""))
    if not job:
        store.upsert_delivery(
            delivery_id,
            job_id=str(row.get("job_id") or ""),
            kind=str(row.get("kind") or "result"),
            status="failed",
            payload=row.get("payload") or {},
            attempts=int(row.get("attempts") or 0) + 1,
            last_error="job_missing",
        )
        return False

    payload = row.get("payload") or {}
    content = str(payload.get("content") or "")
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    status = str(job.get("status") or "completed")

    # Use progress preview if content empty
    if not content.strip():
        content = str((job.get("progress") or {}).get("assistant_preview") or "")
    if status == "failed" and not content.strip():
        err = job.get("error") or {}
        content = str(err.get("message") or err.get("reason") or "Job failed.")
    if status == "cancelled" and not content.strip():
        content = content or ""  # keep partial preview if any

    try:
        finalize_assistant(job, content=content, meta=meta, status=status)
        store.upsert_delivery(
            delivery_id,
            job_id=job["job_id"],
            kind=str(row.get("kind") or "result"),
            status="delivered",
            payload=payload,
            attempts=int(row.get("attempts") or 0) + 1,
            last_error="",
        )
    except Exception as exc:
        log.exception("chat job delivery failed %s", delivery_id)
        store.upsert_delivery(
            delivery_id,
            job_id=job["job_id"],
            kind=str(row.get("kind") or "result"),
            status="pending",
            payload=payload,
            attempts=int(row.get("attempts") or 0) + 1,
            last_error=str(exc)[:300],
        )
        return False

    # Private HA notify (best-effort, never blocks delivery)
    try:
        await _maybe_notify(job, content=content)
    except Exception:
        log.debug("chat job notify failed", exc_info=True)
    return True


async def retry_pending(limit: int = 5) -> None:
    for row in store.list_pending_deliveries(limit=limit):
        attempts = int(row.get("attempts") or 0)
        if attempts >= 20:
            store.upsert_delivery(
                row["delivery_id"],
                job_id=row["job_id"],
                kind=row.get("kind") or "result",
                status="failed",
                payload=row.get("payload") or {},
                attempts=attempts,
                last_error=row.get("last_error") or "max_attempts",
            )
            continue
        await try_deliver(row["delivery_id"])


def build_chat_url(session_id: str, *, cfg: dict | None = None, job_id: str = "") -> str:
    cfg = cfg or load_config()
    cj = manager._cj_cfg(cfg)
    base = cj.get("public_base_url") or ""
    sid = str(session_id or "").strip()
    q = f"session={sid}"
    if job_id:
        q += f"&job={job_id}"
    if base:
        return f"{base}/?{q}"
    return f"/?{q}"


async def _maybe_notify(job: dict, *, content: str) -> None:
    cfg = load_config()
    cj = manager._cj_cfg(cfg)
    scope = job.get("permission_scope") or {}
    if scope.get("notify_on_complete") is False or not cj["notify_on_complete"]:
        return
    if job.get("status") not in ("completed", "failed"):
        return
    # Dedup notify via separate delivery kind
    nid = _delivery_id(job["job_id"], "notify")
    existing = store.get_delivery(nid)
    if existing and existing.get("status") == "delivered":
        return

    from services.chat_jobs import notify as cj_notify

    service = await cj_notify.resolve_private_notify(
        str(job.get("owner_id") or ""),
        cfg=cfg,
        preferred=str(scope.get("notify_service") or ""),
        ha_id=str(scope.get("ha_id") or ""),
    )
    if not service:
        store.upsert_delivery(
            nid,
            job_id=job["job_id"],
            kind="notify",
            status="delivered",
            payload={"skipped": True, "reason": "no_private_target"},
        )
        log.info(
            "chat job notify skipped job=%s owner=%s reason=no_private_target",
            job.get("job_id"),
            job.get("owner_id"),
        )
        return

    preview = " ".join(str(content or "").split())
    if len(preview) > 160:
        preview = preview[:157] + "…"
    title = "HASSAI"
    if job.get("status") == "failed":
        title = "HASSAI — eroare"
        if not preview:
            preview = "Răspunsul nu a putut fi generat."
    elif not preview:
        preview = "Răspunsul este gata."

    url = build_chat_url(
        str(job.get("session_id") or ""),
        cfg=cfg,
        job_id=str(job.get("job_id") or ""),
    )
    ok = await cj_notify.send_private_notify(
        service,
        title=title,
        message=preview,
        url=url,
        tag=f"hassai_chat_{job.get('job_id')}",
    )
    store.upsert_delivery(
        nid,
        job_id=job["job_id"],
        kind="notify",
        status="delivered" if ok else "pending",
        payload={"service": service, "url": url},
        attempts=1,
        last_error="" if ok else "notify_failed",
    )
