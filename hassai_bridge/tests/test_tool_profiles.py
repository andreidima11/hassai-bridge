"""Tests for intent-based tool profile filtering."""

from services import tool_profiles as tp


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name}}


LOCAL = {"type": "local", "base_url": "http://127.0.0.1:1234", "max_tokens": 2048}
CLOUD = {"type": "openai", "base_url": "https://api.openai.com/v1", "max_tokens": 2048}
CFG = {"performance": {"tool_profile": "auto"}}


def test_compact_for_local_provider():
    tools = [_tool("ha_list_entities"), _tool("ha_create_backup"), _tool("memory_search")]
    out, compact = tp.filter_chat_tools(
        tools,
        provider=LOCAL,
        cfg=CFG,
        user_text="stinge lumina living",
        route_klass="control",
    )
    names = {t["function"]["name"] for t in out}
    assert compact is True
    assert "ha_list_entities" in names
    assert "ha_create_backup" not in names
    assert "memory_search" in names


def test_full_profile_keeps_all_ha_tools():
    tools = [_tool("ha_list_entities"), _tool("ha_create_backup")]
    cfg = {"performance": {"tool_profile": "full"}}
    out, compact = tp.filter_chat_tools(
        tools,
        provider=LOCAL,
        cfg=cfg,
        user_text="stinge lumina",
        route_klass="control",
    )
    names = {t["function"]["name"] for t in out}
    assert compact is False
    assert names == {"ha_list_entities", "ha_create_backup"}


def test_frigate_dropped_without_keywords():
    tools = [_tool("frigate_events"), _tool("ha_get_state")]
    out, compact = tp.filter_chat_tools(
        tools,
        provider=LOCAL,
        cfg=CFG,
        user_text="stinge lumina",
        route_klass="simple",
    )
    names = {t["function"]["name"] for t in out}
    assert compact is True
    assert "frigate_events" not in names
    assert "ha_get_state" in names


def test_frigate_kept_when_mentioned():
    tools = [_tool("frigate_events"), _tool("ha_get_state")]
    out, _ = tp.filter_chat_tools(
        tools,
        provider=LOCAL,
        cfg=CFG,
        user_text="arată camera curte frigate",
        route_klass="simple",
    )
    names = {t["function"]["name"] for t in out}
    assert "frigate_events" in names


def test_cloud_provider_keeps_full_tools_without_eco():
    tools = [_tool("ha_list_entities"), _tool("ha_create_backup")]
    out, compact = tp.filter_chat_tools(
        tools,
        provider=CLOUD,
        cfg=CFG,
        user_text="aprinde lumina",
        route_klass="control",
    )
    names = {t["function"]["name"] for t in out}
    assert compact is False
    assert names == {"ha_list_entities", "ha_create_backup"}


def test_dynamic_profile_skips_local_compact():
    assert tp.tool_profile_mode({"performance": {"tool_profile": "dynamic"}}) == tp.PROFILE_DYNAMIC
    assert tp.should_compact_tools(LOCAL, {"performance": {"tool_profile": "dynamic"}}) is False


def test_openai_hard_caps_over_128_tools():
    tools = [_tool(f"ha_tool_{i}") for i in range(140)]
    # Map unknown ha_* names to entities via default tool_category fallback.
    tools.append(_tool("frigate_events"))
    tools.append(_tool("memory_search"))
    out, trimmed = tp.filter_chat_tools(
        tools,
        provider=CLOUD,
        cfg=CFG,
        user_text="arata ultima inregistrare video de la curte",
        route_klass="simple",
    )
    assert trimmed is True
    assert len(out) <= tp.OPENAI_MAX_TOOLS
    names = {t["function"]["name"] for t in out}
    assert "frigate_events" in names
    assert "memory_search" in names


def test_openai_full_profile_still_caps_at_128():
    tools = [_tool(f"ha_list_entities_{i}") for i in range(150)]
    cfg = {"performance": {"tool_profile": "full"}}
    out, trimmed = tp.filter_chat_tools(
        tools,
        provider=CLOUD,
        cfg=cfg,
        user_text="hello",
        route_klass="simple",
    )
    assert trimmed is True
    assert len(out) == tp.OPENAI_MAX_TOOLS


def test_frigate_kept_for_romanian_courtyard_video():
    tools = [
        _tool("frigate_events"),
        _tool("frigate_snapshot"),
        _tool("frigate_clip"),
        _tool("ha_get_state"),
    ]
    out, _ = tp.filter_chat_tools(
        tools,
        provider=LOCAL,
        cfg=CFG,
        user_text="Imi poti arata ultima inregistrare video de la curte",
        route_klass="simple",
    )
    names = {t["function"]["name"] for t in out}
    assert "frigate_events" in names
    assert "frigate_snapshot" in names
    assert "frigate_clip" in names


def test_local_history_limit():
    assert tp.effective_history_limit({"performance": {"history_limit": 10, "local_history_limit": 6}}, LOCAL) == 6
    assert tp.effective_history_limit({"performance": {"history_limit": 10}}, CLOUD) == 10


def test_ha_categories_simple_vs_deep():
    cfg = {}
    simple = tp.ha_categories_for_turn(cfg, "simple", compact=True)
    deep = tp.ha_categories_for_turn(cfg, "deep", compact=True)
    assert "entities" in simple and "control" in simple
    assert "automations" not in simple
    assert "automations" in deep


def test_create_automation_keeps_ha_create_tool_when_compact():
    tools = [
        _tool("ha_list_entities"),
        _tool("ha_call_service"),
        _tool("ha_create_automation"),
        _tool("ha_reload"),
    ]
    out, compact = tp.filter_chat_tools(
        tools,
        provider=LOCAL,
        cfg=CFG,
        user_text="creează o automatizare care stinge luminile la 23:00",
        route_klass="control",
    )
    names = {t["function"]["name"] for t in out}
    assert compact is True
    assert "ha_create_automation" in names
    assert "ha_reload" in names


def test_light_command_still_drops_create_automation():
    tools = [_tool("ha_call_service"), _tool("ha_create_automation")]
    out, _ = tp.filter_chat_tools(
        tools,
        provider=LOCAL,
        cfg=CFG,
        user_text="stinge lumina living",
        route_klass="control",
    )
    names = {t["function"]["name"] for t in out}
    assert "ha_call_service" in names
    assert "ha_create_automation" not in names
