"""Dynamic toolkits — pack gate, hot-path, activate, sticky, OpenAI cap."""

from services import toolkits as tk
from services import tool_profiles as tp


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name}}


def _ha_tools(*names: str) -> list[dict]:
    return [_tool(n) for n in names]


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
    assert tp.should_compact_tools(CLOUD, {"performance": {"tool_profile": "dynamic"}}) is False


def test_eligible_respects_ha_toggles():
    tools = _ha_tools(
        "ha_list_entities",
        "ha_call_service",
        "ha_create_backup",
        "ha_update_entity",
    ) + [
        _tool("hassai_set_setting"),
        _tool("frigate_events"),
        _tool("media_list"),
        _tool("memory_search"),
        _tool("hassai_status"),
    ]
    eligible = tk.eligible_packs(CFG_ALL, tools, frigate_available=True)
    assert "entities" in eligible
    assert "control" in eligible
    assert "backups" in eligible
    assert "registry" not in eligible  # disabled in CFG_ALL
    assert "frigate" in eligible
    assert "bridge_write" in eligible
    assert "media" not in eligible  # media is core, not a pack


def test_core_includes_media_and_activate():
    tools = [
        _tool("media_list"),
        _tool("media_read"),
        _tool("media_delete"),
        _tool("memory_search"),
        _tool("hassai_status"),
        _tool("ha_list_entities"),
        _tool("ha_call_service"),
        _tool("frigate_events"),
    ]
    out, active, eligible = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        user_text="hello there",
        route_klass="simple",
        session_id="",
        provider=CLOUD,
        frigate_available=True,
    )
    names = {t["function"]["name"] for t in out}
    assert tk.ACTIVATE_TOOL in names
    assert "media_list" in names
    assert "media_read" in names
    assert "media_delete" in names
    assert "memory_search" in names
    assert "hassai_status" in names
    assert "ha_list_entities" not in names  # not primed on chatty simple
    assert "frigate_events" not in names
    assert active == set()


def test_core_omits_media_when_not_assembled():
    """When bridge_tools.media is off, chat does not put media_* in all_tools."""
    tools = [
        _tool("memory_search"),
        _tool("hassai_status"),
        _tool("ha_list_entities"),
    ]
    out, _, _ = tk.resolve_dynamic_tools(
        tools,
        cfg={**CFG_ALL, "bridge_tools": {**CFG_ALL["bridge_tools"], "media": False}},
        user_text="hello",
        route_klass="simple",
        session_id="",
        provider=CLOUD,
    )
    names = {t["function"]["name"] for t in out}
    assert "media_list" not in names
    assert "media_read" not in names
    assert tk.ACTIVATE_TOOL in names


def test_hot_path_primes_control_on_light_command():
    tools = [
        _tool("media_list"),
        _tool("ha_list_entities"),
        _tool("ha_call_service"),
        _tool("ha_create_backup"),
        _tool("frigate_events"),
    ]
    out, active, _ = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        user_text="stinge lumina living",
        route_klass="control",
        session_id="",
        provider=CLOUD,
    )
    names = {t["function"]["name"] for t in out}
    assert "ha_list_entities" in names
    assert "ha_call_service" in names
    assert "ha_create_backup" not in names
    assert "frigate_events" not in names
    assert "entities" in active and "control" in active


def test_activate_refuses_disabled_pack():
    tools = [
        _tool("media_list"),
        _tool("ha_list_entities"),
        _tool("ha_update_entity"),  # registry — disabled
        _tool("hassai_status"),
    ]
    sid = "tk-test-activate-deny"
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
    assert "registry" in data["denied"]
    assert "registry" not in active
    names = {t["function"]["name"] for t in effective}
    assert "ha_list_entities" in names
    assert "ha_update_entity" not in names
    tk.clear_sticky(sid)


def test_sticky_keeps_packs_across_resolve():
    tools = [
        _tool("media_list"),
        _tool("ha_list_entities"),
        _tool("ha_call_service"),
        _tool("ha_create_backup"),
    ]
    sid = "tk-test-sticky"
    tk.clear_sticky(sid)
    tk.set_sticky(sid, {"backups"})
    out, active, _ = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        user_text="ok",
        route_klass="simple",
        session_id=sid,
        provider=CLOUD,
    )
    assert "backups" in active
    names = {t["function"]["name"] for t in out}
    assert "ha_create_backup" in names
    tk.clear_sticky(sid)


def test_dynamic_caps_at_128_openai():
    tools = [_tool("media_list"), _tool("hassai_status")]
    tools += [_tool(f"ha_list_entities_{i}") for i in range(140)]
    # Map synthetic names via pack_for_tool → entities default for unknown ha_
    # pack_for_tool uses hta.tool_category which defaults unknown ha_* to entities
    out, _, _ = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        user_text="stinge lumina",
        route_klass="control",
        session_id="",
        provider=CLOUD,
    )
    assert len(out) <= tp.OPENAI_MAX_TOOLS
    names = {t["function"]["name"] for t in out}
    assert tk.ACTIVATE_TOOL in names or len(out) == tp.OPENAI_MAX_TOOLS


def test_frigate_hot_path():
    tools = [
        _tool("media_list"),
        _tool("ha_get_state"),
        _tool("frigate_events"),
        _tool("frigate_snapshot"),
    ]
    out, active, _ = tk.resolve_dynamic_tools(
        tools,
        cfg=CFG_ALL,
        user_text="arată camera curte frigate",
        route_klass="simple",
        session_id="",
        provider=CLOUD,
        frigate_available=True,
    )
    names = {t["function"]["name"] for t in out}
    assert "frigate" in active
    assert "frigate_events" in names
    assert "frigate_snapshot" in names


def test_tool_inactive_message_suggests_activate():
    msg = tk.tool_inactive_message("ha_create_backup", {"backups": "Supervisor backups"})
    assert "activate_toolkits" in msg
    assert "backups" in msg


def test_shorten_tool_descriptions_keeps_params_and_activate():
    long_desc = (
        "List every entity in Home Assistant with optional domain filter. "
        "Use this before calling services. Always prefer this over guessing entity ids."
    )
    tools = [
        {
            "type": "function",
            "function": {
                "name": "activate_toolkits",
                "description": "Available packs:\n- entities: Read entities",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "ha_list_entities",
                "description": long_desc,
                "parameters": {
                    "type": "object",
                    "properties": {"domain": {"type": "string"}},
                    "required": [],
                },
            },
        },
    ]
    out = tk.shorten_tool_descriptions(tools, max_len=80)
    by = {t["function"]["name"]: t["function"] for t in out}
    assert by["activate_toolkits"]["description"].startswith("Available packs:")
    assert len(by["ha_list_entities"]["description"]) <= 80
    assert "domain" in by["ha_list_entities"]["parameters"]["properties"]
    assert tk.estimate_tools_tokens(out) < tk.estimate_tools_tokens(tools)


def test_estimate_tools_tokens_empty():
    assert tk.estimate_tools_tokens(None) == 0
    assert tk.estimate_tools_tokens([]) == 0
