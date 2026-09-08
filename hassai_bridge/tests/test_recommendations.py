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


def test_top_lights_prefers_period_score():
    habits = {
        "lights": [
            {
                "entity_id": "light.a",
                "name": "A",
                "count": 10,
                "periods": {"morning": 0, "day": 0, "evening": 1, "night": 0},
            },
            {
                "entity_id": "light.b",
                "name": "B",
                "count": 3,
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


def test_build_followups_light_context_ro():
    with patch.object(recs, "enabled", return_value=True), patch(
        "services.recommendations.load_config", return_value={"recommendations": {"enabled": True}}
    ):
        chips = recs.build_followups(
            lang="ro",
            assistant_text="Am aprins Living.",
            tools_used=["ha_call_service"],
        )
    assert chips
    labels = [c["label"] for c in chips]
    assert any("detalii" in x.lower() or "Mai multe" in x for x in labels)
    assert any("hol" in x.lower() for x in labels)


def test_build_followups_disabled():
    with patch.object(recs, "enabled", return_value=False):
        assert recs.build_followups(lang="en", assistant_text="hi", tools_used=[]) == []


def test_build_empty_recs_skips_already_on():
    habits = {
        "updated_at": 1,
        "lights": [
            {
                "entity_id": "light.living",
                "name": "Living",
                "count": 5,
                "periods": {"morning": 1, "day": 1, "evening": 5, "night": 0},
            }
        ],
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
