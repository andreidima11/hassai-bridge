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
