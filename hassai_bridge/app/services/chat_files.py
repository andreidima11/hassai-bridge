"""Browse Home Assistant /share and /media for chat attachments.

The Companion app WebView drops the Ingress panel when a native file picker
opens, so the app needs a way to attach files that never leaves the page.
"""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("hassai.chat_files")

MAX_ENTRIES = 300
MAX_FILE_BYTES = 4 * 1024 * 1024

DEFAULT_ROOTS = ("/share", "/media")
_ROOT_OVERRIDES: tuple[str, ...] | None = None

IMAGE_EXT = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic", ".heif"})
DOC_EXT = frozenset({
    ".pdf",
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".log",
    ".rtf",
})


def set_roots_for_test(paths: tuple[str, ...] | None) -> None:
    global _ROOT_OVERRIDES
    _ROOT_OVERRIDES = paths


def roots() -> list[Path]:
    names = _ROOT_OVERRIDES if _ROOT_OVERRIDES is not None else DEFAULT_ROOTS
    out: list[Path] = []
    for name in names:
        try:
            path = Path(name).resolve()
        except OSError:
            continue
        if path.is_dir():
            out.append(path)
    return out


def file_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in IMAGE_EXT:
        return "image"
    if ext in DOC_EXT:
        return "document"
    return ""


def _within_roots(path: Path) -> bool:
    for root in roots():
        try:
            path.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def _resolve(raw: str) -> Path:
    text = str(raw or "").strip()
    if not text:
        raise ValueError("Missing path")
    try:
        path = Path(text).resolve()
    except OSError as exc:
        raise ValueError(f"Invalid path: {exc}") from exc
    if not _within_roots(path):
        raise ValueError("Path is outside /share and /media")
    return path


def list_dir(raw: str = "", kind: str = "") -> dict:
    """One directory at a time — never recursive, so huge /media trees stay cheap."""
    available = roots()
    if not available:
        return {"path": "", "parent": "", "roots": [], "dirs": [], "files": []}

    if not str(raw or "").strip():
        if len(available) == 1:
            current = available[0]
        else:
            return {
                "path": "",
                "parent": "",
                "roots": [str(p) for p in available],
                "dirs": [{"name": str(p), "path": str(p)} for p in available],
                "files": [],
            }
    else:
        current = _resolve(raw)

    if not current.is_dir():
        raise ValueError("Not a folder")

    wanted = str(kind or "").strip().lower()
    dirs: list[dict] = []
    files: list[dict] = []
    try:
        entries = sorted(current.iterdir(), key=lambda p: p.name.lower())
    except OSError as exc:
        raise ValueError(f"Cannot read folder: {exc}") from exc

    for entry in entries[:MAX_ENTRIES]:
        if entry.name.startswith("."):
            continue
        try:
            if entry.is_dir():
                dirs.append({"name": entry.name, "path": str(entry)})
                continue
            if not entry.is_file():
                continue
            item_kind = file_kind(entry)
            if not item_kind:
                continue
            if wanted and wanted != item_kind:
                continue
            size = entry.stat().st_size
            if size <= 0 or size > MAX_FILE_BYTES:
                continue
            files.append({
                "name": entry.name,
                "path": str(entry),
                "kind": item_kind,
                "size": size,
            })
        except OSError:
            continue

    parent = "" if current in available else str(current.parent)
    if parent and not _within_roots(Path(parent)):
        parent = ""
    return {
        "path": str(current),
        "parent": parent,
        "roots": [str(p) for p in available],
        "dirs": dirs,
        "files": files,
    }


def read_file(raw: str) -> tuple[bytes, str]:
    """Return (bytes, filename) for a file under /share or /media."""
    path = _resolve(raw)
    if not path.is_file():
        raise ValueError("File not found")
    if not file_kind(path):
        raise ValueError("Unsupported file type")
    size = path.stat().st_size
    if size <= 0:
        raise ValueError("Empty file")
    if size > MAX_FILE_BYTES:
        raise ValueError("File too large")
    return path.read_bytes(), path.name
