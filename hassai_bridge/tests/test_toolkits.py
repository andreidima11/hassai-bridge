"""Tests for Dynamic toolkits (LLM-primed packs, media_write, sticky)."""

from services import toolkits as tk
from services import tool_profiles as tp


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name + " " * 80 + "extra detail."}}


CLOUD = {"type": "openai", "base_url": "https://api.openai.com/v1", "max_tokens": 2048}
CFG_ALL = {
    "performance": {"tool_profile": "dynamic"},
    "ha_tools": {
        "entities": True,
        "control": True,
        "automations": True,
        "backups": True,
        "hacs": True,
        "calendar": True,
        "helpers": True,
        "diagnostics": True,
        "registry": False,
        "integrations": False,
        "dashboards": False,
        "config_files": False,
        "addons": False,
        "updates": False,
        "restart": False,
        "network": False,
        "upload": False,
        "zigbee": False,
    },
    "bridge_tools": {"memory": True, "status": True, "control": True, "media": True},
}


def test_tool_profile_mode_accepts_dynamic():
    assert tp.tool_profile_mode({"performance": {"tool_profile": "dynamic"}}) == "dynamic"


def test_browser_and_enable_tools_are_core_in_dynamic():
    """Regression: pack=None tools must be is_core_tool or Dynamic drops them."""
    assert tk.is_core_tool("browser_interact") is True
    assert tk.is_core_tool("request_enable_tools") is True
    tools = [
        _tool("media_list"),
        _tool("hassai_status"),
        _tool("browser_interact"),
        _tool("request_enable_tools"),
    ]
    cfg = dict(CFG_ALL)
    cfg["bridge_tools"] = {**CFG_ALL["bridge_tools"], "browser": True}
    out, _, _ = tk.resolve_dynamic_tools(
        tools,
        cfg=cfg,
        session_id="",
        provider=CLOUD,
        primed_packs=set(),
    )
    names = {t["function"]["name"] for t in out}
    assert "browser_interact" in names
    assert "request_enable_tools" in names


def test_media_delete_not_core_requires_media_write_pack():
    tools = [
        _tool("media_list"),
        _tool("media_read"),
        _tool("media_delete"),
        _tool("hassai_status"),
    ]
    out, active, eligible = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        session_id="",
        provider=CLOUD,
        primed_packs=set(),
    )
    names = {t["function"]["name"] for t in out}
    assert "media_list" in names
    assert "media_read" in names
    assert "media_delete" not in names
    assert "media_write" in eligible
    assert tk.pack_for_tool("media_delete") == "media_write"

    out2, active2, _ = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        session_id="",
        provider=CLOUD,
        primed_packs={"media_write"},
    )
    names2 = {t["function"]["name"] for t in out2}
    assert "media_delete" in names2
    assert "media_write" in active2


def test_primed_packs_from_router_not_regex():
    tools = [
        _tool("media_list"),
        _tool("ha_list_entities"),
        _tool("ha_call_service"),
        _tool("ha_create_backup"),
        _tool("frigate_events"),
    ]
    # No priming → lean
    out, active, _ = tk.resolve_dynamic_tools(
        tools, cfg=CFG_ALL, session_id="", provider=CLOUD, primed_packs=set(),
    )
    names = {t["function"]["name"] for t in out}
    assert "ha_list_entities" not in names
    assert "frigate_events" not in names
    assert active == set()

    out2, active2, _ = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        session_id="",
        provider=CLOUD,
        primed_packs={"entities", "control"},
    )
    names2 = {t["function"]["name"] for t in out2}
    assert "ha_list_entities" in names2
    assert "ha_call_service" in names2
    assert "ha_create_backup" not in names2
    assert "frigate_events" not in names2


def test_eligible_includes_settings_off_packs():
    """OFF packs stay eligible so activate/tool call can open Approve."""
    tools = [
        _tool("ha_list_entities"),
        _tool("ha_call_service"),
        _tool("ha_create_backup"),
        _tool("ha_update_entity"),
        _tool("hassai_set_setting"),
        _tool("frigate_events"),
        _tool("media_list"),
        _tool("media_delete"),
    ]
    eligible = tk.eligible_packs(CFG_ALL, tools, frigate_available=True)
    assert "entities" in eligible
    assert "registry" in eligible
    assert "OFF in Settings" in eligible["registry"]
    assert "media_write" in eligible
    assert "media" not in eligible


def test_activate_allows_settings_off_pack_at_toolkit_layer():
    """Toolkit layer allows OFF packs; chat.py gates with Approve before expand."""
    tools = [
        _tool("media_list"),
        _tool("ha_list_entities"),
        _tool("ha_update_entity"),
        _tool("hassai_status"),
    ]
    sid = "tk-test-activate-off"
    tk.clear_sticky(sid)
    effective, active, payload = tk.expand_after_activate(
        tools,
        cfg=CFG_ALL,
        packs=["registry", "entities"],
        session_id=sid,
        current_active=set(),
        provider=CLOUD,
    )
    import json
    data = json.loads(payload)
    assert "entities" in data["activated"]
    assert "registry" in data["activated"]
    assert "ha_update_entity" in {t["function"]["name"] for t in effective}
    tk.clear_sticky(sid)


def test_shorten_and_estimate():
    tools = [_tool("ha_list_entities")]
    short = tk.shorten_tool_descriptions(tools, max_len=40)
    assert len(short[0]["function"]["description"]) <= 40
    assert tk.estimate_tools_tokens(short) <= tk.estimate_tools_tokens(tools)
