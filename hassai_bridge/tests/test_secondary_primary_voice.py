"""Secondary handles tool rounds; primary speaks and owns memory."""

from __future__ import annotations

import asyncio

import pytest

from routers import chat as chat_mod
from services import memory_engine as me


def test_recall_routes_ha_to_primary_and_search_to_secondary():
    active = {"id": "primary", "model": "gpt-4o"}
    secondary = {"id": "secondary", "model": "llama-local"}

    assert chat_mod._recall_provider(
        [{"function": {"name": "ha_list_entities"}}], active, secondary,
    )["id"] == "primary"
    assert chat_mod._recall_provider(
        [{"function": {"name": "ha_call_service"}}], active, secondary,
    )["id"] == "primary"
    assert chat_mod._recall_provider(
        [{"function": {"name": "web_search"}}], active, secondary,
    )["id"] == "secondary"
    assert chat_mod._recall_provider(
        [{"function": {"name": "frigate_events"}}], active, secondary,
    )["id"] == "secondary"


def test_should_finalize_on_primary_when_secondary_returns_text():
    active = {"id": "primary"}
    secondary = {"id": "secondary"}

    assert chat_mod._should_finalize_on_primary(
        active=active,
        secondary=secondary,
        call_provider=secondary,
        tool_calls=None,
    ) is True
    assert chat_mod._should_finalize_on_primary(
        active=active,
        secondary=secondary,
        call_provider=secondary,
        tool_calls=[{"function": {"name": "web_search"}}],
    ) is False
    assert chat_mod._should_finalize_on_primary(
        active=active,
        secondary=secondary,
        call_provider=active,
        tool_calls=None,
    ) is False
    assert chat_mod._should_finalize_on_primary(
        active=active,
        secondary=None,
        call_provider=secondary,
        tool_calls=None,
    ) is False


def test_secondary_tools_hint_appended():
    msgs = chat_mod._messages_for_secondary_tools([{"role": "user", "content": "hi"}])
    assert msgs[-1]["role"] == "system"
    assert "Do not write the final user-facing answer" in msgs[-1]["content"]
    assert msgs[0]["content"] == "hi"


def test_extract_uses_active_provider_when_none(memory_db, monkeypatch):
    """Background extract must call the primary, not leave provider unset."""
    active = {"id": "primary-cloud", "name": "Primary", "type": "openai", "model": "gpt-4o-mini"}
    seen: list[dict | None] = []

    async def fake_llm(messages, max_tokens=1000, provider=None):
        seen.append(provider)
        return "NONE"

    monkeypatch.setattr(me, "_llm_call", fake_llm)
    monkeypatch.setattr(me, "load_config", lambda: {
        "memory": {"enabled": True, "auto_extract": True, "max_memories_per_user": 500},
    })
    monkeypatch.setattr(
        "services.providers.get_active_provider",
        lambda: active,
    )

    asyncio.run(me.extract_memories_from_conversation("alice", [
        {"role": "user", "content": "ține minte că am o pisică pe nume Miu"},
        {"role": "assistant", "content": "Am notat."},
    ]))
    assert seen and seen[0] is active


def test_consolidate_uses_active_provider_when_none(memory_db, monkeypatch):
    from database import add_memory

    for i in range(10):
        add_memory("alice", f"fact number {i} about the house layout", category="facts")

    active = {"id": "primary-cloud", "name": "Primary", "type": "openai", "model": "gpt-4o-mini"}
    seen: list[dict | None] = []

    async def fake_llm(messages, max_tokens=1000, provider=None):
        seen.append(provider)
        return "{}"

    monkeypatch.setattr(me, "_llm_call", fake_llm)
    monkeypatch.setattr(
        "services.providers.get_active_provider",
        lambda: active,
    )

    asyncio.run(me.consolidate_memories("alice"))
    assert seen and seen[0] is active


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
