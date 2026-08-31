"""custom_components .py read/write — gated, preview, backup."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from services import homeassistant as ha


@pytest.fixture()
def config_root(tmp_path, monkeypatch):
    root = tmp_path / "config"
    root.mkdir()
    monkeypatch.setattr(ha, "_HA_CONFIG_OVERRIDE", root)
    return root


def test_py_outside_custom_components_refused(config_root):
    with pytest.raises(ValueError, match="outside custom_components"):
        ha._safe_config_path("scripts/foo.py", allow_py=True)


def test_py_requires_allow_flag(config_root):
    with pytest.raises(ValueError, match="custom_code"):
        ha._safe_config_path("custom_components/midea_ac/climate.py", allow_py=False)


def test_py_allowed_when_flag_on(config_root):
    path = ha._safe_config_path("custom_components/midea_ac/climate.py", allow_py=True)
    assert path.name == "climate.py"


def test_write_preview_then_backup(config_root, monkeypatch):
    monkeypatch.setattr(ha, "_cfg_allow_custom_py", lambda: True)
    target = config_root / "custom_components" / "midea_ac" / "climate.py"
    target.parent.mkdir(parents=True)
    target.write_text("old = 1\n", encoding="utf-8")

    preview = asyncio.run(ha._write_file({
        "path": "custom_components/midea_ac/climate.py",
        "content": "old = 2\n",
        "confirm": False,
        "change_summary": "fix fan_mode assert",
    }))
    assert "PREVIEW only" in preview
    assert "---" in preview or "old = 1" in preview or "+old = 2" in preview
    assert target.read_text(encoding="utf-8") == "old = 1\n"

    done = asyncio.run(ha._write_file({
        "path": "custom_components/midea_ac/climate.py",
        "content": "old = 2\n",
        "confirm": True,
        "change_summary": "fix fan_mode assert",
    }))
    assert "OK: wrote" in done
    assert "Backup:" in done
    assert target.read_text(encoding="utf-8") == "old = 2\n"
    bak = Path(str(target) + ".bak")
    assert bak.read_text(encoding="utf-8") == "old = 1\n"


def test_write_py_confirm_needs_summary(config_root, monkeypatch):
    monkeypatch.setattr(ha, "_cfg_allow_custom_py", lambda: True)
    target = config_root / "custom_components" / "x" / "a.py"
    target.parent.mkdir(parents=True)
    target.write_text("x\n", encoding="utf-8")
    out = asyncio.run(ha._write_file({
        "path": "custom_components/x/a.py",
        "content": "y\n",
        "confirm": True,
    }))
    assert "change_summary" in out
    assert target.read_text(encoding="utf-8") == "x\n"


def test_replace_in_file_preview_and_apply(config_root, monkeypatch):
    monkeypatch.setattr(ha, "_cfg_allow_custom_py", lambda: True)
    target = config_root / "custom_components" / "midea_ac" / "climate.py"
    target.parent.mkdir(parents=True)
    target.write_text(
        "class X:\n    @property\n    def fan_mode(self):\n"
        "        assert isinstance(x, int)\n        return x\n",
        encoding="utf-8",
    )
    old = "        assert isinstance(x, int)\n        return x\n"
    new = (
        "        if not isinstance(x, int):\n"
        "            return None\n"
        "        return x\n"
    )
    preview = asyncio.run(ha._replace_in_file({
        "path": "custom_components/midea_ac/climate.py",
        "old_text": old,
        "new_text": new,
        "confirm": False,
        "change_summary": "safe fan_mode",
    }))
    assert "PREVIEW only" in preview
    assert "assert isinstance" in preview or "-" in preview
    assert "assert isinstance(x, int)" in target.read_text(encoding="utf-8")

    done = asyncio.run(ha._replace_in_file({
        "path": "custom_components/midea_ac/climate.py",
        "old_text": old,
        "new_text": new,
        "confirm": True,
        "change_summary": "safe fan_mode",
    }))
    assert "OK: wrote" in done
    text = target.read_text(encoding="utf-8")
    assert "return None" in text
    assert "assert isinstance(x, int)" not in text
    assert Path(str(target) + ".bak").is_file()


def test_write_file_rejects_large_py_rewrite(config_root, monkeypatch):
    monkeypatch.setattr(ha, "_cfg_allow_custom_py", lambda: True)
    target = config_root / "custom_components" / "midea_ac" / "climate.py"
    target.parent.mkdir(parents=True)
    target.write_text("x = 1\n", encoding="utf-8")
    big = "x = 1\n" + ("# pad\n" * 10_000)
    out = asyncio.run(ha._write_file({
        "path": "custom_components/midea_ac/climate.py",
        "content": big,
        "confirm": False,
    }))
    assert "ha_replace_in_file" in out
    assert target.read_text(encoding="utf-8") == "x = 1\n"


def test_write_file_missing_path_hints_replace():
    out = asyncio.run(ha._write_file({"content": "x", "confirm": False}))
    assert "path is missing" in out
    assert "ha_replace_in_file" in out


def test_write_file_parse_error_hints_replace():
    out = asyncio.run(ha._write_file({
        "_parse_error": "Expecting ',' delimiter: line 1 column 80 (char 79)",
        "_raw_len": 12000,
    }))
    assert "truncated or invalid" in out
    assert "ha_replace_in_file" in out


def test_list_files_surfaces_custom_py_first(config_root, monkeypatch):
    monkeypatch.setattr(ha, "_cfg_allow_custom_py", lambda: True)
    # Many yaml files that would previously fill the 120-cap before custom_components
    for i in range(80):
        (config_root / f"zzz_pack_{i}.yaml").write_text("x: 1\n", encoding="utf-8")
    py = config_root / "custom_components" / "midea_ac" / "climate.py"
    py.parent.mkdir(parents=True)
    py.write_text("FAN=1\n", encoding="utf-8")

    out = asyncio.run(ha._list_files({"search": "midea"}))
    assert "custom_components/midea_ac/climate.py" in out


def test_read_missing_lists_packages(config_root, monkeypatch):
    monkeypatch.setattr(ha, "_cfg_allow_custom_py", lambda: True)
    (config_root / "custom_components" / "other_ac").mkdir(parents=True)
    out = asyncio.run(ha._read_file({"path": "custom_components/midea_ac/climate.py"}))
    assert "not found" in out
    assert "other_ac" in out


def test_ha_config_dir_prefers_homeassistant(tmp_path, monkeypatch):
    monkeypatch.setattr(ha, "_HA_CONFIG_OVERRIDE", None)
    monkeypatch.delenv("HASSAI_HA_CONFIG", raising=False)
    home = tmp_path / "homeassistant"
    addon = tmp_path / "config"
    home.mkdir()
    addon.mkdir()
    (home / "configuration.yaml").write_text("default_config:\n", encoding="utf-8")
    (home / "custom_components").mkdir()
    (addon / "options.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(
        ha,
        "_ha_config_dir",
        lambda: home if (home / "configuration.yaml").is_file() else addon,
    )
    assert ha._ha_config_dir() == home
