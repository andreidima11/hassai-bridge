"""Tests for the LLM-facing memory tools."""

from __future__ import annotations

import pytest

from services import memory_tools as mt


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


CFG = {"memory": {"enabled": True, "auto_extract": True, "max_memories_per_user": 500}}


# ── Durable fact vs live state ─────────────────────

@pytest.mark.parametrize("text", [
    "The kitchen light is on",
    "Becul din bucătărie este aprins",
    "Ușa de la intrare e descuiată",
    "The temperature in the bedroom is 21.5",
    "Bateria senzorului este la 43%",
    "The user is home right now",
    "Andrei este acasă acum",
    "It is raining today",
])
def test_live_state_is_rejected(text):
    assert mt.transient_reason(text)


@pytest.mark.parametrize("text", [
    "Andrei's daughter is called Maria and was born in 2019",
    "Andrei lucrează ca inginer software în București",
    "The living room light is a Philips Hue White Ambiance bulb",
    "Andrei prefers the lights off at night",
    "Utilizatorul preferă răspunsuri scurte, în română",
    "The upstairs bathroom is called 'baie mare' in Home Assistant",
])
def test_durable_facts_are_accepted(text):
    assert mt.transient_reason(text) == ""


def test_conversation_meta_is_rejected(memory_db):
    out = mt.run_tool("memory_save", {"content": "The user asked about cameras"}, "alice", CFG)
    assert out.startswith("Rejected")


# ── Round trip ─────────────────────────────────────

def test_save_search_update_forget(memory_db):
    saved = mt.run_tool(
        "memory_save",
        {"content": "Andrei has a dog named Rex", "category": "personal_info", "importance": 4},
        "alice",
        CFG,
    )
    assert saved.startswith("Remembered")

    listed = mt.run_tool("memory_list", {}, "alice", CFG)
    assert "Rex" in listed

    found = mt.run_tool("memory_search", {"query": "dog"}, "alice", CFG)
    assert "Rex" in found

    memory_id = int(found.split("#")[1].split(" ")[0])

    updated = mt.run_tool(
        "memory_update",
        {"memory_id": memory_id, "content": "Andrei has a dog named Rex, a golden retriever"},
        "alice",
        CFG,
    )
    assert "golden retriever" in updated

    forgotten = mt.run_tool("memory_forget", {"memory_id": memory_id}, "alice", CFG)
    assert forgotten.startswith("Forgot")
    assert "Rex" not in mt.run_tool("memory_list", {}, "alice", CFG)


def test_save_rejects_live_state_with_guidance(memory_db):
    out = mt.run_tool("memory_save", {"content": "The hallway light is on"}, "alice", CFG)
    assert out.startswith("Rejected")
    assert "Home Assistant" in out
    assert mt.run_tool("memory_list", {}, "alice", CFG).startswith("No memories")


def test_saving_twice_refreshes_instead_of_duplicating(memory_db):
    mt.run_tool("memory_save", {"content": "Andrei lives in Bucharest"}, "alice", CFG)
    again = mt.run_tool("memory_save", {"content": "Andrei lives in Bucharest"}, "alice", CFG)
    assert "Already knew that" in again
    assert mt.run_tool("memory_list", {}, "alice", CFG).startswith("1 of 1")


def test_memories_are_per_user(memory_db):
    saved = mt.run_tool("memory_save", {"content": "Andrei drives a blue Dacia"}, "alice", CFG)
    memory_id = int(saved.split("#")[1].split(",")[0])
    out = mt.run_tool("memory_forget", {"memory_id": memory_id}, "bob", CFG)
    assert "does not exist" in out


def test_bad_category_falls_back_to_facts(memory_db):
    out = mt.run_tool(
        "memory_save",
        {"content": "Andrei speaks Romanian and English", "category": "nonsense"},
        "alice",
        CFG,
    )
    assert "facts" in out


def test_memory_limit_is_reported(memory_db):
    cfg = {"memory": {"enabled": True, "max_memories_per_user": 1}}
    mt.run_tool("memory_save", {"content": "Andrei plays the guitar"}, "alice", cfg)
    out = mt.run_tool("memory_save", {"content": "Andrei studied in Cluj at university"}, "alice", cfg)
    assert "memory is full" in out


# ── Gating ─────────────────────────────────────────

def test_tools_hidden_when_memory_off():
    assert mt.build_tools({"memory": {"enabled": False}}) == []
    assert mt.system_hint({"memory": {"enabled": False}}) == ""


def test_tools_hidden_when_group_off():
    cfg = {"memory": {"enabled": True}, "bridge_tools": {"memory": False}}
    assert mt.build_tools(cfg) == []
    assert mt.run_tool("memory_save", {"content": "x y z"}, "alice", cfg).startswith("Error")


def test_tools_exposed_by_default():
    names = {spec["function"]["name"] for spec in mt.build_tools(CFG)}
    assert names == set(mt.TOOL_NAMES)


def test_system_hint_covers_state_rule():
    hint = mt.system_hint(CFG)
    assert "memory_save" in hint
    assert "Never save live state" in hint
