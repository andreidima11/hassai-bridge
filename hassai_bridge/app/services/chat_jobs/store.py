"""Persistent chat job store (SQLite)."""

from __future__ import annotations

import json
import time
from typing import Any

from core.database import get_db

ACTIVE_STATUSES = frozenset({"queued", "running", "blocked"})
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})


def _dumps(obj: Any) -> str:
    if obj is None:
        return ""
    if isinstance(obj, str):
        return obj
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)


def _loads(raw: str | None, default: Any = None) -> Any:
    text = str(raw or "").strip()
    if not text:
        return default if default is not None else {}
    try:
        return json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return default if default is not None else {}


def _row_to_job(row) -> dict:
    d = dict(row)
    d["spec"] = _loads(d.pop("spec_json", None), {})
    d["progress"] = _loads(d.pop("progress_json", None), {})
    d["result"] = _loads(d.pop("result_json", None), None)
    d["error"] = _loads(d.pop("error_json", None), None)
    d["permission_scope"] = _loads(d.pop("permission_scope_json", None), {})
    return d


def bump_feed(conn, job_id: str) -> int:
    now = time.time()
    conn.execute(
        "UPDATE chat_jobs SET feed_seq = feed_seq + 1, updated_at = ? WHERE job_id = ?",
        (now, job_id),
    )
    row = conn.execute(
        "SELECT feed_seq FROM chat_jobs WHERE job_id = ?", (job_id,)
    ).fetchone()
    return int(row["feed_seq"] if row else 0)


def touch_feed(job_id: str) -> int:
    with get_db() as conn:
        return bump_feed(conn, job_id)


def insert_job(
    *,
    job_id: str,
    owner_id: str,
    session_id: str,
    spec: dict | None = None,
    status: str = "queued",
    deadline_at: float | None = None,
    permission_scope: dict | None = None,
    progress: dict | None = None,
    assistant_message_id: int | None = None,
) -> dict:
    import sqlite3

    now = time.time()
    with get_db() as conn:
        # One active job per session — reject if another is active.
        busy = conn.execute(
            """SELECT job_id FROM chat_jobs
               WHERE owner_id = ? AND session_id = ?
                 AND status IN ('queued', 'running', 'blocked')
                 AND job_id != ?
               LIMIT 1""",
            (owner_id, session_id or "", job_id),
        ).fetchone()
        if busy:
            raise JobConflictError(str(busy["job_id"]))

        existing = conn.execute(
            "SELECT * FROM chat_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if existing:
            return _row_to_job(existing)

        try:
            conn.execute(
                """INSERT INTO chat_jobs (
                    job_id, owner_id, session_id, status,
                    created_at, started_at, deadline_at, next_run_at, updated_at,
                    spec_json, progress_json, result_json, error_json,
                    permission_scope_json, idempotency_key,
                    lease_owner, lease_until, cancel_requested_at, feed_seq,
                    assistant_message_id
                ) VALUES (?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, '', '', ?, ?, '', NULL, NULL, 0, ?)""",
                (
                    job_id,
                    owner_id,
                    session_id or "",
                    status,
                    now,
                    deadline_at,
                    now,
                    now,
                    _dumps(spec or {}),
                    _dumps(progress or {}),
                    _dumps(permission_scope or {}),
                    job_id,
                    assistant_message_id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            # Race on partial unique index
            busy2 = conn.execute(
                """SELECT job_id FROM chat_jobs
                   WHERE owner_id = ? AND session_id = ?
                     AND status IN ('queued', 'running', 'blocked')
                   LIMIT 1""",
                (owner_id, session_id or ""),
            ).fetchone()
            if busy2 and str(busy2["job_id"]) != job_id:
                raise JobConflictError(str(busy2["job_id"])) from exc
            existing2 = conn.execute(
                "SELECT * FROM chat_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing2:
                return _row_to_job(existing2)
            raise
        conn.execute(
            "INSERT INTO chat_job_events (job_id, seq, ts, event_json) VALUES (?, ?, ?, ?)",
            (job_id, 0, now, _dumps({"id": "created", "name": "job", "status": status})),
        )
        bump_feed(conn, job_id)
    return get_job(job_id) or {}


class JobConflictError(Exception):
    def __init__(self, busy_job_id: str):
        self.busy_job_id = busy_job_id
        super().__init__(f"session busy: {busy_job_id}")


def get_job(job_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM chat_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
    return _row_to_job(row) if row else None


def get_job_for_owner(job_id: str, owner_id: str) -> dict | None:
    job = get_job(job_id)
    if not job:
        return None
    if str(job.get("owner_id") or "") != str(owner_id or ""):
        return None
    return job


def active_job_for_session(owner_id: str, session_id: str) -> dict | None:
    sid = str(session_id or "").strip()
    if not sid:
        return None
    with get_db() as conn:
        row = conn.execute(
            """SELECT * FROM chat_jobs
               WHERE owner_id = ? AND session_id = ?
                 AND status IN ('queued', 'running', 'blocked')
               ORDER BY created_at DESC LIMIT 1""",
            (owner_id, sid),
        ).fetchone()
    return _row_to_job(row) if row else None


def list_jobs(
    owner_id: str,
    *,
    session_id: str | None = None,
    status_filter: list[str] | None = None,
    limit: int = 20,
) -> list[dict]:
    limit = max(1, min(int(limit or 20), 100))
    clauses = ["owner_id = ?"]
    args: list[Any] = [owner_id]
    if session_id:
        clauses.append("session_id = ?")
        args.append(session_id)
    if status_filter:
        placeholders = ",".join("?" for _ in status_filter)
        clauses.append(f"status IN ({placeholders})")
        args.extend(status_filter)
    args.append(limit)
    sql = (
        f"SELECT * FROM chat_jobs WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC LIMIT ?"
    )
    with get_db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_job(r) for r in rows]


def list_active_by_sessions(owner_id: str, session_ids: list[str]) -> dict[str, dict]:
    """Map session_id → active job for badge rendering."""
    ids = [str(s).strip() for s in session_ids if str(s or "").strip()]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM chat_jobs
                WHERE owner_id = ? AND session_id IN ({placeholders})
                  AND status IN ('queued', 'running', 'blocked')""",
            (owner_id, *ids),
        ).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        job = _row_to_job(row)
        sid = str(job.get("session_id") or "")
        if sid and sid not in out:
            out[sid] = job
    return out


def update_job(job_id: str, **fields) -> dict | None:
    allowed = {
        "status",
        "started_at",
        "deadline_at",
        "next_run_at",
        "progress",
        "result",
        "error",
        "lease_owner",
        "lease_until",
        "cancel_requested_at",
        "assistant_message_id",
        "spec",
        "permission_scope",
    }
    cols: list[str] = []
    args: list[Any] = []
    mapping = {
        "progress": "progress_json",
        "result": "result_json",
        "error": "error_json",
        "spec": "spec_json",
        "permission_scope": "permission_scope_json",
    }
    for key, val in fields.items():
        if key not in allowed:
            continue
        col = mapping.get(key, key)
        if key in mapping:
            val = _dumps(val) if val is not None else ""
        cols.append(f"{col} = ?")
        args.append(val)
    if not cols:
        return get_job(job_id)
    now = time.time()
    cols.append("updated_at = ?")
    args.append(now)
    args.append(job_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE chat_jobs SET {', '.join(cols)} WHERE job_id = ?",
            args,
        )
        bump_feed(conn, job_id)
    return get_job(job_id)


def request_cancel(job_id: str) -> dict | None:
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM chat_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        if not row:
            return None
        if row["status"] in TERMINAL_STATUSES:
            return get_job(job_id)
        conn.execute(
            "UPDATE chat_jobs SET cancel_requested_at = ?, updated_at = ? WHERE job_id = ?",
            (now, now, job_id),
        )
        bump_feed(conn, job_id)
    return get_job(job_id)


def append_event(job_id: str, event: dict) -> int:
    """Append activity event; return event seq (0-based index)."""
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(seq), -1) AS m FROM chat_job_events WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        seq = int(row["m"] if row else -1) + 1
        conn.execute(
            "INSERT INTO chat_job_events (job_id, seq, ts, event_json) VALUES (?, ?, ?, ?)",
            (job_id, seq, now, _dumps(event or {})),
        )
        if (event or {}).get("name") == "assistant":
            detail = str((event or {}).get("detail") or "")
            row_p = conn.execute(
                "SELECT progress_json FROM chat_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            progress = _loads(row_p["progress_json"] if row_p else None, {})
            if not isinstance(progress, dict):
                progress = {}
            progress["assistant_preview"] = detail
            progress["phase"] = "streaming"
            conn.execute(
                "UPDATE chat_jobs SET progress_json = ?, updated_at = ? WHERE job_id = ?",
                (_dumps(progress), now, job_id),
            )
        bump_feed(conn, job_id)
    return seq


def list_events(job_id: str, *, after: int = -1, limit: int = 500) -> list[dict]:
    after = int(after if after is not None else -1)
    limit = max(1, min(int(limit or 500), 2000))
    with get_db() as conn:
        rows = conn.execute(
            """SELECT seq, ts, event_json FROM chat_job_events
               WHERE job_id = ? AND seq > ?
               ORDER BY seq ASC LIMIT ?""",
            (job_id, after, limit),
        ).fetchall()
    out = []
    for r in rows:
        ev = _loads(r["event_json"], {})
        if not isinstance(ev, dict):
            ev = {}
        ev["i"] = int(r["seq"])
        ev["_ts"] = float(r["ts"] or 0)
        out.append(ev)
    return out


def try_acquire_lease(job_id: str, owner: str, lease_seconds: float) -> bool:
    now = time.time()
    until = now + max(5.0, float(lease_seconds))
    with get_db() as conn:
        cur = conn.execute(
            """UPDATE chat_jobs
               SET lease_owner = ?, lease_until = ?, updated_at = ?,
                   status = CASE WHEN status = 'queued' THEN 'running' ELSE status END,
                   started_at = COALESCE(started_at, ?)
               WHERE job_id = ?
                 AND status IN ('queued', 'running', 'blocked')
                 AND (lease_until IS NULL OR lease_until < ? OR lease_owner = ?)""",
            (owner, until, now, now, job_id, now, owner),
        )
        return cur.rowcount > 0


def release_lease(job_id: str, owner: str) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE chat_jobs SET lease_owner = '', lease_until = NULL, updated_at = ?
               WHERE job_id = ? AND lease_owner = ?""",
            (time.time(), job_id, owner),
        )


def list_claimable(now: float | None = None, limit: int = 5) -> list[dict]:
    now = now if now is not None else time.time()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM chat_jobs
               WHERE status IN ('queued', 'running')
                 AND (lease_until IS NULL OR lease_until < ?)
                 AND (
                   cancel_requested_at IS NOT NULL
                   OR next_run_at IS NULL
                   OR next_run_at <= ?
                 )
               ORDER BY CASE WHEN cancel_requested_at IS NOT NULL THEN 0 ELSE 1 END,
                        created_at ASC
               LIMIT ?""",
            (now, now, limit),
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def list_recoverable() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM chat_jobs
               WHERE status IN ('queued', 'running', 'blocked')"""
        ).fetchall()
    return [_row_to_job(r) for r in rows]


def upsert_delivery(
    delivery_id: str,
    *,
    job_id: str,
    kind: str,
    status: str = "pending",
    payload: dict | None = None,
    attempts: int = 0,
    last_error: str = "",
) -> None:
    now = time.time()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT delivery_id FROM chat_deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE chat_deliveries SET status = ?, payload_json = ?,
                   attempts = ?, last_error = ?, updated_at = ?
                   WHERE delivery_id = ?""",
                (
                    status,
                    _dumps(payload or {}),
                    attempts,
                    last_error or "",
                    now,
                    delivery_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO chat_deliveries (
                    delivery_id, job_id, kind, status, payload_json,
                    attempts, last_error, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    delivery_id,
                    job_id,
                    kind,
                    status,
                    _dumps(payload or {}),
                    attempts,
                    last_error or "",
                    now,
                    now,
                ),
            )


def get_delivery(delivery_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM chat_deliveries WHERE delivery_id = ?",
            (delivery_id,),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["payload"] = _loads(d.pop("payload_json", None), {})
    return d


def list_pending_deliveries(limit: int = 10) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM chat_deliveries
               WHERE status = 'pending'
               ORDER BY created_at ASC LIMIT ?""",
            (max(1, min(int(limit or 10), 50)),),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = _loads(d.pop("payload_json", None), {})
        out.append(d)
    return out


def feed_since(session_id: str, after_seq: int = 0, *, owner_id: str | None = None) -> dict:
    after_seq = int(after_seq or 0)
    clauses = ["session_id = ?", "feed_seq > ?"]
    args: list[Any] = [session_id, after_seq]
    if owner_id:
        clauses.append("owner_id = ?")
        args.append(owner_id)
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM chat_jobs
                WHERE {' AND '.join(clauses)}
                ORDER BY feed_seq ASC LIMIT 50""",
            args,
        ).fetchall()
    jobs = [_row_to_job(r) for r in rows]
    max_seq = after_seq
    for j in jobs:
        max_seq = max(max_seq, int(j.get("feed_seq") or 0))
    return {"jobs": jobs, "after": max_seq}


def cleanup_old_jobs(max_days: int = 30) -> int:
    cutoff = time.time() - max(1, int(max_days)) * 86400
    with get_db() as conn:
        rows = conn.execute(
            """SELECT job_id FROM chat_jobs
               WHERE status IN ('completed', 'failed', 'cancelled')
                 AND updated_at < ?""",
            (cutoff,),
        ).fetchall()
        ids = [r["job_id"] for r in rows]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            f"DELETE FROM chat_job_events WHERE job_id IN ({placeholders})", ids
        )
        conn.execute(
            f"DELETE FROM chat_deliveries WHERE job_id IN ({placeholders})", ids
        )
        cur = conn.execute(
            f"DELETE FROM chat_jobs WHERE job_id IN ({placeholders})", ids
        )
        return cur.rowcount
