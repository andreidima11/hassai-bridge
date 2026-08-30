"""Light integration: expand_after_activate + mocked route_packs (no HTTP)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import pytest

from services import pack_router as pr
from services import toolkits as tk


def _tool(name: str) -> dict:
    return {"type": "function", "function": {"name": name, "description": name}}


CFG = {
    "performance": {"tool_profile": "dynamic"},
    "ha_tools": {
        "entities": True,
        "control": True,
        "automations": False,
        "backups": False,
        "hacs": False,
        "calendar": False,
        "helpers": False,
        "diagnostics": False,
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

CLOUD = {"type": "openai", "base_url": "https://api.openai.com/v1", "max_tokens": 2048}


@pytest.mark.asyncio
async def test_route_packs_trivial_skips_provider():
    with patch("services.providers.chat_completion", new_callable=AsyncMock) as mock_cc:
        out = await pr.route_packs("ok", {"entities": "x"}, provider=CLOUD, model="m")
        assert out["reason"] == "trivial"
        assert out["packs"] == set()
        mock_cc.assert_not_called()


@pytest.mark.asyncio
async def test_route_packs_parses_mock_completion():
    async def fake_cc(*args, **kwargs):
        return {
            "choices": [{
                "message": {
                    "content": '{"packs":["entities","control"],"confidence":0.92}',
                },
            }],
        }

    eligible = {"entities": "e", "control": "c", "frigate": "f"}
    with patch("services.providers.chat_completion", new=fake_cc):
        out = await pr.route_packs("turn off lights", eligible, provider=CLOUD, model="gpt")
    assert out["packs"] == {"entities", "control"}
    assert out["reason"] == "ok"


def test_expand_after_activate_then_resolve():
    tools = [
        _tool("media_list"),
        _tool("ha_list_entities"),
        _tool("ha_call_service"),
        _tool("hassai_status"),
    ]
    sid = "integ-activate-1"
    tk.clear_sticky(sid)
    effective, active, payload = tk.expand_after_activate(
        tools,
        cfg=CFG,
        packs=["entities"],
        session_id=sid,
        current_active=set(),
        provider=CLOUD,
    )
    data = json.loads(payload)
    assert "entities" in data["activated"]
    assert "ha_list_entities" in {t["function"]["name"] for t in effective}
    assert "entities" in active

    out2, active2, _ = tk.resolve_dynamic_tools(
        tools, cfg=CFG, session_id=sid, provider=CLOUD, primed_packs=set(),
    )
    assert "ha_list_entities" in {t["function"]["name"] for t in out2}
    assert "entities" in active2
    tk.clear_sticky(sid)
