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


def persist_image_bytes(user_id: str, raw: bytes, mime: str = "image/png", *, name: str = "") -> dict:
    """Save one generated image blob and return attachment metadata."""
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError("image too large or empty")
    mime = str(mime or "image/png").lower()
    if mime not in _ALLOWED_MIME:
        mime = "image/png"
    att_id = uuid.uuid4().hex[:16]
    base = _safe_user_dir(user_id)
    path = base / f"{att_id}.{_ext_for_mime(mime)}"
    path.write_bytes(raw)
    out = {"id": att_id, "mime": mime}
    if name:
        out["name"] = str(name)[:120]
    return out


def _normalize_upload(raw: bytes, *, filename: str = "", content_type: str = "") -> tuple[bytes, str]:
    """Resize/compress uploads; convert to JPEG when possible (incl. HEIC on server)."""
    if not raw:
        raise ValueError("empty file")
    if len(raw) > MAX_BYTES * 3:
        raise ValueError("image too large")

    ctype = str(content_type or "").split(";", 1)[0].strip().lower()
    name = str(filename or "").lower()
    if not ctype or ctype == "application/octet-stream":
        if name.endswith(".png"):
            ctype = "image/png"
        elif name.endswith(".webp"):
            ctype = "image/webp"
        elif name.endswith(".gif"):
            ctype = "image/gif"
        elif name.endswith((".heic", ".heif")):
            ctype = "image/heic"
        else:
            ctype = "image/jpeg"

    try:
        from PIL import Image
    except ImportError:
        if ctype in _ALLOWED_MIME and len(raw) <= MAX_BYTES:
            return raw, ctype
        raise ValueError("unsupported image type") from None

    try:
        import pillow_heif  # optional HEIC support

        pillow_heif.register_heif_opener()
    except ImportError:
        pass

    import io

    try:
        img = Image.open(io.BytesIO(raw))
        if getattr(img, "is_animated", False):
            buf = io.BytesIO()
            img.save(buf, format="GIF")
            out = buf.getvalue()
            if len(out) > MAX_BYTES:
                raise ValueError("image too large")
            return out, "image/gif"
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if ctype == "image/png" else "RGB")
        max_dim = 1280
        w, h = img.size
        scale = min(1.0, max_dim / max(w, h, 1))
        if scale < 1.0:
            img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.Resampling.LANCZOS)
        out_mime = "image/png" if ctype == "image/png" else "image/jpeg"
        buf = io.BytesIO()
        if out_mime == "image/png":
            img.save(buf, format="PNG", optimize=True)
        else:
            if img.mode == "RGBA":
                bg = Image.new("RGB", img.size, (0, 0, 0))
                bg.paste(img, mask=img.split()[3])
                img = bg
            img.save(buf, format="JPEG", quality=82, optimize=True)
            out_mime = "image/jpeg"
        out = buf.getvalue()
        if len(out) > MAX_BYTES:
            raise ValueError("image too large")
        return out, out_mime
    except ValueError:
        raise
    except Exception as exc:
        if ctype in _ALLOWED_MIME and len(raw) <= MAX_BYTES:
            return raw, ctype
        raise ValueError("unsupported image type") from exc


def save_uploaded_file(user_id: str, raw: bytes, *, filename: str = "", content_type: str = "") -> dict:
    """Process and persist one chat upload; returns attachment metadata."""
    processed, mime = _normalize_upload(raw, filename=filename, content_type=content_type)
    name = str(filename or "")[:120]
    return persist_image_bytes(user_id, processed, mime, name=name)
