"""Unit tests for Cursor-style tool approval gate."""

from __future__ import annotations

import asyncio

import pytest

from services import tool_approval as ta


def test_risky_tools_include_ha_and_extras():
    assert ta.is_risky("ha_call_service")
    assert ta.is_risky("ha_write_file")
    assert ta.is_risky("media_delete")
    assert ta.is_risky("browser_interact")
    assert ta.is_risky("hassai_set_setting")
    assert not ta.is_risky("ha_get_state")
    assert not ta.is_risky("search_web")
    # Per-call UI gate removed — Settings-disabled groups use enable flow instead.
    assert ta.needs_approval("ha_call_service") is False
    assert ta.needs_approval("browser_interact") is False


def test_inject_confirm():
    assert ta.inject_confirm({"entity_id": "light.x"})["confirm"] is True
    assert ta.inject_confirm(None)["confirm"] is True


def test_args_preview_prefers_keys():
    preview = ta.args_preview(
        "ha_call_service",
        {"domain": "light", "service": "turn_on", "entity_id": "light.kitchen", "noise": {"a": 1}},
    )
    assert "domain=light" in preview
    assert "service=turn_on" in preview
    assert "entity_id=light.kitchen" in preview


def test_conversation_allow_scope():
    ta.clear_conversation("sess-1")
    assert not ta.is_conversation_allowed("sess-1", "ha_call_service", {"domain": "light", "service": "turn_on"})
    ta.grant_conversation("sess-1", "ha_call_service", {"domain": "light", "service": "turn_on"})
    assert ta.is_conversation_allowed("sess-1", "ha_call_service", {"domain": "light", "service": "turn_on"})
    assert ta.is_conversation_allowed("sess-1", "ha_call_service", {"domain": "switch", "service": "turn_on"})
    ta.clear_conversation("sess-1")


@pytest.mark.asyncio
async def test_approve_resolves_future():
    fut = ta.register_pending(
        "trace-a",
        "call-1",
        name="ha_call_service",
        args={"domain": "light", "service": "turn_on"},
        detail="light.turn_on",
    )
    assert not fut.done()
    result = ta.resolve("trace-a", "call-1", decision="approve", scope="once")
    assert result["ok"] is True
    decision = await ta.wait_decision(fut, timeout=1)
    assert decision["decision"] == "approve"


@pytest.mark.asyncio
async def test_decline_resolves_future():
    fut = ta.register_pending(
        "trace-b",
        "call-2",
        name="media_delete",
        args={"path": "/media/x"},
    )
    ta.resolve("trace-b", "call-2", decision="decline")
    decision = await ta.wait_decision(fut, timeout=1)
    assert decision["decision"] == "decline"


@pytest.mark.asyncio
async def test_conversation_scope_grants_on_approve():
    ta.clear_conversation("sess-2")
    fut = ta.register_pending(
        "trace-c",
        "call-3",
        name="browser_interact",
        args={"action": "screenshot"},
    )
    ta.resolve(
        "trace-c",
        "call-3",
        decision="approve",
        scope="conversation",
        session_id="sess-2",
    )
    await ta.wait_decision(fut, timeout=1)
    assert ta.is_conversation_allowed("sess-2", "browser_interact", {"action": "open"})
    ta.clear_conversation("sess-2")


@pytest.mark.asyncio
async def test_cancel_trace_cancels_future():
    fut = ta.register_pending("trace-d", "call-4", name="ha_reload", args={})
    ta.cancel_trace("trace-d")
    assert fut.cancelled() or fut.done()


@pytest.mark.asyncio
async def test_timeout_auto_decline(monkeypatch):
    monkeypatch.setattr(ta, "APPROVAL_TIMEOUT_SEC", 0.05)
    fut = ta.register_pending("trace-e", "call-5", name="ha_write_file", args={"path": "x"})
    decision = await ta.wait_decision(fut, timeout=0.05)
    assert decision["decision"] == "timeout"
