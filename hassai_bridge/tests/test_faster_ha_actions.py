"""Faster HA actions: control priming, default verify, parallel tools."""

from __future__ import annotations

import asyncio

import pytest

from routers import chat as chat_mod
from services import entity_tools as et
from services import homeassistant as ha
from services import tool_awareness as taw


def test_control_action_packs_entities_and_control():
    assert taw.control_action_packs("aprinde lumina") == {"entities", "control"}
    assert "frigate" in taw.control_action_packs("pornește camera living")


def test_skip_pack_router_for_short_clear_control():
    assert taw.should_skip_pack_router_for_control("sting 2 lumini")
    assert taw.should_skip_pack_router_for_control("turn on kitchen light")
    # Long / ambiguous keep the router
    long = "please turn on the kitchen light and also check why " + ("x " * 40)
    assert not taw.should_skip_pack_router_for_control(long)
    # Automation edit and explain intents must not skip
    assert not taw.should_skip_pack_router_for_control("creează o automatizare pentru lumină")
    assert not taw.should_skip_pack_router_for_control("De ce s-a aprins lumina?")


@pytest.mark.asyncio
async def test_call_service_defaults_verify_when_entity_present(monkeypatch):
    calls = {"core": 0, "state": []}

    async def fake_core(method, path, json_body=None):
        calls["core"] += 1
        return [{"entity_id": "light.kitchen"}]

    async def fake_get_state(args):
        calls["state"].append(args["entity_id"])
        return f"{args['entity_id']}: state=on"

    monkeypatch.setattr(ha, "_core", fake_core)
    monkeypatch.setattr(ha, "_get_state", fake_get_state)

    out = await ha._call_service({
        "domain": "light",
        "service": "turn_on",
        "entity_id": "light.kitchen",
    })
    assert "OK: called light.turn_on" in out
    assert "verify:" in out
    assert "light.kitchen: state=on" in out
    assert calls["state"] == ["light.kitchen"]


@pytest.mark.asyncio
async def test_call_service_verify_false_skips(monkeypatch):
    calls = {"state": 0}

    async def fake_core(method, path, json_body=None):
        return []

    async def fake_get_state(args):
        calls["state"] += 1
        return "should-not-run"

    monkeypatch.setattr(ha, "_core", fake_core)
    monkeypatch.setattr(ha, "_get_state", fake_get_state)

    out = await ha._call_service({
        "domain": "light",
        "service": "turn_off",
        "entity_id": "light.kitchen",
        "verify": False,
    })
    assert "verify:" not in out
    assert calls["state"] == 0


@pytest.mark.asyncio
async def test_call_service_verifies_entity_id_list(monkeypatch):
    seen: list[str] = []

    async def fake_core(method, path, json_body=None):
        return []

    async def fake_get_state(args):
        seen.append(args["entity_id"])
        return f"{args['entity_id']}: ok"

    monkeypatch.setattr(ha, "_core", fake_core)
    monkeypatch.setattr(ha, "_get_state", fake_get_state)

    out = await ha._call_service({
        "domain": "light",
        "service": "turn_on",
        "data": {"entity_id": ["light.a", "light.b"]},
    })
    assert "verify:" in out
    assert seen == ["light.a", "light.b"]


@pytest.mark.asyncio
async def test_parallel_tools_preserve_order(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    order: list[str] = []

    async def fake_invoke(fn_name, args, **kwargs):
        order.append(f"start:{fn_name}")
        if fn_name == "ha_call_service" and args.get("entity_id") == "light.slow":
            started.set()
            await release.wait()
        else:
            await started.wait()
            release.set()
        order.append(f"done:{fn_name}:{args.get('entity_id')}")
        return f"ok:{args.get('entity_id')}", False

    monkeypatch.setattr(chat_mod, "_invoke_internal_tool", fake_invoke)
    monkeypatch.setattr(chat_mod, "_is_internal_tool", lambda name, cfg: True)
    monkeypatch.setattr(
        chat_mod, "_tool_needs_interactive_gate", lambda *a, **k: False
    )

    augmented: list = []
    events: list = []

    async def on_event(ev):
        events.append(ev)

    tool_calls = [
        {
            "id": "c1",
            "function": {
                "name": "ha_call_service",
                "arguments": '{"domain":"light","service":"turn_on","entity_id":"light.slow"}',
            },
        },
        {
            "id": "c2",
            "function": {
                "name": "ha_call_service",
                "arguments": '{"domain":"light","service":"turn_on","entity_id":"light.fast"}',
            },
        },
    ]
    await chat_mod._append_internal_tool_results(
        augmented,
        tool_calls,
        search_enabled=False,
        fingerprints=[],
        on_event=on_event,
        cfg={},
        session_id="s1",
    )

    assert [m["tool_call_id"] for m in augmented] == ["c1", "c2"]
    assert [m["content"] for m in augmented] == ["ok:light.slow", "ok:light.fast"]
    starts = [i for i, x in enumerate(order) if x.startswith("start:")]
    dones = [i for i, x in enumerate(order) if x.startswith("done:")]
    assert len(starts) == 2 and len(dones) == 2
    # Both started before either finished → parallel, not serial
    assert max(starts) < min(dones)


def test_prompts_nudge_same_turn_multi_call_and_inband_verify():
    full = et.render_ha_agent_prompt("", ["ha_list_entities", "ha_call_service"], compact=False)
    compact = et.render_ha_agent_prompt("", ["ha_list_entities", "ha_call_service"], compact=True)
    assert "SAME turn" in full or "same turn" in full.lower()
    assert "verified in the same call" in full or "verified in ha_call_service" in full
    assert "same turn" in compact.lower()
    assert "skip a separate ha_get_state" in compact.lower() or "verified in ha_call_service" in compact
