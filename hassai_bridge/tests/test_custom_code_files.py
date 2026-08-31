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
    monkeypatch.setattr(ha, "_HA_CONFIG", root)
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


def test_write_py_disabled(config_root, monkeypatch):
    monkeypatch.setattr(ha, "_cfg_allow_custom_py", lambda: False)
    out = asyncio.run(ha._write_file({
        "path": "custom_components/x/a.py",
        "content": "y\n",
        "confirm": False,
    }))
    assert "custom_code" in out or "Error" in out
