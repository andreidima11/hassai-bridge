"""Tests for the tools that let the assistant control HASSAI Bridge itself."""

from __future__ import annotations

import asyncio
import json

import pytest

from services import bridge_tools as bt
from services import bridge_tool_access as bta


@pytest.fixture()
def cfg_env(tmp_path, monkeypatch):
    from core import config as core_cfg

    data = tmp_path / "data"
    data.mkdir()
    cfg_path = data / "config.json"
    cfg_path.write_text(json.dumps({
        "api_key": "hab_secret",
        "active_provider": "ds",
        "providers": [
            {"id": "ds", "name": "DeepSeek", "type": "deepseek",
             "api_key": "sk-secret", "model": "deepseek-chat"},
            {"id": "grok", "name": "Grok", "type": "grok",
             "api_key": "xai-secret", "model": "grok-4.6"},
        ],
        "searxng": {"enabled": False, "base_url": "http://x", "max_results": 5},
    }), encoding="utf-8")

    monkeypatch.setattr(core_cfg, "DATA_DIR", data)
    monkeypatch.setattr(core_cfg, "CONFIG_FILE", cfg_path)
    monkeypatch.setattr(core_cfg, "_config_cache", None)
    monkeypatch.setattr(core_cfg, "_config_mtime", 0.0)
    monkeypatch.setattr(core_cfg, "_config_last_check", 0.0)
    return cfg_path


def _load():
    from config import load_config

    return load_config()


# ── Gating ─────────────────────────────────────────

def test_all_groups_default_on():
    assert bta.merged_bridge_tools_config({}) == {"memory": True, "status": True, "control": True}


def test_status_group_hides_read_tools():
    names = {s["function"]["name"] for s in bt.build_tools({"bridge_tools": {"status": False}})}
    assert names == {"hassai_set_setting", "hassai_switch_provider"}


def test_control_group_hides_write_tools():
    names = {s["function"]["name"] for s in bt.build_tools({"bridge_tools": {"control": False}})}
    assert "hassai_set_setting" not in names
    assert "hassai_status" in names


def test_system_hint_states_the_addon_identity():
    hint = bt.system_hint({})
    assert "HASSAI Bridge" in hint
    assert "hassai_status" in hint
    assert "hassai_set_setting" in hint


def test_system_hint_drops_control_sentence_when_disabled():
    hint = bt.system_hint({"bridge_tools": {"control": False}})
    assert "hassai_set_setting" not in hint
    assert "hassai_status" in hint


# ── Settings ───────────────────────────────────────

def test_get_settings_redacts_secrets(cfg_env):
    out = bt._get_settings({"section": "all"}, _load())
    assert "hab_secret" not in out
    assert "sk-secret" not in out


def test_set_setting_writes_allowlisted_key(cfg_env):
    out = bt._set_setting({"path": "searxng.enabled", "value": "on"}, _load())
    assert "false" in out and "true" in out
    assert _load()["searxng"]["enabled"] is True


def test_set_setting_rejects_secrets(cfg_env):
    out = bt._set_setting({"path": "api_key", "value": "hab_evil"}, _load())
    assert out.startswith("Error")
    assert _load()["api_key"] == "hab_secret"


def test_set_setting_enforces_bounds(cfg_env):
    out = bt._set_setting({"path": "performance.agent_max_rounds", "value": 900}, _load())
    assert "between 2 and 32" in out


def test_set_setting_accepts_ha_tool_permissions(cfg_env):
    out = bt._set_setting({"path": "ha_tools.backups", "value": False}, _load())
    assert "Changed" in out
    assert _load()["ha_tools"]["backups"] is False


def test_set_setting_reports_noop(cfg_env):
    assert "already" in bt._set_setting({"path": "searxng.enabled", "value": False}, _load())


# ── Providers ──────────────────────────────────────

def test_list_providers_marks_active(cfg_env):
    out = bt._list_providers(_load())
    assert "DeepSeek" in out and "← active" in out
    assert "xai-secret" not in out


def test_switch_provider_by_name(cfg_env):
    out = bt._switch_provider({"provider": "grok"})
    assert "Grok" in out
    assert _load()["active_provider"] == "grok"


def test_switch_provider_unknown_lists_options(cfg_env):
    out = bt._switch_provider({"provider": "chatgpt"})
    assert out.startswith("Error")
    assert "DeepSeek" in out


def test_switch_model_and_eco(cfg_env):
    bt._switch_provider({"model": "deepseek-reasoner", "eco_mode": True})
    active = next(p for p in _load()["providers"] if p["id"] == "ds")
    assert active["model"] == "deepseek-reasoner"
    assert active["eco_mode"] is True


def test_run_tool_respects_toggle(cfg_env):
    out = asyncio.run(bt.run_tool(
        "hassai_set_setting",
        {"path": "language", "value": "ro"},
        cfg={"bridge_tools": {"control": False}},
    ))
    assert out.startswith("Error")


def test_run_tool_reports_settings(cfg_env):
    out = asyncio.run(bt.run_tool("hassai_get_settings", {"section": "searxng"}, cfg=_load()))
    assert "max_results" in out
