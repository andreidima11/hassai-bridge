"""Persist round-trip for session_state (sticky packs + chat override)."""

from __future__ import annotations

import pytest

from services import session_chat as sc
from services import toolkits as tk


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


def test_sticky_packs_roundtrip(memory_db):
    sid = "sess-sticky-1"
    uid = "andre"
    tk.clear_sticky(sid, user_id=uid)
    tk.set_sticky(sid, {"entities", "control"}, user_id=uid)
    assert tk.get_sticky(sid, user_id=uid) == {"entities", "control"}

    # Drop L1 cache — must hydrate from DB
    tk._sticky.clear()
    assert tk.get_sticky(sid, user_id=uid) == {"entities", "control"}

    tk.clear_sticky(sid, user_id=uid)
    tk._sticky.clear()
    assert tk.get_sticky(sid, user_id=uid) == set()


def test_chat_override_roundtrip(memory_db):
    sid = "sess-chat-1"
    uid = "andre"
    sc.clear(sid)
    sc.set_override(sid, provider_id="p1", model="m1", auto=False, user_id=uid)
    got = sc.get(sid, user_id=uid)
    assert got["provider_id"] == "p1"
    assert got["model"] == "m1"
    assert got["auto"] is False

    sc._overrides.clear()
    got2 = sc.get(sid, user_id=uid)
    assert got2["provider_id"] == "p1"
    assert got2["model"] == "m1"

    sc.clear(sid)
    sc._overrides.clear()
    assert sc.get(sid, user_id=uid) is None


def test_toolkit_audit_write_read(memory_db):
    from core import database as db

    db.add_toolkit_audit(
        user_id="u1",
        session_id="s1",
        event="route",
        packs=["entities"],
        detail="confidence=0.9 reason=ok",
        tools_tokens_before=1000,
        tools_tokens_after=200,
    )
    rows = db.get_toolkit_audit(5)
    assert rows
    assert rows[0]["event"] == "route"
    assert rows[0]["packs"] == ["entities"]
