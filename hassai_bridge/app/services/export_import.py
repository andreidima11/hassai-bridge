"""Full add-on export / import (config, database, uploads, generated skills)."""

from __future__ import annotations

import errno
import json
import logging
import os
import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from core.config import ADDON_VERSION, CONFIG_FILE, DATA_DIR, DB_SCHEMA_VERSION, load_config, save_config

log = logging.getLogger("hassai.export")

FORMAT_NAME = "hassai-export"
FORMAT_VERSION = 1
MAX_IMPORT_BYTES = 200 * 1024 * 1024
CHUNK_UPLOAD_TTL_SEC = 3600
_pending_uploads: dict[str, dict] = {}

# Top-level config keys that a full backup is expected to carry. Listed in the
# manifest so a restore can confirm voice, Frigate, tool permissions, etc. came
# along — not just providers and the database.
CONFIG_SECTIONS = (
    "api_key",
    "active_provider",
    "providers",
    "secondary_providers",
    "users",
    "language",
    "dynamic_greetings",
    "system_prompt",
    "ha_agent_prompt",
    "knowledge_cutoff",
    "voice",
    "memory",
    "frigate",
    "searxng",
    "performance",
    "security",
    "ha_tools",
    "bridge_tools",
    "skills_disabled",
    "lmstudio",
)

# Only /share, and only the top level — never recurse into /media (OOM/hang on HA).
SHARE_IMPORT_ROOT = Path("/share")
_SHARE_IMPORT_ROOT_OVERRIDE: Path | None = None
DEFAULT_SHARE_IMPORT_NAME = "hassai-import.zip"


def _share_root() -> Path:
    if _SHARE_IMPORT_ROOT_OVERRIDE is not None:
        return _SHARE_IMPORT_ROOT_OVERRIDE
    return SHARE_IMPORT_ROOT


def close_db_connections() -> None:
    """Drop cached SQLite connections so a restored DB file can be opened cleanly."""
    try:
        from database import close_all_connections

        close_all_connections()
    except Exception as exc:
        log.warning("close database connections failed: %s", exc)
    try:
        from services import knowledge_graph as kg

        close_kg = getattr(kg, "close_all_connections", None)
        if callable(close_kg):
            close_kg()
    except Exception as exc:
        log.warning("close knowledge_graph connections failed: %s", exc)


def _atomic_replace(src: Path, dst: Path) -> None:
    """Move/replace a file; fall back to copy when /tmp and /config are different mounts."""
    try:
        os.replace(src, dst)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        log.info("Cross-device replace for %s -> %s; copying instead", src, dst)
        shutil.copy2(src, dst)
        src.unlink(missing_ok=True)


def list_share_import_files(*, limit: int = 40) -> list[dict]:
    """List .zip/.db files in /share (top level only — safe for HA Companion)."""
    root = _share_root()
    found: list[dict] = []
    if not root.is_dir():
        return found
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        log.warning("Cannot list %s: %s", root, exc)
        return found
    for path in entries:
        try:
            if not path.is_file():
                continue
            name_l = path.name.lower()
            if name_l.endswith(".zip"):
                kind = "zip"
            elif name_l.endswith(".db") or name_l.endswith(".sqlite") or name_l.endswith(".sqlite3"):
                kind = "db"
            else:
                continue
            st = path.stat()
            if st.st_size <= 0 or st.st_size > MAX_IMPORT_BYTES:
                continue
            found.append(
                {
                    "path": str(path.resolve()),
                    "name": path.name,
                    "rel": path.name,
                    "root": "share",
                    "kind": kind,
                    "size": int(st.st_size),
                    "mtime": float(st.st_mtime),
                }
            )
        except OSError:
            continue
    found.sort(key=lambda item: item["mtime"], reverse=True)
    return found[:limit]


def resolve_share_import_path(raw: str) -> Path:
    """Resolve a filename or path under /share only (no /media, no traversal)."""
    text = str(raw or "").strip()
    if not text:
        text = DEFAULT_SHARE_IMPORT_NAME
    # Users type a bare filename most of the time
    name = Path(text).name
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        # If they pasted /share/foo.zip, take only the basename after validating prefix
        p = Path(text)
        if p.is_absolute():
            name = p.name
        else:
            raise ValueError("Use a file name in /share (e.g. hassai-import.zip)")
    if ".." in name:
        raise ValueError("Invalid file name")
    root = _share_root()
    try:
        root_res = root.resolve()
    except OSError as exc:
        raise ValueError(f"/share is not available: {exc}") from exc
    if not root_res.is_dir():
        raise ValueError("/share is not available on this add-on")
    path = (root_res / name).resolve()
    try:
        path.relative_to(root_res)
    except ValueError as exc:
        raise ValueError("Path must be a file directly under /share") from exc
    if not path.is_file():
        raise ValueError(f"File not found: /share/{name}")
    size = path.stat().st_size
    if size <= 0 or size > MAX_IMPORT_BYTES:
        raise ValueError(f"Invalid file size (max {MAX_IMPORT_BYTES // (1024 * 1024)}MB)")
    return path


def import_from_share_path(raw: str) -> dict:
    """Restore from a ZIP/DB already on /share (Companion-safe, no file picker)."""
    path = resolve_share_import_path(raw)
    name = path.name.lower()
    close_db_connections()
    if name.endswith(".zip"):
        result = restore_export_zip(path)
        result["source"] = f"/share/{path.name}"
        result["kind"] = "zip"
        return result
    if name.endswith(".db") or name.endswith(".sqlite") or name.endswith(".sqlite3"):
        result = restore_database_file(path)
        result["source"] = f"/share/{path.name}"
        result["kind"] = "db"
        return result
    raise ValueError("Only .zip or .db files are supported")


def start_chunked_upload(*, size: int, filename: str = "", kind: str = "zip") -> dict:
    """Create a temp file for Ingress-friendly chunked upload (zip or db)."""
    import time
    import uuid

    kind = str(kind or "zip").strip().lower()
    if kind not in ("zip", "db"):
        raise ValueError("kind must be zip or db")
    max_bytes = MAX_IMPORT_BYTES if kind == "zip" else 100 * 1024 * 1024
    if size <= 0 or size > max_bytes:
        raise ValueError(f"Invalid upload size (max {max_bytes // (1024 * 1024)}MB)")
    upload_id = uuid.uuid4().hex
    suffix = ".zip" if kind == "zip" else ".db"
    tmp = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
    tmp_path = Path(tmp.name)
    tmp.close()
    _pending_uploads[upload_id] = {
        "path": tmp_path,
        "size": int(size),
        "received": 0,
        "filename": str(filename or "")[:200],
        "kind": kind,
        "created": time.time(),
    }
    _prune_chunked_uploads()
    return {"id": upload_id, "size": int(size), "kind": kind}


def _prune_chunked_uploads() -> None:
    import time

    now = time.time()
    stale = [
        uid
        for uid, meta in _pending_uploads.items()
        if now - float(meta.get("created") or 0) > CHUNK_UPLOAD_TTL_SEC
    ]
    for uid in stale:
        meta = _pending_uploads.pop(uid, None)
        if meta:
            Path(meta["path"]).unlink(missing_ok=True)


def append_chunk(upload_id: str, offset: int, data: bytes) -> dict:
    meta = _pending_uploads.get(upload_id)
    if not meta:
        raise ValueError("Upload session expired or unknown — start again")
    expected = int(meta["received"])
    if int(offset) != expected:
        raise ValueError(f"Unexpected chunk offset {offset}, expected {expected}")
    if not data:
        raise ValueError("Empty chunk")
    path = Path(meta["path"])
    with open(path, "ab") as out:
        out.write(data)
    meta["received"] = expected + len(data)
    if meta["received"] > meta["size"]:
        path.unlink(missing_ok=True)
        _pending_uploads.pop(upload_id, None)
        raise ValueError("Upload exceeded declared size")
    return {"id": upload_id, "received": meta["received"], "size": meta["size"]}


def finish_chunked_upload(upload_id: str) -> dict:
    meta = _pending_uploads.pop(upload_id, None)
    if not meta:
        raise ValueError("Upload session expired or unknown — start again")
    path = Path(meta["path"])
    try:
        if int(meta["received"]) != int(meta["size"]):
            raise ValueError(
                f"Incomplete upload: got {meta['received']} of {meta['size']} bytes"
            )
        kind = meta.get("kind") or "zip"
        close_db_connections()
        if kind == "db":
            return restore_database_file(path)
        return restore_export_zip(path)
    finally:
        path.unlink(missing_ok=True)


def restore_database_file(db_path: Path) -> dict:
    """Replace hassai.db from an uploaded SQLite file path."""
    from database import DB_PATH

    src = Path(db_path)
    # Validate with a short header read + separate check connection (not the live pool)
    with open(src, "rb") as fh:
        header = fh.read(16)
    if not header.startswith(b"SQLite format 3"):
        raise ValueError("Invalid SQLite database file")
    conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
    finally:
        conn.close()
    required = {"memories", "conversations"}
    missing = required - tables
    if missing:
        raise ValueError(f"Invalid HASSAI backup: missing tables {missing}")

    close_db_connections()
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    backup_path = DB_PATH.with_suffix(".db.bak")
    if DB_PATH.exists():
        shutil.copy2(DB_PATH, backup_path)
    # Stream copy — avoid loading the whole DB into RAM
    tmp_dest = DB_PATH.with_suffix(".db.restoring")
    shutil.copy2(src, tmp_dest)
    _atomic_replace(tmp_dest, DB_PATH)
    for suffix in ("-wal", "-shm"):
        side = Path(str(DB_PATH) + suffix)
        if side.exists():
            side.unlink(missing_ok=True)
    size = DB_PATH.stat().st_size
    return {
        "status": "ok",
        "message": "Database restored successfully",
        "size": size,
    }


def restore_config_only(cfg: dict) -> dict:
    """Replace settings/profiles/providers from a config dict (no DB/uploads)."""
    if not isinstance(cfg, dict):
        raise ValueError("config must be an object")
    # Require at least providers or users or api_key so we don't wipe with garbage
    if not any(k in cfg for k in ("providers", "users", "api_key", "secondary_providers")):
        raise ValueError("Invalid settings file: missing providers/users")
    save_config(cfg)
    return {
        "status": "ok",
        "message": "Settings restored successfully",
        "counts": {
            "providers": len(cfg.get("providers") or []),
            "secondary_providers": len(cfg.get("secondary_providers") or []),
            "profiles": len((cfg.get("users") or {}).get("profiles") or {}),
        },
    }

# Paths relative to DATA_DIR (or package data via symlink on add-on)
UPLOADS_REL = Path("uploads") / "chat"
GENERATED_SKILLS_REL = Path("skills") / "generated"
SKILL_USAGE_NAME = "skill_usage.json"


def _skills_data_root() -> Path:
    """Skills live under app/data/skills (symlinked to DATA_DIR on the add-on)."""
    return Path(__file__).resolve().parent.parent / "data"


def _checkpoint_db(db_path: Path) -> None:
    if not db_path.exists():
        return
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            conn.close()
    except Exception as exc:
        log.warning("SQLite checkpoint before export failed: %s", exc)


def _add_tree(zf: zipfile.ZipFile, src_dir: Path, arc_prefix: str) -> int:
    """Add files under src_dir into the zip. Returns file count."""
    if not src_dir.is_dir():
        return 0
    count = 0
    for path in sorted(src_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src_dir)
        zf.write(path, f"{arc_prefix}/{rel.as_posix()}")
        count += 1
    return count


def _config_inventory(cfg: dict) -> dict:
    """Summarize which settings sections and secrets landed in the export."""
    voice = cfg.get("voice") if isinstance(cfg.get("voice"), dict) else {}
    local_stt = voice.get("local_stt") if isinstance(voice.get("local_stt"), dict) else {}
    local_tts = voice.get("local_tts") if isinstance(voice.get("local_tts"), dict) else {}
    sections = {key: key in cfg for key in CONFIG_SECTIONS}
    return {
        "sections": sections,
        "voice": {
            "enabled": bool(voice.get("enabled")),
            "stt_engine": str(voice.get("stt_engine") or "google"),
            "tts_engine": str(voice.get("tts_engine") or "google"),
            "language": str(voice.get("language") or ""),
            "controls": str(voice.get("controls") or "both"),
            "has_google_api_key": bool(str(voice.get("google_api_key") or "").strip()),
            "local_stt_url": str(local_stt.get("url") or ""),
            "local_tts_url": str(local_tts.get("url") or ""),
            "local_tts_voice": str(local_tts.get("voice") or ""),
        },
        "secrets": {
            "bridge_api_key": bool(str(cfg.get("api_key") or "").strip()),
            "provider_api_keys": sum(
                1 for p in (cfg.get("providers") or []) if isinstance(p, dict) and str(p.get("api_key") or "").strip()
            ),
            "secondary_provider_api_keys": sum(
                1
                for p in (cfg.get("secondary_providers") or [])
                if isinstance(p, dict) and str(p.get("api_key") or "").strip()
            ),
            "user_api_keys": len((cfg.get("users") or {}).get("api_keys") or {}),
            "google_voice_api_key": bool(str(voice.get("google_api_key") or "").strip()),
        },
    }


def _settings_readme(cfg: dict, inventory: dict) -> str:
    """Plain-text note inside the ZIP so a human can see what was backed up."""
    voice = inventory.get("voice") or {}
    secrets = inventory.get("secrets") or {}
    lines = [
        "HASSAI Bridge full backup",
        "=========================",
        "",
        "This ZIP restores EVERYTHING from Settings, not just the database:",
        "  - Providers + secondary providers (API keys included)",
        "  - Users / profiles / Assist API keys",
        "  - Language, prompts, Eco Mode, tool permissions",
        "  - Voice (Google key, STT/TTS engines, Whisper/Piper URLs, Chirp voice)",
        "  - Memory, Frigate, SearXNG, performance",
        "  - Conversations + memories (hassai.db)",
        "  - Chat images and spoken audio clips (uploads/chat)",
        "  - Generated skills",
        "",
        f"Voice enabled: {voice.get('enabled')}",
        f"STT engine: {voice.get('stt_engine')}",
        f"TTS engine: {voice.get('tts_engine')}",
        f"Voice language: {voice.get('language') or '—'}",
        f"Google voice key present: {secrets.get('google_voice_api_key')}",
        f"Local Whisper URL: {voice.get('local_stt_url') or '—'}",
        f"Local Piper URL: {voice.get('local_tts_url') or '—'}",
        f"Piper voice: {voice.get('local_tts_voice') or '—'}",
        "",
        "Store this file safely — it contains secrets.",
        "",
    ]
    return "\n".join(lines)


def build_export_zip(dest: Path) -> dict:
    """Write a complete export zip to dest. Returns manifest dict."""
    from database import DB_PATH

    cfg = load_config()
    _checkpoint_db(DB_PATH)

    skills_root = _skills_data_root()
    uploads_dir = DATA_DIR / UPLOADS_REL
    generated_dir = skills_root / "generated"
    usage_file = skills_root.parent / SKILL_USAGE_NAME
    if not usage_file.exists():
        usage_file = DATA_DIR / SKILL_USAGE_NAME

    inventory = _config_inventory(cfg)
    includes = {
        "config": True,
        "database": DB_PATH.exists(),
        "uploads": uploads_dir.is_dir(),
        "generated_skills": generated_dir.is_dir(),
        "skill_usage": usage_file.is_file(),
        # Explicit so older UI copy ("providers, memories, images") is not
        # mistaken for the whole story — voice and the rest of Settings ride
        # inside config.json.
        "settings_voice": True,
        "settings_frigate": True,
        "settings_searxng": True,
        "settings_memory": True,
        "settings_tools": True,
        "settings_prompts": True,
    }

    manifest = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "addon_version": ADDON_VERSION,
        "db_schema_version": DB_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "includes": includes,
        "config_inventory": inventory,
        "secrets": {
            "include_bridge_api_key": True,
            "include_user_api_keys": True,
            "include_provider_api_keys": True,
            "include_google_voice_api_key": True,
        },
        "counts": {},
    }

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Full settings (providers, secondary, profiles, keys, voice, Frigate, …)
        zf.writestr(
            "config.json",
            json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
            compress_type=zipfile.ZIP_DEFLATED,
        )
        zf.writestr(
            "README.txt",
            _settings_readme(cfg, inventory),
            compress_type=zipfile.ZIP_DEFLATED,
        )

        if DB_PATH.exists():
            zf.write(DB_PATH, "hassai.db")

        upload_count = _add_tree(zf, uploads_dir, "uploads/chat")
        skill_count = _add_tree(zf, generated_dir, "skills/generated")
        if usage_file.is_file():
            zf.write(usage_file, SKILL_USAGE_NAME)

        manifest["counts"] = {
            "providers": len(cfg.get("providers") or []),
            "secondary_providers": len(cfg.get("secondary_providers") or []),
            "profiles": len((cfg.get("users") or {}).get("profiles") or {}),
            "upload_files": upload_count,
            "generated_skills": skill_count,
            "config_sections": sum(1 for present in inventory["sections"].values() if present),
        }
        zf.writestr(
            "manifest.json",
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            compress_type=zipfile.ZIP_DEFLATED,
        )

    return manifest


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        raw = zf.read("manifest.json")
    except KeyError as exc:
        raise ValueError("Not a HASSAI export: missing manifest.json") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid manifest.json") from exc
    if not isinstance(data, dict):
        raise ValueError("Invalid manifest.json")
    if data.get("format") != FORMAT_NAME:
        raise ValueError(f"Unsupported export format: {data.get('format')!r}")
    ver = data.get("format_version")
    if ver not in (1, FORMAT_VERSION):
        raise ValueError(f"Unsupported export format_version: {ver!r}")
    return data


def _extract_members(zf: zipfile.ZipFile, prefix: str, dest_dir: Path) -> int:
    """Safely extract zip members under prefix into dest_dir."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    prefix = prefix.rstrip("/") + "/"
    for info in zf.infolist():
        name = info.filename.replace("\\", "/")
        if name.endswith("/") or not name.startswith(prefix):
            continue
        rel = name[len(prefix) :]
        if not rel or ".." in Path(rel).parts:
            continue
        target = dest_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


def restore_export_zip(zip_path: Path) -> dict:
    """Replace config, database, uploads, and generated skills from an export zip."""
    from database import DB_PATH

    if not zipfile.is_zipfile(zip_path):
        raise ValueError("Not a valid ZIP archive")

    with zipfile.ZipFile(zip_path, "r") as zf:
        manifest = _read_manifest(zf)
        names = set(zf.namelist())

        if "config.json" not in names:
            raise ValueError("Export is missing config.json")

        cfg_raw = zf.read("config.json")
        try:
            cfg = json.loads(cfg_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Invalid config.json in export") from exc
        if not isinstance(cfg, dict):
            raise ValueError("config.json must be an object")

        # Validate + stage DB once (stream out of zip — avoid double RAM load)
        has_db = "hassai.db" in names
        db_tmp: Path | None = None
        if has_db:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                db_tmp = Path(tmp.name)
                with zf.open("hassai.db") as src:
                    shutil.copyfileobj(src, tmp)
            try:
                with open(db_tmp, "rb") as fh:
                    if not fh.read(16).startswith(b"SQLite format 3"):
                        raise ValueError("Invalid SQLite database in export")
                conn = sqlite3.connect(f"file:{db_tmp}?mode=ro", uri=True)
                try:
                    tables = {
                        r[0]
                        for r in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                finally:
                    conn.close()
                required = {"memories", "conversations"}
                missing = required - tables
                if missing:
                    raise ValueError(f"Invalid HASSAI database: missing tables {missing}")
            except Exception:
                if db_tmp is not None:
                    db_tmp.unlink(missing_ok=True)
                raise

        close_db_connections()

        # Apply config first
        save_config(cfg)

        # Database — atomic replace from staged temp
        if has_db and db_tmp is not None:
            try:
                backup_path = DB_PATH.with_suffix(".db.bak")
                if DB_PATH.exists():
                    shutil.copy2(DB_PATH, backup_path)
                DB_PATH.parent.mkdir(parents=True, exist_ok=True)
                _atomic_replace(db_tmp, DB_PATH)
                db_tmp = None
                for suffix in ("-wal", "-shm"):
                    side = Path(str(DB_PATH) + suffix)
                    if side.exists():
                        side.unlink(missing_ok=True)
            finally:
                if db_tmp is not None:
                    db_tmp.unlink(missing_ok=True)

        # Uploads — replace tree when present in export
        if any(n.startswith("uploads/chat/") for n in names):
            uploads_dir = DATA_DIR / UPLOADS_REL
            if uploads_dir.exists():
                shutil.rmtree(uploads_dir)
            _extract_members(zf, "uploads/chat", uploads_dir)

        # Generated skills
        skills_root = _skills_data_root()
        generated_dir = skills_root / "generated"
        if any(n.startswith("skills/generated/") for n in names):
            if generated_dir.exists():
                shutil.rmtree(generated_dir)
            _extract_members(zf, "skills/generated", generated_dir)

        if SKILL_USAGE_NAME in names:
            usage_dest = skills_root.parent / SKILL_USAGE_NAME
            usage_dest.parent.mkdir(parents=True, exist_ok=True)
            usage_dest.write_bytes(zf.read(SKILL_USAGE_NAME))

    return {
        "status": "ok",
        "message": "Full settings and data restored successfully",
        "manifest": {
            "addon_version": manifest.get("addon_version"),
            "exported_at": manifest.get("exported_at"),
            "includes": manifest.get("includes"),
            "counts": manifest.get("counts"),
        },
    }
