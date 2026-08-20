"""Full add-on export / import (config, database, uploads, generated skills)."""

from __future__ import annotations

import json
import logging
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

    includes = {
        "config": True,
        "database": DB_PATH.exists(),
        "uploads": uploads_dir.is_dir(),
        "generated_skills": generated_dir.is_dir(),
        "skill_usage": usage_file.is_file(),
    }

    manifest = {
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "addon_version": ADDON_VERSION,
        "db_schema_version": DB_SCHEMA_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "includes": includes,
        "secrets": {
            "include_bridge_api_key": True,
            "include_user_api_keys": True,
            "include_provider_api_keys": True,
        },
        "counts": {},
    }

    with zipfile.ZipFile(dest, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # Full settings (providers, secondary, profiles, keys, prompts, …)
        zf.writestr(
            "config.json",
            json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
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

        # Validate DB if present
        has_db = "hassai.db" in names
        if has_db:
            with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
                tmp.write(zf.read("hassai.db"))
                tmp_path = Path(tmp.name)
            try:
                if not tmp_path.read_bytes()[:16].startswith(b"SQLite format 3"):
                    raise ValueError("Invalid SQLite database in export")
                conn = sqlite3.connect(str(tmp_path))
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
            finally:
                tmp_path.unlink(missing_ok=True)

        # Apply config first
        save_config(cfg)

        # Database
        if has_db:
            backup_path = DB_PATH.with_suffix(".db.bak")
            if DB_PATH.exists():
                shutil.copy2(DB_PATH, backup_path)
            with open(DB_PATH, "wb") as out:
                out.write(zf.read("hassai.db"))
            # Drop WAL leftovers so the restored file is authoritative
            for suffix in ("-wal", "-shm"):
                side = Path(str(DB_PATH) + suffix)
                if side.exists():
                    side.unlink(missing_ok=True)

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
