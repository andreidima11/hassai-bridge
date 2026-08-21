"""Agent tools for the Home Assistant /media and /share folders.

Listing, reading and deleting files the add-on can already see through its
folder mappings. Everything is confined to those two roots.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from services import chat_files as cf
from services import chat_media as cm

log = logging.getLogger("hassai.media_tools")

MAX_LIST_ROWS = 200
MAX_TEXT_CHARS = 40_000
MAX_READ_BYTES = 12 * 1024 * 1024

TEXT_EXT = frozenset({
    ".txt", ".md", ".markdown", ".csv", ".json", ".xml", ".html", ".htm",
    ".log", ".rtf", ".yaml", ".yml", ".ini", ".conf",
})
IMAGE_EXT = cf.IMAGE_EXT
VIDEO_EXT = frozenset({".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"})
AUDIO_EXT = frozenset({".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac"})


def roots() -> list[Path]:
    return cf.roots()


def _resolve(raw: str) -> Path:
    """Resolve a user- or model-supplied path inside /media or /share."""
    text = str(raw or "").strip()
    if not text:
        raise ValueError("path is required")
    available = roots()
    if not available:
        raise ValueError("/media and /share are not mounted")
    # An absolute path is taken literally; only relative ones are tried under each root,
    # so /etc/passwd can never be re-rooted into /media/etc/passwd.
    candidates = [Path(text)] if text.startswith("/") else [root / text for root in available]
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        for root in available:
            try:
                resolved.relative_to(root)
            except ValueError:
                continue
            return resolved
    raise ValueError("path must be inside /media or /share")


def file_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in VIDEO_EXT:
        return "video"
    if ext in AUDIO_EXT:
        return "audio"
    if ext in TEXT_EXT or ext == ".pdf":
        return "document"
    return "other"


def _row(path: Path) -> str:
    try:
        stat = path.stat()
        size = stat.st_size
        when = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M")
    except OSError:
        size, when = 0, "—"
    return f"{path}\t{file_kind(path)}\t{size}\t{when}"


def list_media(path: str = "", search: str = "", limit: int = MAX_LIST_ROWS) -> str:
    available = roots()
    if not available:
        return "Error: /media and /share are not mounted for this add-on."
    cap = max(1, min(int(limit or MAX_LIST_ROWS), MAX_LIST_ROWS))
    needle = str(search or "").strip().lower()

    if str(path or "").strip():
        bases = [_resolve(path)]
    elif needle:
        bases = list(available)
    else:
        bases = list(available)
        if len(bases) > 1:
            listing = "\n".join(f"{root}\tfolder" for root in bases)
            return f"Roots (pass one as path=):\npath\tkind\n{listing}"

    rows: list[str] = []
    truncated = False
    for base in bases:
        if not base.is_dir():
            rows.append(_row(base))
            continue
        entries = base.rglob("*") if needle else base.iterdir()
        try:
            for entry in sorted(entries, key=lambda p: str(p).lower()):
                if entry.name.startswith("."):
                    continue
                if needle and needle not in entry.name.lower():
                    continue
                rows.append(f"{entry}\tfolder" if entry.is_dir() else _row(entry))
                if len(rows) >= cap:
                    truncated = True
                    break
        except OSError as exc:
            return f"Error: cannot read folder — {exc}"
        if truncated:
            break

    if not rows:
        return "No files here."
    out = "path\tkind\tsize\tmodified\n" + "\n".join(rows)
    return out + "\n… truncated" if truncated else out


def read_media(path: str) -> dict:
    """Return text for documents, raw bytes for images, metadata for the rest."""
    target = _resolve(path)
    if target.is_dir():
        raise ValueError("that is a folder — use media_list")
    if not target.is_file():
        raise ValueError(f"not found: {target}")
    size = target.stat().st_size
    kind = file_kind(target)
    info = {"kind": kind, "name": target.name, "path": str(target), "size": size}

    if kind == "image":
        if size > MAX_READ_BYTES:
            raise ValueError("image too large to open")
        info["bytes"] = target.read_bytes()
        return info
    if kind == "document":
        if size > cm.MAX_DOC_BYTES:
            raise ValueError("document too large to read")
        raw = target.read_bytes()
        mime = cm.resolve_doc_mime(filename=target.name) or "text/plain"
        try:
            text = cm.extract_document_text(raw, mime=mime, filename=target.name)
        except ValueError:
            text = raw.decode("utf-8", errors="replace")
        if len(text) > MAX_TEXT_CHARS:
            text = text[:MAX_TEXT_CHARS] + f"\n… truncated ({len(text)} chars)"
        info["text"] = text
        return info
    return info


def delete_media(path: str, confirm: bool = False) -> str:
    if confirm is not True:
        return "Error: confirm=true is required to delete a file."
    target = _resolve(path)
    if target.is_dir():
        return "Error: that is a folder — only files can be deleted."
    if not target.is_file():
        return f"Error: not found: {target}"
    try:
        target.unlink()
    except OSError as exc:
        return f"Error: could not delete — {exc}"
    log.info("Deleted media file %s", target)
    return f"OK: deleted {target}"
