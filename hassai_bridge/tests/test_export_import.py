"""Tests for full settings export / import."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from pathlib import Path

import pytest

from services import export_import as ei


@pytest.fixture()
def data_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    cfg_path = data / "config.json"
    db_path = data / "hassai.db"
    uploads = data / "uploads" / "chat" / "alice"
    uploads.mkdir(parents=True)
    (uploads / "abcd1234abcd1234.jpg").write_bytes(b"fake-jpeg")

    skills = tmp_path / "skills_pkg" / "data" / "skills" / "generated"
    skills.mkdir(parents=True)
    (skills / "my_skill.py").write_text("# skill\n", encoding="utf-8")
    usage = tmp_path / "skills_pkg" / "data" / "skill_usage.json"
    usage.write_text('{"my_skill": 3}', encoding="utf-8")

    cfg = {
        "api_key": "hab_test",
        "active_provider": "deepseek_main",
        "providers": [
            {
                "id": "deepseek_main",
                "name": "DeepSeek",
                "type": "deepseek",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-test",
                "model": "deepseek-chat",
                "image_generation_provider": "grok_sec",
            }
        ],
        "secondary_providers": [
            {
                "id": "grok_sec",
                "name": "Grok",
                "type": "grok",
                "base_url": "https://api.x.ai/v1",
                "api_key": "xai-test",
                "model": "grok-4.6",
            }
        ],
        "users": {
            "default_user": "alice",
            "api_keys": {"alice": "hab_alice"},
            "profiles": {"alice": {"display_name": "Alice", "ha_id": "person.alice"}},
        },
        "language": "ro",
        "system_prompt": "You are HASSAI",
    }
    cfg_path.write_text(json.dumps(cfg), encoding="utf-8")

    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE conversations (id INTEGER PRIMARY KEY)")
    conn.execute("INSERT INTO memories DEFAULT VALUES")
    conn.execute("INSERT INTO conversations DEFAULT VALUES")
    conn.commit()
    conn.close()

    monkeypatch.setattr(ei, "DATA_DIR", data)
    monkeypatch.setattr(ei, "CONFIG_FILE", cfg_path)
    monkeypatch.setattr(ei, "_skills_data_root", lambda: tmp_path / "skills_pkg" / "data" / "skills")

    import database as db_mod
    from core import database as core_db
    from core import config as core_cfg

    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    monkeypatch.setattr(core_cfg, "DATA_DIR", data)
    monkeypatch.setattr(core_cfg, "CONFIG_FILE", cfg_path)
    monkeypatch.setattr(core_cfg, "_config_cache", None)
    monkeypatch.setattr(core_cfg, "_config_mtime", 0.0)

    return {
        "data": data,
        "cfg_path": cfg_path,
        "db_path": db_path,
        "uploads": uploads,
        "skills": skills,
        "usage": usage,
    }


def test_build_and_restore_export_roundtrip(data_env, tmp_path):
    zip_path = tmp_path / "out.zip"
    manifest = ei.build_export_zip(zip_path)
    assert zip_path.is_file()
    assert manifest["format"] == "hassai-export"
    assert manifest["counts"]["providers"] == 1
    assert manifest["counts"]["profiles"] == 1
    assert manifest["counts"]["upload_files"] == 1
    assert manifest["counts"]["generated_skills"] == 1

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        assert "manifest.json" in names
        assert "config.json" in names
        assert "hassai.db" in names
        assert any(n.startswith("uploads/chat/") for n in names)
        assert any(n.startswith("skills/generated/") for n in names)

    # Mutate live data then restore
    data_env["cfg_path"].write_text(json.dumps({"api_key": "wiped", "providers": []}), encoding="utf-8")
    (data_env["uploads"] / "abcd1234abcd1234.jpg").unlink()
    (data_env["skills"] / "my_skill.py").unlink()

    result = ei.restore_export_zip(zip_path)
    assert result["status"] == "ok"

    restored = json.loads(data_env["cfg_path"].read_text(encoding="utf-8"))
    assert restored["api_key"] == "hab_test"
    assert restored["providers"][0]["api_key"] == "sk-test"
    assert restored["users"]["profiles"]["alice"]["display_name"] == "Alice"
    assert restored["language"] == "ro"
    assert (data_env["data"] / "uploads" / "chat" / "alice" / "abcd1234abcd1234.jpg").is_file()
    assert (data_env["skills"] / "my_skill.py").is_file()

    conn = sqlite3.connect(str(data_env["db_path"]))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    conn.close()
    assert "memories" in tables
    assert "conversations" in tables


def test_restore_rejects_non_zip(tmp_path):
    bad = tmp_path / "x.bin"
    bad.write_bytes(b"not-a-zip")
    with pytest.raises(ValueError, match="ZIP"):
        ei.restore_export_zip(bad)


def test_chunked_db_upload_roundtrip(data_env, tmp_path):
    db_bytes = data_env["db_path"].read_bytes()
    # wipe live db
    data_env["db_path"].write_bytes(b"")
    start = ei.start_chunked_upload(size=len(db_bytes), filename="x.db", kind="db")
    mid = len(db_bytes) // 2 or 1
    ei.append_chunk(start["id"], 0, db_bytes[:mid])
    ei.append_chunk(start["id"], mid, db_bytes[mid:])
    result = ei.finish_chunked_upload(start["id"])
    assert result["status"] == "ok"
    assert data_env["db_path"].read_bytes()[:16].startswith(b"SQLite format 3")
