"""Tests for the background memory extraction pipeline gates."""

from __future__ import annotations

import asyncio

import pytest

from services import memory_engine as me


@pytest.fixture()
def memory_db(tmp_path, monkeypatch):
    import database as db_mod
    from core import database as core_db

    core_db.close_all_connections()
    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    core_db.init_db()
    yield db_path
    core_db.close_all_connections()


@pytest.fixture()
def capture_llm(monkeypatch):
    """Record the extraction prompt and replay a canned action list."""
    calls: list[dict] = []
    reply = {"text": "NONE"}

    async def fake(messages, max_tokens=1000, provider=None):
        calls.append({"messages": messages})
        return reply["text"]

    monkeypatch.setattr(me, "_llm_call", fake)
    monkeypatch.setattr(me, "load_config", lambda: {
        "memory": {"enabled": True, "auto_extract": True, "max_memories_per_user": 500},
    })
    return calls, reply


def _extract(user_text, assistant_text="Sigur."):
    asyncio.run(me.extract_memories_from_conversation("alice", [
        {"role": "user", "content": user_text},
        {"role": "assistant", "content": assistant_text},
    ]))


@pytest.mark.parametrize("text", [
    "ține minte că am o pisică pe nume Miu",
    "memorează asta",
    "notează, te rog",
    "remember this",
    "don't forget it",
    "reține",
])
def test_explicit_requests_are_detected(text):
    assert me.is_explicit_memory_request(text)


def test_short_explicit_request_still_runs_extraction(memory_db, capture_llm):
    calls, _ = capture_llm
    # Three words: the trivial-message pre-filter used to drop this silently.
    _extract("memorează asta")
    assert calls, "explicit memory request must reach the extraction LLM"
    assert "explicitly asked to remember" in calls[0]["messages"][-1]["content"]


def test_small_talk_still_skips_extraction(memory_db, capture_llm):
    calls, _ = capture_llm
    _extract("ok")
    assert not calls


def test_extracted_live_state_is_not_stored(memory_db, capture_llm):
    from database import get_memories

    calls, reply = capture_llm
    reply["text"] = (
        "ADD home_setup 3 The kitchen light is on\n"
        "ADD home_setup 3 The kitchen has three Philips Hue bulbs"
    )
    _extract("becul din bucătărie e aprins, am trei becuri Hue acolo")
    stored = [m["content"] for m in get_memories("alice")]
    assert stored == ["The kitchen has three Philips Hue bulbs"]


def test_prompt_spells_out_the_state_rule(capture_llm):
    assert "NEVER STORE LIVE STATE" in me.EXTRACT_PIPELINE_PROMPT
    assert "must be read from Home Assistant each time" in me.EXTRACT_PIPELINE_PROMPT
    assert "NEVER STORE HOME ASSISTANT REGISTRY DATA" in me.EXTRACT_PIPELINE_PROMPT
    assert "LIFE EVENTS" in me.EXTRACT_PIPELINE_PROMPT
    assert "{today_date}" in me.EXTRACT_PIPELINE_PROMPT


def test_format_extract_prompt_injects_date():
    out = me.format_extract_prompt(
        me.default_extract_prompt(),
        existing_memories="(none)",
        conversation="USER: am fost la restaurant",
        today_date="2026-08-25",
    )
    assert "2026-08-25" in out
    assert "(none)" in out


def test_resolve_extract_prompt_custom():
    cfg = {"memory": {"extract_prompt": "CUSTOM {existing_memories} {conversation} {today_date}"}}
    assert me.resolve_extract_prompt(cfg) == "CUSTOM {existing_memories} {conversation} {today_date}"
    assert "LIFE EVENTS" in me.resolve_extract_prompt({"memory": {}})


def test_ha_registry_fact_is_rejected(memory_db, capture_llm):
    from database import get_memories
    from services.memory_tools import ha_registry_redundant_reason

    assert ha_registry_redundant_reason(
        'There is a device called "bec interior bar" controlled via entity ID "releu.bar.lumini.interior".'
    )

    calls, reply = capture_llm
    reply["text"] = (
        "ADD home_setup 3 There is a light named Bec living etaj with entity ID switch.releu_living_sus_l1.\n"
        "ADD preferences 4 User prefers short answers in Romanian."
    )
    _extract(
        "cum arată livingul seara?",
        'There is a light named Bec living etaj with entity ID switch.releu_living_sus_l1.',
    )
    stored = [m["content"] for m in get_memories("alice")]
    assert stored == ["User prefers short answers in Romanian."]


def test_pure_ha_operation_skips_extraction(memory_db, capture_llm):
    calls, reply = capture_llm
    reply["text"] = "ADD home_setup 3 Bec living etaj is switch.releu_living_sus_l1"
    _extract("stinge lumini living etaj", "Am stins switch.releu_living_sus_l1.")
    assert not calls


def test_routine_ha_skips_even_without_entity_markers_in_reply(memory_db, capture_llm):
    calls, _ = capture_llm
    _extract("stinge toate luminile din casă te rog", "Gata, am stins luminile.")
    assert not calls


def test_mixed_control_and_life_event_still_extracts(memory_db, capture_llm):
    from database import get_memories

    calls, reply = capture_llm
    reply["text"] = "ADD context 3 Pe 2026-08-25 userul a fost la restaurant."
    _extract(
        "aprinde lumina living, am fost azi la restaurant",
        "Am aprins lumina.",
    )
    assert calls
    stored = [m["content"] for m in get_memories("alice")]
    assert any("restaurant" in s.lower() for s in stored)


def test_life_event_can_be_stored(memory_db, capture_llm):
    from database import get_memories

    calls, reply = capture_llm
    reply["text"] = "ADD context 3 Pe 2026-08-25 userul a fost la restaurant și a servit pizza."
    _extract(
        "am fost azi la restaurant și am mâncat pizza",
        "Sună bine!",
    )
    stored = [m["content"] for m in get_memories("alice")]
    assert any("pizza" in s.lower() and "restaurant" in s.lower() for s in stored)
