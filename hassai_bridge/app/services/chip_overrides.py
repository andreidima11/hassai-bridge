"""Per-user recommendation chip suppress / label+prompt overrides."""

from __future__ import annotations

import logging
import time

from core.database import get_db

log = logging.getLogger("hassai.chip_overrides")


def get_map(user_id: str) -> dict[str, dict]:
    if not user_id:
        return {}
    try:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT chip_id, suppressed, label, prompt, updated_at
                FROM chip_overrides
                WHERE user_id = ?
                """,
                (user_id,),
            ).fetchall()
    except Exception as e:
        log.debug("chip_overrides get_map failed: %s", e)
        return {}
    out: dict[str, dict] = {}
    for row in rows:
        cid = str(row["chip_id"] or "").strip()
        if not cid:
            continue
        out[cid] = {
            "id": cid,
            "suppressed": bool(int(row["suppressed"] or 0)),
            "label": str(row["label"] or ""),
            "prompt": str(row["prompt"] or ""),
            "updated_at": float(row["updated_at"] or 0),
        }
    return out


def list_for_user(user_id: str) -> list[dict]:
    rows = list(get_map(user_id).values())
    rows.sort(key=lambda r: float(r.get("updated_at") or 0), reverse=True)
    return rows


def suppress(user_id: str, chip_id: str) -> None:
    _upsert(user_id, chip_id, suppressed=True, label="", prompt="", keep_text=False)


def set_text(user_id: str, chip_id: str, label: str, prompt: str) -> None:
    label = str(label or "").strip()[:80]
    prompt = str(prompt or "").strip()[:240]
    if not prompt:
        prompt = label
    _upsert(user_id, chip_id, suppressed=False, label=label, prompt=prompt, keep_text=False)


def clear(user_id: str, chip_id: str) -> int:
    if not user_id or not chip_id:
        return 0
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM chip_overrides WHERE user_id = ? AND chip_id = ?",
            (user_id, str(chip_id)[:64]),
        )
        return int(cur.rowcount or 0)


def clear_all(user_id: str) -> int:
    if not user_id:
        return 0
    with get_db() as conn:
        cur = conn.execute("DELETE FROM chip_overrides WHERE user_id = ?", (user_id,))
        return int(cur.rowcount or 0)


def _upsert(
    user_id: str,
    chip_id: str,
    *,
    suppressed: bool,
    label: str,
    prompt: str,
    keep_text: bool,
) -> None:
    if not user_id or not chip_id:
        return
    cid = str(chip_id).strip()[:64]
    now = time.time()
    try:
        with get_db() as conn:
            if keep_text:
                conn.execute(
                    """
                    INSERT INTO chip_overrides (user_id, chip_id, suppressed, label, prompt, updated_at)
                    VALUES (?, ?, ?, '', '', ?)
                    ON CONFLICT(user_id, chip_id) DO UPDATE SET
                        suppressed = excluded.suppressed,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, cid, 1 if suppressed else 0, now),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO chip_overrides (user_id, chip_id, suppressed, label, prompt, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(user_id, chip_id) DO UPDATE SET
                        suppressed = excluded.suppressed,
                        label = excluded.label,
                        prompt = excluded.prompt,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, cid, 1 if suppressed else 0, label[:80], prompt[:240], now),
                )
    except Exception as e:
        log.debug("chip_overrides upsert failed: %s", e)


def apply_overrides(user_id: str, chips: list[dict] | None) -> list[dict]:
    """Drop suppressed chips and rewrite label/prompt from overrides."""
    if not chips:
        return []
    if not user_id:
        return list(chips)
    ov = get_map(user_id)
    if not ov:
        return list(chips)
    out: list[dict] = []
    for chip in chips:
        if not isinstance(chip, dict):
            continue
        cid = str(chip.get("id") or "").strip()
        meta = ov.get(cid) if cid else None
        if meta and meta.get("suppressed"):
            continue
        item = dict(chip)
        if meta:
            if meta.get("label"):
                item["label"] = meta["label"]
            if meta.get("prompt"):
                item["prompt"] = meta["prompt"]
        if item.get("label") and item.get("prompt"):
            out.append(item)
    return out
