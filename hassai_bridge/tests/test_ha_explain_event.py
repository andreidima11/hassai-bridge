"""Tests for background-task RO copy and ha_explain_event."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from services.background_tasks import i18n as bg_i18n
from services.background_tasks import worker
from services import ha_explain_event as hexp


def test_bg_messages_romanian():
    task = {"title": "Monitor light", "kind": "monitor_entities"}
    result = {
        "entity_ids": ["light.x"],
        "observed_seconds": 30,
        "observation_count": 2,
        "unavailable_intervals": 0,
        "total_unavailable_seconds": 0,
        "total_gap_seconds": 0,
        "last_observed_state": {"light.x": "on"},
    }
    msg = worker.format_monitor_message(task, result, lang="ro")
    assert "finalizat" in msg.lower() or "Finalizat" in msg
    assert "Urmărit" in msg or "urmărit" in msg.lower()

    wait_task = {"title": "Wait door", "kind": "wait_for_state"}
    wait_ok = worker.format_wait_message(
        wait_task,
        {
            "matched": True,
            "entity_id": "binary_sensor.door",
            "state": "on",
            "waited_seconds": 12,
        },
        lang="ro",
    )
    assert "condiție" in wait_ok.lower() or "îndeplinită" in wait_ok.lower()

    assert bg_i18n.lang_from_cfg({"language": "ro"}) == "ro"
    created = bg_i18n.t("ro", "created_wait", title="T", entity_id="light.a", state="on")
    assert "programat" in created.lower()
    assert "închizi" in created.lower() or "chatul" in created.lower()


def test_explain_find_transition_last_on():
    base = datetime(2026, 9, 13, 0, 0, tzinfo=timezone.utc)
    rows = [
        {"state": "off", "last_changed": (base).isoformat(), "entity_id": "light.x", "context": {}},
        {
            "state": "on",
            "last_changed": (base + timedelta(minutes=5)).isoformat(),
            "entity_id": "light.x",
            "context": {"id": "ctx1", "parent_id": "p1", "user_id": None},
        },
        {
            "state": "off",
            "last_changed": (base + timedelta(minutes=10)).isoformat(),
            "entity_id": "light.x",
            "context": {},
        },
        {
            "state": "on",
            "last_changed": (base + timedelta(minutes=15)).isoformat(),
            "entity_id": "light.x",
            "context": {"id": "ctx2"},
        },
    ]
    prev, cur = hexp._find_transition(rows, from_state="off", to_state="on", start=None, end=None)
    assert cur["context"]["id"] == "ctx2"
    assert prev["state"] == "off"


def test_explain_confirmed_automation():
    cur = {
        "state": "on",
        "last_changed": "2026-09-13T01:00:00+00:00",
        "context": {"id": "abc", "parent_id": "parent1", "user_id": None},
    }
    prev = {"state": "off", "last_changed": "2026-09-13T00:59:00+00:00"}
    report = hexp.build_report(
        entity_id="light.banda",
        prev=prev,
        cur=cur,
        logbook=[{
            "when": "2026-09-13T01:00:00+00:00",
            "entity_id": "automation.lumina_noapte",
            "domain": "automation",
            "message": "triggered",
            "name": "Lumină de noapte",
        }],
        traces_allowed=True,
        matched_trace={"item_id": "lumina_noapte", "run_id": "r1", "domain": "automation"},
        full_trace={"trigger": {"entity_id": "binary_sensor.motion"}, "trace": {"light.banda": True}},
        time_near_auto=None,
        lang="en",
    )
    assert report["cause_type"] == "automation"
    assert report["confidence"] == "confirmed"
    assert report["change"] == "off → on"
    assert any("automation" in e.lower() or "lumina_noapte" in e for e in report["evidence"])


def test_explain_unknown_no_context_ro():
    cur = {
        "state": "on",
        "last_changed": "2026-09-13T01:00:00+00:00",
        "context": {},
    }
    prev = {"state": "off"}
    report = hexp.build_report(
        entity_id="light.banda",
        prev=prev,
        cur=cur,
        logbook=[],
        traces_allowed=True,
        matched_trace=None,
        full_trace=None,
        time_near_auto=None,
        lang="ro",
    )
    assert report["cause_type"] == "unknown"
    assert report["confidence"] == "unknown"
    assert "nu pot determina" in report["summary"].lower()
    assert report["missing_evidence"]


@pytest.mark.asyncio
async def test_explain_run_tool_mocked(monkeypatch):
    base = datetime.now(timezone.utc)
    rows = [
        {
            "entity_id": "light.x",
            "state": "off",
            "last_changed": (base - timedelta(minutes=2)).isoformat(),
            "context": {},
        },
        {
            "entity_id": "light.x",
            "state": "on",
            "last_changed": (base - timedelta(minutes=1)).isoformat(),
            "context": {"id": "c1", "parent_id": "p1"},
        },
    ]

    async def fake_hist(entity_id, start, end):
        return rows

    async def fake_log(entity_id, start, end):
        return [{
            "when": (base - timedelta(minutes=1)).isoformat(),
            "entity_id": "automation.night",
            "domain": "automation",
            "message": "Night light triggered",
        }]

    async def fake_list(domain, item_id=None):
        return [{
            "item_id": "night",
            "run_id": "run1",
            "context_id": "c1",
            "timestamp": (base - timedelta(minutes=1)).isoformat(),
        }]

    async def fake_get(domain, item_id, run_id):
        return {"trigger": {"description": "motion"}, "action": "light.turn_on light.x"}

    monkeypatch.setattr(hexp, "_fetch_history", fake_hist)
    monkeypatch.setattr(hexp, "_fetch_logbook", fake_log)
    monkeypatch.setattr(hexp, "_list_traces", fake_list)
    monkeypatch.setattr(hexp, "_get_trace", fake_get)
    monkeypatch.setattr(
        "services.ha_tool_access.enabled_categories",
        lambda cfg: {"entities", "automations"},
    )

    out = await hexp.run_tool(
        {"entity_id": "light.x", "event": "turned_on"},
        cfg={"language": "en", "ha_tools": {"entities": True, "automations": True}},
    )
    data = json.loads(out)
    assert data["ok"] is True
    assert data["confidence"] == "confirmed"
    assert data["cause_type"] == "automation"


def test_ha_explain_registered():
    from services import homeassistant as ha
    from services import ha_tool_access as hta
    from services import entity_tools as et

    assert "ha_explain_event" in ha._TOOL_SPECS
    assert "ha_explain_event" in ha._HANDLERS
    assert hta.tool_category("ha_explain_event") == "entities"
    assert "ha_explain_event" in et.HA_ENTITY_TOOLS
