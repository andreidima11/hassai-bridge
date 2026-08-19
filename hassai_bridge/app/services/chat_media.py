"""Persist chat image attachments on disk for session history."""

from __future__ import annotations

import base64
import re
import uuid
from pathlib import Path

from core.config import DATA_DIR

UPLOADS_ROOT = DATA_DIR / "uploads" / "chat"
DATA_URL_RE = re.compile(r"^data:(image/[\w.+-]+);base64,([A-Za-z0-9+/=\s]+)$", re.DOTALL)
MAX_IMAGES = 4
MAX_BYTES = 1_500_000
_ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})


def _safe_user_dir(user_id: str) -> Path:
    safe = re.sub(r"[^\w.-]", "_", (user_id or "default").strip())[:64] or "default"
    path = UPLOADS_ROOT / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ext_for_mime(mime: str) -> str:
    return {
        "image/jpeg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }.get(mime, "bin")


def parse_data_url(url: str) -> tuple[str, bytes] | None:
    match = DATA_URL_RE.match(str(url or "").strip())
    if not match:
        return None
    mime = match.group(1).lower()
    if mime not in _ALLOWED_MIME:
        return None
    try:
        raw = base64.b64decode(match.group(2), validate=True)
    except (ValueError, base64.binascii.Error):
        return None
    if not raw or len(raw) > MAX_BYTES:
        return None
    return mime, raw


def persist_attachments_from_content(user_id: str, content) -> list[dict]:
    if not isinstance(content, list):
        return []
    saved: list[dict] = []
    base = _safe_user_dir(user_id)
    for part in content:
        if not isinstance(part, dict) or part.get("type") != "image_url":
            continue
        url = (part.get("image_url") or {}).get("url") or ""
        parsed = parse_data_url(url)
        if not parsed:
            continue
        mime, raw = parsed
        att_id = uuid.uuid4().hex[:16]
        path = base / f"{att_id}.{_ext_for_mime(mime)}"
        path.write_bytes(raw)
        saved.append({"id": att_id, "mime": mime})
        if len(saved) >= MAX_IMAGES:
            break
    return saved


def resolve_attachment_path(user_id: str, att_id: str) -> Path | None:
    att_id = str(att_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{16}", att_id):
        return None
    base = _safe_user_dir(user_id)
    for path in base.glob(f"{att_id}.*"):
        if path.is_file():
            return path
    return None


def attachment_data_url(user_id: str, att: dict) -> str | None:
    path = resolve_attachment_path(user_id, str(att.get("id") or ""))
    if not path:
        return None
    mime = str(att.get("mime") or "image/jpeg")
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def attachment_public_url(att_id: str, session_id: str = "") -> str:
    query = f"?session_id={session_id}" if session_id else ""
    return f"/api/chat/media/{att_id}{query}"
