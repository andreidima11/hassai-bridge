"""Persistent background task store (SQLite)."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from core.database import get_db

ACTIVE_STATUSES = frozenset({"scheduled", "running", "blocked"})
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


def _row_to_task(row) -> dict:
    d = dict(row)
    d["spec"] = _loads(d.pop("spec_json", None), {})
    d["progress"] = _loads(d.pop("progress_json", None), {})
    d["result"] = _loads(d.pop("result_json", None), None)
    d["error"] = _loads(d.pop("error_json", None), None)
    d["permission_scope"] = _loads(d.pop("permission_scope_json", None), {})
    return d


def new_task_id() -> str:
    return f"bt_{uuid.uuid4().hex[:16]}"


def new_delivery_id(task_id: str, kind: str = "result") -> str:
    return f"dl_{task_id}_{kind}"


def insert_task(
    *,
    task_id: str,
    owner_id: str,
    session_id: str,
    kind: str,
    title: str,
    spec: dict,
    status: str = "scheduled",
    deadline_at: float | None = None,
    next_run_at: float | None = None,
    permission_scope: dict | None = None,
    idempotency_key: str | None = None,
) -> dict:
    now = time.time()
    with get_db() as conn:
        conn.execute(
            """INSERT INTO bg_tasks (
                task_id, owner_id, session_id, kind, title, spec_json, status,
                created_at, started_at, deadline_at, next_run_at, updated_at,
                progress_json, result_json, error_json, permission_scope_json,
                idempotency_key, lease_owner, lease_until, cancel_requested_at, feed_seq
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, '{}', '', '', ?, ?, '', NULL, NULL, 0)""",
            (
                task_id,
                owner_id,
                session_id or "",
                kind,
                title or "",
                _dumps(spec or {}),
                status,
                now,
                deadline_at,
                next_run_at if next_run_at is not None else now,
                now,
                _dumps(permission_scope or {}),
                (idempotency_key or "").strip() or None,
            ),
        )
        conn.execute(
            "INSERT INTO bg_events (task_id, ts, event_type, detail_json) VALUES (?, ?, ?, ?)",
            (task_id, now, "created", _dumps({"kind": kind, "title": title})),
        )
        bump_feed(conn, task_id)
    return get_task(task_id) or {}


def get_task(task_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM bg_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
    return _row_to_task(row) if row else None


def get_by_idempotency(owner_id: str, key: str) -> dict | None:
    key = str(key or "").strip()
    if not key:
        return None
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM bg_tasks WHERE owner_id = ? AND idempotency_key = ?",
            (owner_id, key),
        ).fetchone()
    return _row_to_task(row) if row else None


def list_tasks(
    owner_id: str,
    *,
    status_filter: list[str] | None = None,
    limit: int = 20,
    session_id: str | None = None,
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
        f"SELECT * FROM bg_tasks WHERE {' AND '.join(clauses)} "
        "ORDER BY created_at DESC LIMIT ?"
    )
    with get_db() as conn:
        rows = conn.execute(sql, args).fetchall()
    return [_row_to_task(r) for r in rows]


def count_active(owner_id: str) -> int:
    with get_db() as conn:
        row = conn.execute(
            f"SELECT COUNT(*) AS n FROM bg_tasks WHERE owner_id = ? AND status IN ({','.join('?' for _ in ACTIVE_STATUSES)})",
            (owner_id, *ACTIVE_STATUSES),
        ).fetchone()
    return int(row["n"] if row else 0)


def bump_feed(conn, task_id: str) -> int:
    """Increment feed_seq and return new value. Caller holds get_db() transaction."""
    now = time.time()
    conn.execute(
        "UPDATE bg_tasks SET feed_seq = feed_seq + 1, updated_at = ? WHERE task_id = ?",
        (now, task_id),
    )
    row = conn.execute(
        "SELECT feed_seq FROM bg_tasks WHERE task_id = ?", (task_id,)
    ).fetchone()
    return int(row["feed_seq"] if row else 0)


def touch_feed(task_id: str) -> int:
    """Bump feed_seq so open UIs polling the feed reload."""
    with get_db() as conn:
        return bump_feed(conn, task_id)


def update_task(task_id: str, **fields) -> dict | None:
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
        "title",
    }
    cols: list[str] = []
    args: list[Any] = []
    mapping = {
        "progress": "progress_json",
        "result": "result_json",
        "error": "error_json",
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
        return get_task(task_id)
    now = time.time()
    cols.append("updated_at = ?")
    args.append(now)
    args.append(task_id)
    with get_db() as conn:
        conn.execute(
            f"UPDATE bg_tasks SET {', '.join(cols)} WHERE task_id = ?",
            args,
        )
        bump_feed(conn, task_id)
    return get_task(task_id)


def request_cancel(task_id: str) -> dict | None:
    now = time.time()
    with get_db() as conn:
        row = conn.execute(
            "SELECT status FROM bg_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if not row:
            return None
        if row["status"] in TERMINAL_STATUSES:
            return get_task(task_id)
        conn.execute(
            "UPDATE bg_tasks SET cancel_requested_at = ?, updated_at = ? WHERE task_id = ?",
            (now, now, task_id),
        )
        conn.execute(
            "INSERT INTO bg_events (task_id, ts, event_type, detail_json) VALUES (?, ?, ?, ?)",
            (task_id, now, "cancel_requested", "{}"),
        )
        bump_feed(conn, task_id)
    return get_task(task_id)


def add_event(task_id: str, event_type: str, detail: dict | None = None) -> None:
    with get_db() as conn:
        conn.execute(
            "INSERT INTO bg_events (task_id, ts, event_type, detail_json) VALUES (?, ?, ?, ?)",
            (task_id, time.time(), event_type, _dumps(detail or {})),
        )
        bump_feed(conn, task_id)


def add_observation(
    task_id: str,
    *,
    entity_id: str,
    old_state: str = "",
    new_state: str = "",
    payload: dict | None = None,
    ts: float | None = None,
) -> None:
    with get_db() as conn:
        conn.execute(
            """INSERT INTO bg_observations
               (task_id, ts, entity_id, old_state, new_state, payload_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                task_id,
                ts if ts is not None else time.time(),
                entity_id or "",
                old_state or "",
                new_state or "",
                _dumps(payload or {}),
            ),
        )


def list_observations(task_id: str, *, limit: int = 500) -> list[dict]:
    limit = max(1, min(int(limit or 500), 5000))
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, task_id, ts, entity_id, old_state, new_state, payload_json
               FROM bg_observations WHERE task_id = ? ORDER BY ts ASC LIMIT ?""",
            (task_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["payload"] = _loads(d.pop("payload_json", None), {})
        out.append(d)
    return out


def list_events(task_id: str, *, limit: int = 200) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, task_id, ts, event_type, detail_json
               FROM bg_events WHERE task_id = ? ORDER BY ts ASC LIMIT ?""",
            (task_id, max(1, min(limit, 1000))),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["detail"] = _loads(d.pop("detail_json", None), {})
        out.append(d)
    return out


def try_acquire_lease(task_id: str, owner: str, lease_seconds: float) -> bool:
    now = time.time()
    until = now + max(5.0, float(lease_seconds))
    with get_db() as conn:
        cur = conn.execute(
            """UPDATE bg_tasks
               SET lease_owner = ?, lease_until = ?, updated_at = ?
               WHERE task_id = ?
                 AND status IN ('scheduled', 'running', 'blocked')
                 AND (lease_until IS NULL OR lease_until < ? OR lease_owner = ?)""",
            (owner, until, now, task_id, now, owner),
        )
        return cur.rowcount > 0


def release_lease(task_id: str, owner: str) -> None:
    with get_db() as conn:
        conn.execute(
            """UPDATE bg_tasks SET lease_owner = '', lease_until = NULL, updated_at = ?
               WHERE task_id = ? AND lease_owner = ?""",
            (time.time(), task_id, owner),
        )


def list_claimable(now: float | None = None, limit: int = 20) -> list[dict]:
    """Tasks ready for a worker: due work, or cancel pending on a non-terminal task."""
    now = now if now is not None else time.time()
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM bg_tasks
               WHERE status IN ('scheduled', 'running', 'blocked')
                 AND (lease_until IS NULL OR lease_until < ?)
                 AND (
                   cancel_requested_at IS NOT NULL
                   OR next_run_at IS NULL
                   OR next_run_at <= ?
                 )
               ORDER BY CASE WHEN cancel_requested_at IS NOT NULL THEN 0 ELSE 1 END,
                        CASE WHEN next_run_at IS NULL THEN 0 ELSE 1 END,
                        next_run_at ASC
               LIMIT ?""",
            (now, now, limit),
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def list_active_for_entities() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT * FROM bg_tasks WHERE status IN ({','.join('?' for _ in ACTIVE_STATUSES)})""",
            tuple(ACTIVE_STATUSES),
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def list_recoverable() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM bg_tasks
               WHERE status IN ('scheduled', 'running', 'blocked')"""
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def feed_since(session_id: str, after_seq: int = 0, *, limit: int = 50) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM bg_tasks
               WHERE session_id = ? AND feed_seq > ?
               ORDER BY feed_seq ASC LIMIT ?""",
            (session_id, int(after_seq or 0), max(1, min(limit, 100))),
        ).fetchall()
    return [_row_to_task(r) for r in rows]


def upsert_delivery(
    *,
    delivery_id: str,
    task_id: str,
    kind: str = "result",
    status: str = "pending",
    message_meta: dict | None = None,
    last_error: str = "",
    attempts: int | None = None,
) -> dict:
    now = time.time()
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM bg_deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
        if existing:
            next_attempts = (
                int(attempts)
                if attempts is not None
                else int(existing["attempts"] or 0) + (1 if status != existing["status"] else 0)
            )
            conn.execute(
                """UPDATE bg_deliveries
                   SET status = ?, attempts = ?, last_error = ?, message_meta = ?, updated_at = ?
                   WHERE delivery_id = ?""",
                (
                    status,
                    next_attempts,
                    last_error or "",
                    _dumps(message_meta) if message_meta is not None else existing["message_meta"],
                    now,
                    delivery_id,
                ),
            )
        else:
            conn.execute(
                """INSERT INTO bg_deliveries
                   (delivery_id, task_id, kind, status, attempts, last_error, message_meta, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    delivery_id,
                    task_id,
                    kind,
                    status,
                    int(attempts or 0),
                    last_error or "",
                    _dumps(message_meta or {}),
                    now,
                    now,
                ),
            )
        row = conn.execute(
            "SELECT * FROM bg_deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
    d = dict(row)
    d["message_meta"] = _loads(d.get("message_meta"), {})
    return d


def get_delivery(delivery_id: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM bg_deliveries WHERE delivery_id = ?", (delivery_id,)
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d["message_meta"] = _loads(d.get("message_meta"), {})
    return d


def list_pending_deliveries(limit: int = 20) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """SELECT * FROM bg_deliveries
               WHERE status IN ('pending', 'failed')
               ORDER BY updated_at ASC LIMIT ?""",
            (max(1, min(limit, 100)),),
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["message_meta"] = _loads(d.get("message_meta"), {})
        out.append(d)
    return out


def cleanup_old_results(max_result_days: float = 30) -> int:
    """Delete terminal tasks older than max_result_days (and related rows)."""
    cutoff = time.time() - max(1.0, float(max_result_days)) * 86400.0
    with get_db() as conn:
        rows = conn.execute(
            f"""SELECT task_id FROM bg_tasks
                WHERE status IN ({','.join('?' for _ in TERMINAL_STATUSES)})
                  AND updated_at < ?""",
            (*TERMINAL_STATUSES, cutoff),
        ).fetchall()
        ids = [r["task_id"] for r in rows]
        for tid in ids:
            conn.execute("DELETE FROM bg_observations WHERE task_id = ?", (tid,))
            conn.execute("DELETE FROM bg_events WHERE task_id = ?", (tid,))
            conn.execute("DELETE FROM bg_deliveries WHERE task_id = ?", (tid,))
            conn.execute("DELETE FROM bg_tasks WHERE task_id = ?", (tid,))
    return len(ids)
