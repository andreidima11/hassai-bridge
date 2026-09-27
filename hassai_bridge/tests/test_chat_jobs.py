"""Durable chat jobs — create, isolate, recover, finalize, notify."""

from __future__ import annotations

import asyncio
import time

import pytest

from services.chat_jobs import delivery, manager, runner, store
from services.chat_turn.engine import MemoryTurnEvents, register_turn_runner, run_registered_turn


@pytest.fixture()
def cj_db(tmp_path, monkeypatch):
    import database as db_mod
    from core import database as core_db

    core_db.close_all_connections()
    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    core_db.init_db()
    yield db_path
    core_db.close_all_connections()


def test_create_idempotent_and_one_per_session(cj_db, monkeypatch):
    monkeypatch.setattr(manager, "load_config", lambda: {"chat_jobs": {"enabled": True}})
    monkeypatch.setattr(
        "services.chat_jobs.manager.get_profile",
        lambda uid: {"ha_id": "ha-1", "display_name": uid, "notify_service": ""},
    )
    job = manager.create_job(job_id="t1", owner_id="andrei", session_id="s1")
    assert job["job_id"] == "t1"
    again = manager.create_job(job_id="t1", owner_id="andrei", session_id="s1")
    assert again["job_id"] == "t1"

    with pytest.raises(store.JobConflictError) as exc:
        store.insert_job(job_id="t2", owner_id="andrei", session_id="s1")
    assert exc.value.busy_job_id == "t1"


def test_owner_isolation_on_activity(cj_db, monkeypatch):
    monkeypatch.setattr(manager, "load_config", lambda: {"chat_jobs": {}})
    monkeypatch.setattr(
        "services.chat_jobs.manager.get_profile",
        lambda uid: {"ha_id": "", "display_name": uid},
    )
    manager.create_job(job_id="j1", owner_id="alice", session_id="s1")
    store.append_event("j1", {"name": "assistant", "detail": "secret", "status": "done"})
    assert manager.activity_payload("j1", owner_id="alice", after=-1) is not None
    assert manager.activity_payload("j1", owner_id="bob", after=-1) is None


def test_placeholder_finalize_once(cj_db, monkeypatch):
    monkeypatch.setattr(manager, "load_config", lambda: {"chat_jobs": {"notify_on_complete": False}})
    monkeypatch.setattr(
        "services.chat_jobs.manager.get_profile",
        lambda uid: {"ha_id": "x", "display_name": uid},
    )
    job = manager.create_job(job_id="jfin", owner_id="u1", session_id="sess")
    mid = delivery.ensure_placeholder(owner_id="u1", session_id="sess", job_id="jfin")
    assert mid
    job = store.get_job("jfin")
    assert int(job["assistant_message_id"]) == int(mid)

    manager.mark_completed("jfin", result={"ok": True})
    asyncio.run(delivery.enqueue_result("jfin", content="Răspuns final.", meta={"model": "m"}))
    # Second delivery is idempotent
    asyncio.run(delivery.enqueue_result("jfin", content="DUPLICATE", meta={}))

    from core.database import get_session_messages

    msgs = get_session_messages("u1", "sess", limit=20)
    assistants = [m for m in msgs if m["role"] == "assistant"]
    assert len(assistants) == 1
    assert assistants[0]["content"] == "Răspuns final."
    assert assistants[0].get("chat_job_id") == "jfin"


def test_recover_on_boot_marks_interrupted(cj_db, monkeypatch):
    monkeypatch.setattr(manager, "load_config", lambda: {"chat_jobs": {"notify_on_complete": False}})
    monkeypatch.setattr(
        "services.chat_jobs.manager.get_profile",
        lambda uid: {"ha_id": "x", "display_name": uid},
    )
    monkeypatch.setattr(runner, "_lang", lambda: "en")

    async def _run():
        job = manager.create_job(job_id="jrec", owner_id="u1", session_id="s1")
        delivery.ensure_placeholder(owner_id="u1", session_id="s1", job_id="jrec")
        manager.mark_running("jrec")
        await runner.recover_on_boot()
        fresh = store.get_job("jrec")
        assert fresh["status"] == "failed"
        assert fresh["error"]["code"] == "interrupted"
        from core.database import get_session_messages

        msgs = get_session_messages("u1", "s1")
        asst = [m for m in msgs if m["role"] == "assistant"][-1]
        assert "interrupted" in asst["content"].lower() or "restart" in asst["content"].lower()

    asyncio.run(_run())


def test_tool_fingerprint_dedupe(cj_db, monkeypatch):
    monkeypatch.setattr(manager, "load_config", lambda: {"chat_jobs": {}})
    monkeypatch.setattr(
        "services.chat_jobs.manager.get_profile",
        lambda uid: {"ha_id": "", "display_name": uid},
    )
    manager.create_job(job_id="jfp", owner_id="u1", session_id="s1")
    runner.record_tool_fingerprint("jfp", "fp1", "OK: light.kitchen")
    assert runner.tool_fingerprint_hit("jfp", "fp1") == "OK: light.kitchen"
    assert runner.tool_fingerprint_hit("jfp", "missing") is None


def test_private_notify_skips_sole_phone(monkeypatch):
    from services.chat_jobs import notify as cj_notify

    async def fake_core(method, path, **kwargs):
        if path == "/states":
            return [
                {
                    "entity_id": "person.alice",
                    "attributes": {"user_id": "ha-alice", "friendly_name": "Alice", "device_trackers": ["device_tracker.phone_a"]},
                },
                {
                    "entity_id": "person.bob",
                    "attributes": {"user_id": "ha-bob", "friendly_name": "Bob", "device_trackers": ["device_tracker.phone_b"]},
                },
            ]
        if path == "/services":
            return [{"domain": "notify", "services": {"mobile_app_phone_a": {}, "mobile_app_phone_b": {}}}]
        return {}

    monkeypatch.setattr(
        "services.chat_jobs.notify.get_profile",
        lambda uid: {"ha_id": "", "display_name": uid, "notify_service": ""},
    )
    monkeypatch.setattr("services.homeassistant.is_available", lambda: True)
    monkeypatch.setattr("services.homeassistant._core", fake_core)

    async def _run():
        # No ha_id → must not pick sole/any phone
        svc = await cj_notify.resolve_private_notify("charlie")
        assert svc == ""

        monkeypatch.setattr(
            "services.chat_jobs.notify.get_profile",
            lambda uid: {"ha_id": "ha-alice", "display_name": "Alice", "notify_service": ""},
        )
        svc = await cj_notify.resolve_private_notify("alice")
        assert svc == "notify.mobile_app_phone_a"

    asyncio.run(_run())


def test_turn_events_protocol():
    async def _run():
        ev = MemoryTurnEvents()

        async def runner(**kwargs):
            await kwargs["events"].emit({"name": "think", "status": "running"})
            return {"ok": True}

        register_turn_runner(runner)
        out = await run_registered_turn(events=ev)
        assert out["ok"] is True
        assert ev.events[0]["name"] == "think"

    asyncio.run(_run())


def test_complete_background_fast_path_marks_done(cj_db, monkeypatch):
    """Regression from reflex stuck on Gândește — also covers durable mark."""
    from routers import chat as chat_router

    monkeypatch.setattr(manager, "load_config", lambda: {"chat_jobs": {}})
    monkeypatch.setattr(
        "services.chat_jobs.manager.get_profile",
        lambda uid: {"ha_id": "", "display_name": uid},
    )
    tid = "fast-durable-1"
    chat_router._traces.pop(tid, None)
    resp = chat_router._complete_background_fast_path(
        trace_id=tid,
        session_id="s1",
        user_id="u1",
        model="hassai-bridge",
        content="Am stins lampa.",
    )
    assert resp.status_code == 202
    job = store.get_job(tid)
    assert job is not None
    assert job["status"] == "completed"
    payload = chat_router._activity_status_payload(chat_router._traces.get(tid), -1)
    assert payload["done"] is True
    chat_router._traces.pop(tid, None)
