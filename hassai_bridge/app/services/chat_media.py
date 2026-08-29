"""Persist chat image/document attachments on disk for session history."""

from __future__ import annotations

import base64
import logging
import re
import uuid
from pathlib import Path

from core.config import DATA_DIR

log = logging.getLogger("hassai.chat_media")

UPLOADS_ROOT = DATA_DIR / "uploads" / "chat"
DATA_URL_RE = re.compile(r"^data:(image/[\w.+-]+);base64,([A-Za-z0-9+/=\s]+)$", re.DOTALL)
DOC_BLOCK_RE = re.compile(
    r"<<<HASSAI_DOC\s+id=\"([a-f0-9]{16})\"\s+name=\"([^\"]*)\"\s+mime=\"([^\"]*)\">>>\n"
    r"(.*?)\n<<<END_HASSAI_DOC>>>",
    re.DOTALL,
)
MAX_IMAGES = 4
MAX_BYTES = 1_500_000
MAX_DOC_BYTES = 4_000_000
MAX_DOC_CHARS = 100_000
MAX_AUDIO_BYTES = 5_000_000
MAX_VIDEO_BYTES = 40_000_000
_ALLOWED_MIME = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
_AUDIO_MIME = frozenset({"audio/mpeg", "audio/wav", "audio/ogg", "audio/webm", "audio/mp4"})
_VIDEO_MIME = frozenset({"video/mp4", "video/webm", "video/quicktime"})
_DOC_MIME = frozenset({
    "application/pdf",
    "application/json",
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/xml",
    "application/xml",
    "application/rtf",
    "text/rtf",
})
_DOC_EXT_MIME = {
    ".pdf": "application/pdf",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".markdown": "text/markdown",
    ".csv": "text/csv",
    ".json": "application/json",
    ".xml": "application/xml",
    ".html": "text/html",
    ".htm": "text/html",
    ".log": "text/plain",
    ".rtf": "application/rtf",
}


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
        "application/pdf": "pdf",
        "application/json": "json",
        "text/plain": "txt",
        "text/markdown": "md",
        "text/csv": "csv",
        "text/html": "html",
        "text/xml": "xml",
        "application/xml": "xml",
        "application/rtf": "rtf",
        "text/rtf": "rtf",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
        "audio/ogg": "ogg",
        "audio/webm": "weba",
        "audio/mp4": "m4a",
        "video/mp4": "mp4",
        "video/webm": "webm",
        "video/quicktime": "mov",
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


def _extracted_path(user_id: str, att_id: str) -> Path:
    return _safe_user_dir(user_id) / f"{att_id}.extracted.txt"


def write_extracted_text(user_id: str, att_id: str, text: str) -> None:
    path = _extracted_path(user_id, att_id)
    path.write_text(str(text or ""), encoding="utf-8")


def read_extracted_text(user_id: str, att: dict | str) -> str | None:
    att_id = str(att.get("id") if isinstance(att, dict) else att or "").strip()
    if not att_id:
        return None
    path = _extracted_path(user_id, att_id)
    if not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def resolve_doc_mime(*, filename: str = "", content_type: str = "") -> str | None:
    ctype = str(content_type or "").split(";", 1)[0].strip().lower()
    if ctype in _DOC_MIME:
        return ctype
    name = str(filename or "").strip().lower()
    for ext, mime in _DOC_EXT_MIME.items():
        if name.endswith(ext):
            return mime
    return None


def _decode_text_bytes(raw: bytes) -> str:
    for enc in ("utf-8", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def extract_document_text(raw: bytes, *, mime: str = "", filename: str = "") -> str:
    mime = (mime or resolve_doc_mime(filename=filename) or "").lower()
    if not raw:
        raise ValueError("empty file")
    if len(raw) > MAX_DOC_BYTES:
        raise ValueError("document too large")

    if mime == "application/pdf" or str(filename).lower().endswith(".pdf"):
        try:
            from pypdf import PdfReader
            import io

            reader = PdfReader(io.BytesIO(raw))
            parts: list[str] = []
            for page in reader.pages:
                try:
                    parts.append(page.extract_text() or "")
                except Exception:
                    continue
            text = "\n".join(parts).strip()
        except ImportError as exc:
            raise ValueError("PDF support unavailable") from exc
        except Exception as exc:
            raise ValueError("could not read PDF") from exc
        if not text:
            raise ValueError("PDF has no extractable text")
    elif mime in {"text/html"}:
        text = _decode_text_bytes(raw)
        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
    else:
        text = _decode_text_bytes(raw).strip()

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("document is empty")
    if len(text) > MAX_DOC_CHARS:
        text = text[:MAX_DOC_CHARS] + "\n\n…[truncated]"
    return text


def format_document_block(*, att_id: str, name: str, mime: str, text: str) -> str:
    safe_name = str(name or "document").replace('"', "'")[:120]
    safe_mime = str(mime or "text/plain").replace('"', "")[:80]
    return (
        f'<<<HASSAI_DOC id="{att_id}" name="{safe_name}" mime="{safe_mime}">>>\n'
        f"{text}\n"
        f"<<<END_HASSAI_DOC>>>"
    )


def strip_document_blocks(text: str) -> str:
    out = DOC_BLOCK_RE.sub("", str(text or ""))
    return re.sub(r"\n{3,}", "\n\n", out).strip()


def parse_document_refs_from_content(content) -> list[dict]:
    """Collect document attachment meta from HASSAI_DOC markers in text parts."""
    texts: list[str] = []
    if isinstance(content, str):
        texts.append(content)
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                texts.append(str(part.get("text") or ""))
    out: list[dict] = []
    seen: set[str] = set()
    for blob in texts:
        for match in DOC_BLOCK_RE.finditer(blob):
            att_id, name, mime = match.group(1), match.group(2), match.group(3)
            if att_id in seen:
                continue
            seen.add(att_id)
            out.append({
                "id": att_id,
                "mime": mime or "text/plain",
                "name": name or "document",
                "kind": "document",
            })
            if len(out) >= MAX_IMAGES:
                return out
    return out


def persist_document_bytes(
    user_id: str,
    raw: bytes,
    *,
    mime: str,
    name: str = "",
    text: str = "",
) -> dict:
    if not raw or len(raw) > MAX_DOC_BYTES:
        raise ValueError("document too large or empty")
    mime = str(mime or "text/plain").lower()
    if mime not in _DOC_MIME:
        raise ValueError("unsupported document type")
    extracted = text or extract_document_text(raw, mime=mime, filename=name)
    att_id = uuid.uuid4().hex[:16]
    base = _safe_user_dir(user_id)
    path = base / f"{att_id}.{_ext_for_mime(mime)}"
    path.write_bytes(raw)
    write_extracted_text(user_id, att_id, extracted)
    out = {"id": att_id, "mime": mime, "kind": "document"}
    if name:
        out["name"] = str(name)[:120]
    return out


def persist_attachments_from_content(user_id: str, content) -> list[dict]:
    if not isinstance(content, list) and not isinstance(content, str):
        return []
    saved: list[dict] = []
    base = _safe_user_dir(user_id)

    if isinstance(content, list):
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
            saved.append({"id": att_id, "mime": mime, "kind": "image"})
            if len(saved) >= MAX_IMAGES:
                break

    docs = parse_document_refs_from_content(content)
    blob = content if isinstance(content, str) else ""
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                blob += "\n" + str(part.get("text") or "")
    for doc in docs:
        if len(saved) >= MAX_IMAGES:
            break
        att_id = doc["id"]
        if any(item.get("id") == att_id for item in saved):
            continue
        if not resolve_attachment_path(user_id, att_id):
            continue
        match = next((m for m in DOC_BLOCK_RE.finditer(blob) if m.group(1) == att_id), None)
        if match and not _extracted_path(user_id, att_id).is_file():
            write_extracted_text(user_id, att_id, match.group(4))
        saved.append({
            "id": att_id,
            "mime": doc.get("mime") or "text/plain",
            "name": doc.get("name") or "",
            "kind": "document",
        })
    return saved


def resolve_attachment_path(user_id: str, att_id: str) -> Path | None:
    att_id = str(att_id or "").strip()
    if not re.fullmatch(r"[a-f0-9]{16}", att_id):
        return None
    base = _safe_user_dir(user_id)
    for path in sorted(base.glob(f"{att_id}.*")):
        if not path.is_file():
            continue
        if path.name.endswith(".extracted.txt"):
            continue
        return path
    return None


def attachment_data_url(user_id: str, att: dict) -> str | None:
    if str(att.get("kind") or "") == "document":
        return None
    path = resolve_attachment_path(user_id, str(att.get("id") or ""))
    if not path:
        return None
    mime = str(att.get("mime") or "image/jpeg")
    if not mime.startswith("image/"):
        return None
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
    out = {"id": att_id, "mime": mime, "kind": "image"}
    if name:
        out["name"] = str(name)[:120]
    return out


def persist_audio_bytes(user_id: str, raw: bytes, mime: str = "audio/mpeg", *, name: str = "") -> dict:
    """Save one spoken clip (TTS reply or recorded question) as an attachment."""
    if not raw:
        raise ValueError("empty audio")
    if len(raw) > MAX_AUDIO_BYTES:
        raise ValueError("audio too large")
    mime = str(mime or "audio/mpeg").split(";", 1)[0].strip().lower()
    if mime not in _AUDIO_MIME:
        mime = "audio/mpeg"
    att_id = uuid.uuid4().hex[:16]
    path = _safe_user_dir(user_id) / f"{att_id}.{_ext_for_mime(mime)}"
    path.write_bytes(raw)
    out = {"id": att_id, "mime": mime, "kind": "audio"}
    if name:
        out["name"] = str(name)[:120]
    return out


def persist_video_bytes(user_id: str, raw: bytes, mime: str = "video/mp4", *, name: str = "") -> dict:
    """Save one Frigate (or other) video clip for chat playback."""
    if not raw:
        raise ValueError("empty video")
    if len(raw) > MAX_VIDEO_BYTES:
        raise ValueError("video too large")
    mime = str(mime or "video/mp4").split(";", 1)[0].strip().lower()
    if mime not in _VIDEO_MIME:
        mime = "video/mp4"
    att_id = uuid.uuid4().hex[:16]
    path = _safe_user_dir(user_id) / f"{att_id}.{_ext_for_mime(mime)}"
    path.write_bytes(raw)
    out = {"id": att_id, "mime": mime, "kind": "video"}
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
    """Process and persist one chat upload (image, document, or video); returns attachment metadata."""
    name = str(filename or "")[:120]
    ctype = str(content_type or "").split(";", 1)[0].strip().lower()
    lower_name = name.lower()
    if ctype in _VIDEO_MIME or lower_name.endswith((".mp4", ".webm", ".mov", ".m4v")):
        mime = ctype if ctype in _VIDEO_MIME else "video/mp4"
        return persist_video_bytes(user_id, raw, mime=mime, name=name)
    doc_mime = resolve_doc_mime(filename=filename, content_type=content_type)
    if doc_mime:
        return persist_document_bytes(user_id, raw, mime=doc_mime, name=name)
    processed, mime = _normalize_upload(raw, filename=filename, content_type=content_type)
    return persist_image_bytes(user_id, processed, mime, name=name)
