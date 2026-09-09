"""Unit tests for habit scoring and recommendation chip builders."""

import asyncio
from unittest.mock import AsyncMock, patch

from services import habit_watcher as hw
from services import recommendations as recs
from services import recs_llm as rl


def _run_followups(**kwargs):
    with patch.object(recs.rl, "recs_mode", return_value="medium"), patch.object(
        recs.rl, "generate_followups", new=AsyncMock(return_value=[])
    ):
        return asyncio.run(recs.build_followups(**kwargs))


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


def test_score_gateish_switch_without_contact_is_cover_not_light():
    states = [
        {
            "entity_id": "switch.poarta_auto",
            "state": "off",
            "attributes": {"friendly_name": "Poarta auto"},
        },
    ]
    entries = [
        {
            "entity_id": "switch.poarta_auto",
            "state": "on",
            "when": "2026-03-01T18:00:00+00:00",
            "context_user_id": "u",
        },
    ]
    data = hw.score_logbook(entries, states=states)
    assert not any(r["entity_id"] == "switch.poarta_auto" for r in data["lights"])
    assert any(r["entity_id"] == "switch.poarta_auto" for r in data["covers"])


def test_normalize_covers_rescues_gate_from_old_lights():
    habits = {
        "lights": [{
            "entity_id": "switch.poarta_auto",
            "name": "Poarta auto",
            "count": 5,
            "periods": {"evening": 5, "morning": 0, "day": 0, "night": 0},
        }],
        "covers": [],
    }
    covers = hw.top_covers_for_period(habits, period="evening", limit=3)
    assert covers and covers[0]["entity_id"] == "switch.poarta_auto"
    lights = hw.top_lights_for_period(habits, period="evening", limit=5)
    assert not any(r["entity_id"] == "switch.poarta_auto" for r in lights)


def test_lumina_poarta_is_not_a_gate():
    assert not hw.is_gateish("Lumina poarta", "input_boolean.lumina_poarta")
    assert not hw.is_actionable_entity("input_boolean.lumina_poarta")
    assert hw.is_gateish("Poarta auto", "switch.poarta_auto")


def test_score_ignores_input_boolean_lumina_poarta():
    states = [
        {
            "entity_id": "input_boolean.lumina_poarta",
            "state": "off",
            "attributes": {"friendly_name": "Lumina poarta"},
        },
        {
            "entity_id": "switch.poarta_auto",
            "state": "off",
            "attributes": {"friendly_name": "Poarta auto"},
        },
    ]
    entries = [
        {
            "entity_id": "switch.poarta_auto",
            "state": "on",
            "when": "2026-03-01T18:00:00+00:00",
            "context_user_id": "u",
        },
    ]
    data = hw.score_logbook(entries, states=states)
    ids = [r["entity_id"] for r in data["covers"]]
    assert "input_boolean.lumina_poarta" not in ids
    assert "switch.poarta_auto" in ids


def test_recs_mode():
    assert rl.recs_mode({"recommendations": {"mode": "high"}}) == "high"
    assert rl.recs_mode({"recommendations": {"mode": "none"}}) == "none"
    assert rl.recs_mode({"recommendations": {"enabled": False}}) == "none"
    assert rl.recs_mode({"recommendations": {}}) == "medium"


def test_followups_philosophy_empty():
    chips = _run_followups(
        lang="ro",
        user_text="Ce părere ai despre nemurirea sufletului?",
        assistant_text="E o temă veche în filosofie și religie...",
    )
    assert chips == []


def test_followups_yes_no_on_chat_question():
    chips = _run_followups(
        lang="ro",
        user_text="Hai să discutăm despre artă",
        assistant_text="Interesant. Vrei să începem cu pictura modernă?",
    )
    labels = [c["label"] for c in chips]
    assert len(chips) == 2
    # User-voice: accept chip is the action, not bare Da
    assert labels[0].lower() != "da"
    assert "pictura" in labels[0].lower() or "începem" in labels[0].lower() or "pictura" in chips[0]["prompt"].lower()
    assert chips[0]["prompt"].lower() != "da"
    assert "mulțumesc" in labels[1].lower() or "mulțumesc" in chips[1]["prompt"].lower()


def test_followups_status_offer_uses_topics_not_bare_da():
    assistant = (
        "Senzori inundație: camera tehnică #2 — fără scurgeri. "
        "Baterii slabe: temperatura_afara la 59%. "
        "Irigații: au rulat dimineața la 2:00–2:45.\n"
        "Totul pare în regulă. Vrei să verific ceva anume mai detaliat?"
    )
    chips = _run_followups(
        lang="ro",
        user_text="Status casă",
        assistant_text=assistant,
        tool_calls=[{"name": "ha_get_state", "arguments": "{}"}],
    )
    labels = [c["label"] for c in chips]
    prompts = " ".join(c["prompt"].lower() for c in chips)
    assert "Da" not in labels
    assert any(x in labels for x in ("Irigații", "Baterii slabe", "Senzori inundație"))
    assert "iriga" in prompts or "bater" in prompts or "inunda" in prompts
    assert any("mulțumesc" in (c["label"] + c["prompt"]).lower() for c in chips) or len(chips) >= 1


def test_yes_prompt_never_bare():
    chips = recs._yes_no_chips(
        "ro",
        "Pot să verific senzorii de inundație acum?",
    )
    assert chips[0]["label"].lower() != "da"
    assert chips[0]["prompt"].lower() != "da"
    assert "inunda" in chips[0]["prompt"].lower() or "verific" in chips[0]["prompt"].lower()


def test_build_followups_smalltalk_no_hallway():
    chips = _run_followups(lang="ro", user_text="Ce faci?", assistant_text="Bine, tu?")
    # Smalltalk / chat → no HA filler; yes/no voice chips OK only if a clear offer
    assert all("Status" not in c["label"] and "hallway" not in c["label"].lower() for c in chips)


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
        "services.recommendations.load_config", return_value={"recommendations": {"mode": "medium"}}
    ), patch.object(hw, "current_period", return_value="evening"), patch.object(
        recs.rl, "recs_mode", return_value="medium"
    ), patch.object(recs.rl, "generate_followups", new=AsyncMock(return_value=[])):
        chips = asyncio.run(recs.build_followups(
            lang="ro",
            user_text="Aprinde living",
            assistant_text="Am aprins Living.",
            tool_calls=tools,
            habits=habits,
        ))
    labels = " ".join(c["label"].lower() for c in chips)
    assert "hol" not in labels
    assert "seara" in labels or "stinge" in labels or "living" in labels


def test_build_followups_disabled():
    with patch.object(recs, "enabled", return_value=False):
        assert asyncio.run(recs.build_followups(lang="en", assistant_text="hi", tools_used=[])) == []


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
        ), patch.object(hw, "current_period", return_value="evening"), patch.object(
            hw, "current_hour", return_value=18
        ), patch.object(
            recs.rl, "recs_mode", return_value="medium"
        ), patch.object(recs.rl, "ensure_empty_pool", new=AsyncMock(return_value=[])):
            return await recs.build_empty_recs(lang="ro", habits=habits, atmosphere={}, limit=3)

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
        ), patch.object(hw, "current_period", return_value="evening"), patch.object(
            hw, "current_hour", return_value=18
        ), patch.object(
            recs.rl, "recs_mode", return_value="medium"
        ), patch.object(recs.rl, "ensure_empty_pool", new=AsyncMock(return_value=[])):
            return await recs.build_empty_recs(lang="ro", habits=habits, limit=3)

    chips = asyncio.run(_run())
    prompts = " ".join(c["prompt"] for c in chips).lower()
    assert "aprinde living" not in prompts
    assert any(c["kind"] == "ask" for c in chips)


def test_build_empty_recs_disabled():
    async def _run():
        with patch.object(recs, "enabled", return_value=False):
            return await recs.build_empty_recs(lang="en")

    assert asyncio.run(_run()) == []


def _empty_habits_lights_and_gates():
    return {
        "updated_at": 1,
        "meta_version": 5,
        "lights": [
            {
                "entity_id": "light.ambient_dormitor_2",
                "name": "Lumini ambientale dormitor 2",
                "count": 20,
                "kind": "group",
                "member_ids": ["light.a", "light.b"],
                "periods": {"evening": 12, "morning": 2, "day": 2, "night": 4},
            },
            {
                "entity_id": "light.seara_living",
                "name": "Lumini seara living",
                "count": 18,
                "kind": "group",
                "member_ids": ["light.c", "light.d"],
                "periods": {"evening": 14, "morning": 0, "day": 1, "night": 3},
            },
            {
                "entity_id": "light.lampa_dormitor_1",
                "name": "Lampa dormitor 1",
                "count": 15,
                "kind": "light",
                "periods": {"evening": 10, "morning": 1, "day": 1, "night": 3},
            },
            {
                "entity_id": "light.led_pat_dormitor_1",
                "name": "LED pat dormitor 1",
                "count": 14,
                "kind": "light",
                "periods": {"evening": 9, "morning": 0, "day": 0, "night": 5},
            },
        ],
        "covers": [
            {
                "entity_id": "switch.poarta_auto",
                "name": "Poarta auto",
                "open_count": 8,
                "close_count": 8,
                "contact_entity_id": "binary_sensor.poarta_contact",
                "periods": {"evening": 6, "morning": 2, "day": 4, "night": 4},
            },
            {
                "entity_id": "switch.poarta_pietonala",
                "name": "Poarta pietonala",
                "open_count": 5,
                "close_count": 5,
                "periods": {"evening": 4, "morning": 1, "day": 2, "night": 3},
            },
        ],
        "scenes": [],
    }


def test_score_keeps_named_lamps_not_rolled_into_group():
    states = [
        {
            "entity_id": "light.ambient_dormitor",
            "state": "off",
            "attributes": {
                "friendly_name": "Lumini ambientale dormitor 2",
                "entity_id": [
                    "light.lampa_dormitor_1",
                    "light.led_pat",
                    "light.dormitor_bec_1",
                ],
            },
        },
        {
            "entity_id": "light.lampa_dormitor_1",
            "state": "off",
            "attributes": {"friendly_name": "Lampa dormitor 1"},
        },
        {
            "entity_id": "light.led_pat",
            "state": "off",
            "attributes": {"friendly_name": "LED pat dormitor 1"},
        },
        {
            "entity_id": "light.dormitor_bec_1",
            "state": "off",
            "attributes": {"friendly_name": "Lampa dormitor #2 - bec 1"},
        },
    ]
    entries = []
    for eid, when in (
        ("light.lampa_dormitor_1", "2026-03-01T19:10:00+00:00"),
        ("light.lampa_dormitor_1", "2026-03-02T19:20:00+00:00"),
        ("light.led_pat", "2026-03-01T19:30:00+00:00"),
        ("light.led_pat", "2026-03-03T20:00:00+00:00"),
        ("light.dormitor_bec_1", "2026-03-01T19:40:00+00:00"),
        ("light.dormitor_bec_1", "2026-03-02T20:10:00+00:00"),
    ):
        entries.append({
            "entity_id": eid,
            "state": "on",
            "when": when,
            "context_user_id": "user-1",
        })
    data = hw.score_logbook(entries, states=states)
    ids = [r["entity_id"] for r in data["lights"]]
    assert "light.lampa_dormitor_1" in ids
    assert "light.led_pat" in ids
    assert "light.ambient_dormitor" in ids
    assert "light.dormitor_bec_1" not in ids


def test_top_lights_keeps_several_named_favorites():
    habits = _empty_habits_lights_and_gates()
    top = hw.top_lights_for_period(habits, period="evening", limit=4)
    names = {r["name"] for r in top}
    assert "Lumini ambientale dormitor 2" in names
    assert "Lumini seara living" in names
    assert "Lampa dormitor 1" in names
    assert "LED pat dormitor 1" in names


def test_device_status_chip_detected():
    assert rl.is_device_status_chip({
        "label": "Starea porții auto",
        "prompt": "Care e starea porții auto?",
        "kind": "ask",
    })
    assert not rl.is_device_status_chip({
        "label": "Aprinde Lumini seara living",
        "prompt": "Aprinde Lumini seara living",
        "kind": "action",
    })


def test_pedestrian_gate_switch_on_means_close():
    assert hw.is_gateish("Poarta pietonala", "switch.poarta_pietonala")
    states = {"switch.poarta_pietonala": {"state": "on"}}
    assert hw.is_open_like(states, "switch.poarta_pietonala")
    chips = recs.heuristic_empty_actions(
        {
            "covers": [{
                "entity_id": "switch.poarta_pietonala",
                "name": "Poarta pietonala",
                "open_count": 3,
                "close_count": 2,
                "periods": {"evening": 3, "morning": 0, "day": 0, "night": 0},
            }],
            "lights": [],
        },
        states,
        lang="ro",
        period="evening",
        hour=18,
    )
    labels = " ".join(c["label"] for c in chips)
    assert "Închide Poarta pietonala" in labels
    assert "Aprinde" not in labels


def test_build_empty_recs_prefers_live_actions_over_llm_status():
    habits = _empty_habits_lights_and_gates()
    states = {
        "switch.poarta_auto": {"state": "off"},
        "binary_sensor.poarta_contact": {"state": "on"},
        "switch.poarta_pietonala": {"state": "off"},
        "light.ambient_dormitor_2": {"state": "off"},
        "light.seara_living": {"state": "off"},
        "light.lampa_dormitor_1": {"state": "off"},
        "light.led_pat_dormitor_1": {"state": "off"},
    }
    llm = [
        {
            "id": "gate-status",
            "label": "Starea porții auto",
            "prompt": "Care e starea porții auto?",
            "kind": "ask",
        },
        {
            "id": "house",
            "label": "Status casă",
            "prompt": "Dă-mi statusul casei",
            "kind": "ask",
        },
    ]

    async def _run():
        with patch.object(recs, "enabled", return_value=True), patch(
            "services.recommendations.load_config",
            return_value={"recommendations": {"mode": "medium"}, "frigate": {"enabled": False}},
        ), patch.object(recs, "_states_map", new=AsyncMock(return_value=states)), patch.object(
            recs, "_has_energy_stats", new=AsyncMock(return_value=False)
        ), patch.object(hw, "current_period", return_value="evening"), patch.object(
            hw, "current_hour", return_value=18
        ), patch.object(recs.rl, "recs_mode", return_value="medium"), patch.object(
            recs.rl, "ensure_empty_pool", new=AsyncMock(return_value=llm)
        ):
            return await recs.build_empty_recs(lang="ro", habits=habits, atmosphere={}, limit=3)

    chips = asyncio.run(_run())
    assert len(chips) <= 3
    labels = [c["label"] for c in chips]
    blob = " ".join(labels)
    assert "Starea porții auto" not in blob
    assert "Închide Poarta auto" in blob or "Deschide Poarta" in blob or any(
        "Aprinde" in x for x in labels
    )
    assert sum(1 for c in chips if c["kind"] == "action") >= 2


def test_catalog_need_follows_gate_state():
    habits = {
        "covers": [{
            "entity_id": "switch.poarta_auto",
            "name": "Poarta auto",
            "open_count": 2,
            "close_count": 2,
            "contact_entity_id": "binary_sensor.poarta_contact",
            "periods": {"evening": 2, "morning": 0, "day": 0, "night": 0},
        }],
        "lights": [{
            "entity_id": "light.seara_living",
            "name": "Lumini seara living",
            "count": 5,
            "kind": "group",
            "member_ids": ["light.a"],
            "periods": {"evening": 5, "morning": 0, "day": 0, "night": 0},
        }],
    }
    states = {
        "switch.poarta_auto": {"state": "off"},
        "binary_sensor.poarta_contact": {"state": "on"},
        "light.seara_living": {"state": "off"},
    }
    lines = "\n".join(rl.catalog_lines(habits, states))
    assert "need=close" in lines
    assert "need=turn_on" in lines


def test_score_logbook_stores_hour_histogram():
    entries = [
        {
            "entity_id": "light.lampa",
            "state": "on",
            "when": "2026-03-01T21:10:00+00:00",
            "context_user_id": "u",
        },
        {
            "entity_id": "light.lampa",
            "state": "on",
            "when": "2026-03-02T21:20:00+00:00",
            "context_user_id": "u",
        },
        {
            "entity_id": "light.lampa",
            "state": "on",
            "when": "2026-03-03T07:05:00+00:00",
            "context_user_id": "u",
        },
    ]
    states = [{
        "entity_id": "light.lampa",
        "state": "off",
        "attributes": {"friendly_name": "Lampa dormitor 1"},
    }]
    data = hw.score_logbook(entries, states=states)
    row = data["lights"][0]
    hours = row["hours"]
    # Local timezone may shift UTC — just assert evening-ish hour has counts.
    assert sum(int(v) for v in hours.values()) == 3
    assert hw.hour_affinity(hours, 21) >= hw.hour_affinity(hours, 12)


def test_hour_affinity_prefers_matching_hour():
    habits = {
        "lights": [
            {
                "entity_id": "light.evening_lamp",
                "name": "Lampa dormitor 1",
                "count": 10,
                "kind": "light",
                "hours": {"21": 8, "20": 2},
                "periods": {"evening": 10, "morning": 0, "day": 0, "night": 0},
            },
            {
                "entity_id": "light.morning_lamp",
                "name": "Lampa hol",
                "count": 10,
                "kind": "light",
                "hours": {"7": 9},
                "periods": {"morning": 9, "evening": 1, "day": 0, "night": 0},
            },
        ]
    }
    top = hw.top_lights_for_period(habits, period="evening", hour=21, limit=1)
    assert top[0]["entity_id"] == "light.evening_lamp"
    top_m = hw.top_lights_for_period(habits, period="morning", hour=7, limit=1)
    assert top_m[0]["entity_id"] == "light.morning_lamp"


def test_climate_hot_recommends_ac():
    states = {
        "sensor.living_temperature": {
            "state": "27.5",
            "attributes": {
                "friendly_name": "Temperatura living",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            },
        },
        "climate.ac_living": {
            "state": "off",
            "attributes": {
                "friendly_name": "AC Living",
                "current_temperature": 27.5,
                "temperature": 24,
                "hvac_modes": ["off", "cool", "heat"],
            },
        },
    }
    chips = [c for _, c in recs.climate_candidates(states, lang="ro")]
    blob = " ".join(c["label"] + c["prompt"] for c in chips)
    assert "AC Living" in blob
    assert "Pornește" in blob or "Aprinde" in blob


def test_climate_cold_thermostat_off_and_raise():
    states_off = {
        "sensor.dormitor_temp": {
            "state": "19",
            "attributes": {
                "friendly_name": "Temperatura dormitor",
                "device_class": "temperature",
                "unit_of_measurement": "°C",
            },
        },
        "climate.termostat": {
            "state": "off",
            "attributes": {
                "friendly_name": "Termostat",
                "current_temperature": 19,
                "temperature": 20,
                "hvac_modes": ["off", "heat"],
            },
        },
    }
    chips = [c for _, c in recs.climate_candidates(states_off, lang="ro")]
    assert any("Pornește Termostat" in c["label"] for c in chips)

    states_low = {
        **states_off,
        "climate.termostat": {
            "state": "heat",
            "attributes": {
                "friendly_name": "Termostat",
                "current_temperature": 19,
                "temperature": 18,
                "hvac_modes": ["off", "heat"],
            },
        },
    }
    chips2 = [c for _, c in recs.climate_candidates(states_low, lang="ro")]
    assert any("22" in c["label"] for c in chips2)


def test_many_lights_on_suggests_turn_off():
    habits = {"lights": [], "covers": [], "scenes": []}
    states = {
        f"light.room_{i}": {
            "state": "on",
            "attributes": {"friendly_name": f"Lumina camera {i}"},
        }
        for i in range(4)
    }
    with patch.object(hw, "current_hour", return_value=22), patch.object(
        hw, "current_period", return_value="evening"
    ):
        scored = recs.scored_empty_candidates(
            habits, states, lang="ro", period="evening", hour=22, has_energy=False
        )
    labels = [c["label"] for _, c in scored]
    assert any(l.startswith("Stinge") for l in labels)


def test_build_empty_recs_max_three():
    habits = _empty_habits_lights_and_gates()
    # Enrich with hour histograms so evening ranking is strong.
    for row in habits["lights"]:
        row["hours"] = {"18": 10, "19": 8}
    for row in habits["covers"]:
        row["hours"] = {"18": 5, "8": 4}
    states = {
        "switch.poarta_auto": {"state": "off"},
        "binary_sensor.poarta_contact": {"state": "off"},
        "switch.poarta_pietonala": {"state": "off"},
        "light.ambient_dormitor_2": {"state": "off"},
        "light.seara_living": {"state": "off"},
        "light.lampa_dormitor_1": {"state": "off"},
        "light.led_pat_dormitor_1": {"state": "off"},
        "sensor.solar_production": {"state": "1200"},
    }

    async def _run():
        with patch.object(recs, "enabled", return_value=True), patch(
            "services.recommendations.load_config",
            return_value={"recommendations": {"mode": "medium"}, "frigate": {"enabled": False}},
        ), patch.object(recs, "_states_map", new=AsyncMock(return_value=states)), patch.object(
            recs, "_has_energy_stats", new=AsyncMock(return_value=True)
        ), patch.object(hw, "current_period", return_value="evening"), patch.object(
            hw, "current_hour", return_value=18
        ), patch.object(recs.rl, "recs_mode", return_value="medium"), patch.object(
            recs.rl, "ensure_empty_pool", new=AsyncMock(return_value=[])
        ):
            return await recs.build_empty_recs(lang="ro", habits=habits, atmosphere={}, limit=99)

    chips = asyncio.run(_run())
    assert len(chips) == 3
    assert all(not rl.is_device_status_chip(c) for c in chips)


def test_gate_suggest_window():
    assert hw.gate_suggest_window(8) is True
    assert hw.gate_suggest_window(18) is True
    assert hw.gate_suggest_window(21) is False
    assert hw.gate_suggest_window(12) is False


def test_empty_gate_hidden_at_hour_21_without_affinity():
    habits = {
        "lights": [],
        "covers": [{
            "entity_id": "switch.poarta_auto",
            "name": "Poarta auto",
            "open_count": 5,
            "close_count": 5,
            "periods": {"evening": 5, "morning": 1, "day": 0, "night": 2},
            "hours": {"8": 4, "18": 3},
        }],
        "scenes": [],
    }
    states = {
        "switch.poarta_auto": {"state": "off"},
        "binary_sensor.poarta_contact": {"state": "off"},
    }
    scored = recs.scored_empty_candidates(
        habits, states, lang="ro", period="evening", hour=21, has_energy=False
    )
    labels = [c["label"] for _, c in scored]
    assert not any("Poarta" in l for l in labels)


def test_empty_gate_shown_at_hour_8_window():
    habits = {
        "lights": [],
        "covers": [{
            "entity_id": "switch.poarta_auto",
            "name": "Poarta auto",
            "open_count": 2,
            "close_count": 2,
            "periods": {"morning": 2},
        }],
        "scenes": [],
    }
    states = {"switch.poarta_auto": {"state": "off"}}
    scored = recs.scored_empty_candidates(
        habits, states, lang="ro", period="morning", hour=8, has_energy=False
    )
    labels = [c["label"] for _, c in scored]
    assert any("Deschide Poarta auto" in l or "Închide Poarta auto" in l for l in labels)


def test_empty_gate_shown_at_hour_21_with_strong_hour_affinity():
    habits = {
        "lights": [],
        "covers": [{
            "entity_id": "switch.poarta_auto",
            "name": "Poarta auto",
            "open_count": 8,
            "close_count": 8,
            "periods": {"evening": 4, "night": 4},
            "hours": {"21": 5, "20": 2},
        }],
        "scenes": [],
    }
    states = {"switch.poarta_auto": {"state": "on"}}
    # affinity: 5*5 + 2*3 = 31 >= GATE_HOUR_AFFINITY_MIN
    assert hw.hour_affinity(habits["covers"][0]["hours"], 21) >= hw.GATE_HOUR_AFFINITY_MIN
    scored = recs.scored_empty_candidates(
        habits, states, lang="ro", period="evening", hour=21, has_energy=False
    )
    labels = [c["label"] for _, c in scored]
    assert any("Închide Poarta auto" in l for l in labels)


def test_chat_habits_record_and_rank_empty(tmp_path, monkeypatch):
    from core import database as core_db
    from services import chat_habits as ch

    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    core_db.init_db()
    monkeypatch.setattr(
        ch,
        "learn_from_chat_enabled",
        lambda cfg=None: True,
    )
    ch.record("alice", topic="irrigation", hour=9, after_intent="status", source="chip_click")
    ch.record("alice", topic="irrigation", hour=9, after_intent="status", source="chip_click")
    ch.record("alice", topic="batteries", hour=9, after_intent="status", source="user_ask")
    top = ch.top_topics_for_hour("alice", hour=9, limit=3)
    assert top and top[0][0] == "irrigation"
    after = ch.topics_after("alice", "status", hour=9, limit=3)
    assert after[0][0] == "irrigation"

    habits = {"lights": [], "covers": [], "scenes": []}
    states = {}
    with patch.object(ch, "preference_topic_boosts", return_value={}):
        scored = recs.scored_empty_candidates(
            habits,
            states,
            lang="ro",
            period="morning",
            hour=9,
            has_energy=False,
            user_id="alice",
        )
    labels = [c["label"] for _, c in scored]
    assert any("Iriga" in l for l in labels)


def test_chat_habits_feedback_chip_and_clear(tmp_path, monkeypatch):
    from core import database as core_db
    from services import chat_habits as ch

    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    core_db.init_db()
    monkeypatch.setattr(ch, "learn_from_chat_enabled", lambda cfg=None: True)
    ch.record_from_chip(
        "bob",
        {"id": "fu-topic-solar", "label": "Solar", "prompt": "Producție solară"},
        context="followup",
        after_intent="status",
        hour=12,
    )
    assert ch.top_topics_for_hour("bob", hour=12)
    n = ch.clear_for_user("bob")
    assert n >= 1
    assert ch.top_topics_for_hour("bob", hour=12) == []


def test_topic_followups_reorder_by_chat_habits(tmp_path, monkeypatch):
    from core import database as core_db
    from services import chat_habits as ch

    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    core_db.init_db()
    monkeypatch.setattr(ch, "learn_from_chat_enabled", lambda cfg=None: True)
    ch.record(
        "carol",
        topic="irrigation",
        hour=10,
        after_intent="status",
        source="chip_click",
        weight=9,
    )
    ch.record(
        "carol",
        topic="batteries",
        hour=10,
        after_intent="status",
        source="user_ask",
        weight=1,
    )
    text = (
        "Statusul casei e ok. Irigațiile au rulat azi. Baterii slabe pe doi senzori. "
        "Senzori inundație ok. Vrei să verific ceva mai detaliat?"
    )
    with patch.object(hw, "current_hour", return_value=10):
        chips = recs.topic_followups_from_reply(
            text, lang="ro", limit=3, user_id="carol", after_intent="status"
        )
    labels = [c["label"] for c in chips]
    assert labels and "Irigații" in labels[0]


def test_chip_override_suppress_and_edit(tmp_path, monkeypatch):
    from core import database as core_db
    from services import chip_overrides as co

    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    core_db.init_db()
    chips = [
        {"id": "house-status", "label": "Home status", "prompt": "Give me home status", "kind": "ask"},
        {"id": "energy-today", "label": "Solar", "prompt": "Solar today", "kind": "ask"},
    ]
    co.suppress("u1", "house-status")
    out = co.apply_overrides("u1", chips)
    assert [c["id"] for c in out] == ["energy-today"]
    co.clear("u1", "house-status")
    co.set_text("u1", "energy-today", "My solar", "How much solar today?")
    out2 = co.apply_overrides("u1", chips)
    assert len(out2) == 2
    energy = next(c for c in out2 if c["id"] == "energy-today")
    assert energy["label"] == "My solar"
    assert energy["prompt"] == "How much solar today?"


def test_meta_followup_chip_filtered():
    assert recs._is_meta_followup_chip({
        "id": "x",
        "label": "What next?",
        "prompt": "What should we do next?",
        "kind": "ask",
    })
    assert recs._is_meta_followup_chip({"id": "y", "label": "Yes", "prompt": "Yes", "kind": "ask"})
    assert not recs._is_meta_followup_chip({
        "id": "z",
        "label": "Open the gate",
        "prompt": "Open the gate",
        "kind": "action",
    })


def test_gate_offer_yes_chip_is_action_phrase():
    chips = recs._yes_no_chips("en", "Want me to open the driveway gate?")
    assert "open" in chips[0]["label"].lower() or "open" in chips[0]["prompt"].lower()
    assert chips[0]["label"].lower() != "yes"
    assert chips[0]["prompt"].lower() != "yes"
