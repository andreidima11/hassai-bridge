"""Unit tests for habit scoring and recommendation chip builders."""

import asyncio
from unittest.mock import AsyncMock, patch

from services import habit_watcher as hw
from services import recommendations as recs


def test_score_logbook_counts_manual_on():
    entries = [
        {
            "entity_id": "light.living",
            "state": "on",
            "when": "2026-03-01T19:30:00+00:00",
            "context_user_id": "user-1",
            "name": "Living",
        },
        {
            "entity_id": "light.living",
            "state": "on",
            "when": "2026-03-02T19:10:00+00:00",
            "context_user_id": "user-1",
        },
        {
            "entity_id": "light.hall",
            "state": "on",
            "when": "2026-03-01T20:00:00+00:00",
            "context_parent_id": "auto-1",
        },
        {
            "entity_id": "sensor.temp",
            "state": "on",
            "when": "2026-03-01T19:00:00+00:00",
            "context_user_id": "user-1",
        },
    ]
    data = hw.score_logbook(entries)
    lights = {r["entity_id"]: r for r in data["lights"]}
    assert "light.living" in lights
    assert lights["light.living"]["count"] == 2
    assert lights["light.living"]["periods"]["evening"] == 2
    assert "light.hall" not in lights
    assert "sensor.temp" not in lights


def test_score_promotes_bulb_to_parent_group():
    states = [
        {
            "entity_id": "light.ambient_dormitor",
            "state": "off",
            "attributes": {
                "friendly_name": "Lumini ambientale dormitor 2",
                "entity_id": ["light.dormitor_bec_1", "light.dormitor_bec_2", "light.dormitor_bec_3"],
            },
        },
        {
            "entity_id": "light.dormitor_bec_1",
            "state": "off",
            "attributes": {"friendly_name": "Lampa dormitor #2 - bec 1"},
        },
    ]
    entries = [
        {
            "entity_id": "light.dormitor_bec_1",
            "state": "on",
            "when": "2026-03-01T19:30:00+00:00",
            "context_user_id": "user-1",
        },
        {
            "entity_id": "light.dormitor_bec_1",
            "state": "on",
            "when": "2026-03-02T20:00:00+00:00",
            "context_user_id": "user-1",
        },
    ]
    data = hw.score_logbook(entries, states=states)
    ids = [r["entity_id"] for r in data["lights"]]
    assert "light.ambient_dormitor" in ids
    assert "light.dormitor_bec_1" not in ids


def test_score_covers_and_pair_contact():
    states = [
        {
            "entity_id": "switch.poarta_auto",
            "state": "off",
            "attributes": {"friendly_name": "Poarta auto"},
        },
        {
            "entity_id": "binary_sensor.poarta_contact",
            "state": "off",
            "attributes": {"friendly_name": "Poarta contact", "device_class": "garage_door"},
        },
    ]
    registry = {
        "switch.poarta_auto": {"device_id": "dev1", "area_id": "exterior"},
        "binary_sensor.poarta_contact": {"device_id": "dev1", "area_id": "exterior"},
    }
    entries = [
        {
            "entity_id": "switch.poarta_auto",
            "state": "on",
            "when": "2026-03-01T18:00:00+00:00",
            "context_user_id": "u",
        },
        {
            "entity_id": "switch.poarta_auto",
            "state": "off",
            "when": "2026-03-01T18:05:00+00:00",
            "context_user_id": "u",
        },
    ]
    data = hw.score_logbook(entries, states=states, registry=registry, area_labels={"exterior": "Exterior"})
    assert data["covers"]
    gate = data["covers"][0]
    assert gate["entity_id"] == "switch.poarta_auto"
    assert gate["contact_entity_id"] == "binary_sensor.poarta_contact"
    assert gate["open_count"] == 1
    assert gate["close_count"] == 1


def test_top_lights_prefers_period_score():
    habits = {
        "lights": [
            {
                "entity_id": "light.a",
                "name": "A",
                "count": 10,
                "kind": "group",
                "member_ids": ["light.a1", "light.a2"],
                "periods": {"morning": 0, "day": 0, "evening": 1, "night": 0},
            },
            {
                "entity_id": "light.b",
                "name": "B",
                "count": 3,
                "kind": "group",
                "member_ids": ["light.b1", "light.b2"],
                "periods": {"morning": 0, "day": 0, "evening": 5, "night": 0},
            },
        ]
    }
    top = hw.top_lights_for_period(habits, period="evening", limit=2)
    assert top[0]["entity_id"] == "light.b"


def test_period_for_hour():
    assert hw._period_for_hour(7) == "morning"
    assert hw._period_for_hour(14) == "day"
    assert hw._period_for_hour(20) == "evening"
    assert hw._period_for_hour(1) == "night"


def test_classify_smalltalk_intent():
    assert recs.classify_turn_intent(user_text="Ce faci?") == "smalltalk"
    assert recs.classify_turn_intent(user_text="hello") == "smalltalk"


def test_build_followups_smalltalk_no_hallway():
    with patch.object(recs, "enabled", return_value=True), patch(
        "services.recommendations.load_config", return_value={"recommendations": {"enabled": True}}
    ):
        chips = recs.build_followups(lang="ro", user_text="Ce faci?", assistant_text="Bine, tu?")
    labels = " ".join(c["label"].lower() for c in chips)
    assert "vremea" in labels or "status" in labels
    assert "hol" not in labels


def test_build_followups_light_same_area_not_hallway():
    habits = {
        "lights": [
            {
                "entity_id": "light.living",
                "name": "Living",
                "count": 5,
                "kind": "group",
                "area_id": "living",
                "member_ids": ["light.l1", "light.l2"],
                "periods": {"evening": 5, "morning": 0, "day": 0, "night": 0},
            },
            {
                "entity_id": "light.seara_living",
                "name": "Lumini seara living",
                "count": 4,
                "kind": "group",
                "area_id": "living",
                "member_ids": ["light.s1", "light.s2"],
                "periods": {"evening": 4, "morning": 0, "day": 0, "night": 0},
            },
            {
                "entity_id": "light.hol",
                "name": "Bec hol",
                "count": 2,
                "kind": "light",
                "area_id": "hall",
                "periods": {"evening": 2, "morning": 0, "day": 0, "night": 0},
            },
        ]
    }
    tools = [{
        "name": "ha_call_service",
        "arguments": '{"entity_id":"light.living","service":"turn_on"}',
    }]
    with patch.object(recs, "enabled", return_value=True), patch(
        "services.recommendations.load_config", return_value={"recommendations": {"enabled": True}}
    ), patch.object(hw, "current_period", return_value="evening"):
        chips = recs.build_followups(
            lang="ro",
            user_text="Aprinde living",
            assistant_text="Am aprins Living.",
            tool_calls=tools,
            habits=habits,
        )
    labels = " ".join(c["label"].lower() for c in chips)
    assert "hol" not in labels
    assert "seara" in labels or "stinge" in labels or "living" in labels


def test_build_followups_disabled():
    with patch.object(recs, "enabled", return_value=False):
        assert recs.build_followups(lang="en", assistant_text="hi", tools_used=[]) == []


def test_house_status_label_ro():
    assert recs._t("ro", "house_status") == "Status casă"


def test_build_empty_recs_gate_open_close():
    habits = {
        "updated_at": 1,
        "meta_version": 2,
        "lights": [],
        "covers": [{
            "entity_id": "switch.poarta_auto",
            "name": "Poarta auto",
            "open_count": 3,
            "close_count": 2,
            "contact_entity_id": "binary_sensor.poarta_contact",
            "periods": {"evening": 3, "morning": 0, "day": 0, "night": 0},
        }],
        "scenes": [],
    }
    states = {
        "switch.poarta_auto": {"entity_id": "switch.poarta_auto", "state": "off"},
        "binary_sensor.poarta_contact": {
            "entity_id": "binary_sensor.poarta_contact",
            "state": "on",
            "attributes": {"device_class": "garage_door"},
        },
    }

    async def _run():
        with patch.object(recs, "enabled", return_value=True), patch(
            "services.recommendations.load_config",
            return_value={"recommendations": {"enabled": True}, "frigate": {"enabled": False}},
        ), patch.object(recs, "_states_map", new=AsyncMock(return_value=states)), patch.object(
            recs, "_has_energy_stats", new=AsyncMock(return_value=False)
        ), patch.object(hw, "current_period", return_value="evening"):
            return await recs.build_empty_recs(lang="ro", habits=habits, atmosphere={}, limit=5)

    chips = asyncio.run(_run())
    labels = " ".join(c["label"] for c in chips)
    assert "Închide Poarta auto" in labels
    assert "Aprinde Poarta" not in labels


def test_build_empty_recs_skips_already_on():
    habits = {
        "updated_at": 1,
        "meta_version": 2,
        "lights": [
            {
                "entity_id": "light.living",
                "name": "Living",
                "count": 5,
                "kind": "group",
                "member_ids": ["light.a", "light.b"],
                "periods": {"morning": 1, "day": 1, "evening": 5, "night": 0},
            }
        ],
        "covers": [],
        "scenes": [],
    }
    states = {"light.living": {"entity_id": "light.living", "state": "on"}}

    async def _run():
        with patch.object(recs, "enabled", return_value=True), patch(
            "services.recommendations.load_config",
            return_value={"recommendations": {"enabled": True}, "frigate": {"enabled": False}},
        ), patch.object(recs, "_states_map", new=AsyncMock(return_value=states)), patch.object(
            recs, "_has_energy_stats", new=AsyncMock(return_value=False)
        ), patch.object(hw, "current_period", return_value="evening"):
            return await recs.build_empty_recs(lang="ro", habits=habits, limit=5)

    chips = asyncio.run(_run())
    prompts = " ".join(c["prompt"] for c in chips).lower()
    assert "aprinde living" not in prompts
    assert any(c["kind"] == "ask" for c in chips)


def test_build_empty_recs_disabled():
    async def _run():
        with patch.object(recs, "enabled", return_value=False):
            return await recs.build_empty_recs(lang="en")

    assert asyncio.run(_run()) == []
