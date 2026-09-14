"""Unit + acceptance coverage for background tasks V1."""

from __future__ import annotations

import asyncio
import time

import pytest

from services.background_tasks import delivery, manager, store, worker
from services.background_tasks import ha_events


@pytest.fixture()
def bg_db(tmp_path, monkeypatch):
    import database as db_mod
    from core import database as core_db

    core_db.close_all_connections()
    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    core_db.init_db()
    yield db_path
    core_db.close_all_connections()


def _cfg(**overrides):
    base = {
        "background_tasks": {
            "enabled": True,
            "max_active_per_user": 5,
            "max_monitor_hours": 24,
            "worker_lease_seconds": 30,
        },
        "ha_tools": {"entities": True},
        "bridge_tools": {},
    }
    base.update(overrides)
    return base


@pytest.fixture()
def quiet_delivery(monkeypatch):
    monkeypatch.setattr(
        "services.background_tasks.delivery.add_conversation_message",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "services.background_tasks.delivery.post_created_card",
        lambda *a, **k: None,
    )

    async def _noop(*a, **k):
        return None

    monkeypatch.setattr("services.background_tasks.delivery.notify_blocked", _noop)
    monkeypatch.setattr("services.background_tasks.delivery.enqueue_result", _noop)


def test_create_idempotent_and_limits(bg_db, quiet_delivery, monkeypatch):
    monkeypatch.setattr(manager, "load_config", lambda: _cfg())
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    a = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="wait_for_state",
        title="Wait light",
        spec={"entity_id": "light.x", "state": "on", "timeout_seconds": 60},
        idempotency_key="k1",
        cfg=_cfg(),
    )
    assert a["ok"]
    b = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="wait_for_state",
        title="Wait light again",
        spec={"entity_id": "light.x", "state": "on", "timeout_seconds": 60},
        idempotency_key="k1",
        cfg=_cfg(),
    )
    assert b["ok"] and b.get("deduplicated")
    assert b["task"]["task_id"] == a["task"]["task_id"]

    cfg = _cfg()
    cfg["background_tasks"]["max_active_per_user"] = 1
    monkeypatch.setattr(manager, "load_config", lambda: cfg)
    c = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="monitor_entities",
        spec={"entity_ids": ["sensor.a"], "duration_seconds": 30},
        cfg=cfg,
    )
    assert not c["ok"]
    assert "limit" in c["error"]


def test_cancel_and_cross_user_deny(bg_db, quiet_delivery, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    created = manager.create_task(
        owner_id="alice",
        session_id="s1",
        kind="monitor_entities",
        spec={"entity_ids": ["binary_sensor.door"], "duration_seconds": 120},
        cfg=_cfg(),
    )
    tid = created["task"]["task_id"]
    deny = manager.get_task(tid, owner_id="bob")
    assert not deny["ok"]
    cancel = manager.cancel_task(tid, owner_id="alice")
    assert cancel["ok"]
    task = store.get_task(tid)
    assert task["cancel_requested_at"]


def test_lease_exclusive(bg_db):
    task = store.insert_task(
        task_id=store.new_task_id(),
        owner_id="u",
        session_id="s",
        kind="monitor_entities",
        title="t",
        spec={"entity_ids": ["sensor.a"], "duration_seconds": 60},
        status="scheduled",
        deadline_at=time.time() + 60,
        next_run_at=time.time(),
    )
    tid = task["task_id"]
    assert store.try_acquire_lease(tid, "w1", 30)
    assert not store.try_acquire_lease(tid, "w2", 30)
    store.release_lease(tid, "w1")
    assert store.try_acquire_lease(tid, "w2", 30)


def test_permission_recheck_blocks(bg_db, quiet_delivery, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    created = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="wait_for_state",
        spec={"entity_id": "light.x", "state": "on", "timeout_seconds": 30},
        cfg=_cfg(),
    )
    tid = created["task"]["task_id"]

    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: False,
    )
    monkeypatch.setattr(manager, "load_config", lambda: _cfg())
    monkeypatch.setattr(worker, "load_config", lambda: _cfg())

    asyncio.run(worker.process_task(store.get_task(tid)))
    task = store.get_task(tid)
    assert task["status"] == "blocked"


def test_coverage_gaps(bg_db):
    task = store.insert_task(
        task_id=store.new_task_id(),
        owner_id="u",
        session_id="s",
        kind="monitor_entities",
        title="mon",
        spec={"entity_ids": ["sensor.a"], "duration_seconds": 60},
        status="running",
        deadline_at=time.time() + 60,
        next_run_at=time.time(),
    )
    store.update_task(task["task_id"], started_at=time.time() - 10)
    ha_events._gap_open_at = None
    ha_events.refresh_watch_index()
    ha_events._open_gaps("disconnect")
    events = store.list_events(task["task_id"])
    assert any(e["event_type"] == "gap_start" for e in events)
    ha_events._close_gaps()
    events = store.list_events(task["task_id"])
    assert any(e["event_type"] == "gap_end" for e in events)
    refreshed = store.get_task(task["task_id"])
    assert (refreshed.get("progress") or {}).get("coverage_gaps")


def test_delivery_retry(bg_db, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "services.background_tasks.delivery.post_created_card",
        lambda *a, **k: None,
    )
    created = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="wait_for_state",
        spec={"entity_id": "light.x", "state": "on", "timeout_seconds": 5, "accept_already_true": True},
        cfg=_cfg(),
    )
    tid = created["task"]["task_id"]
    store.update_task(
        tid,
        status="completed",
        result={
            "kind": "wait_for_state",
            "matched": True,
            "entity_id": "light.x",
            "state": "on",
            "last_state": "on",
            "waited_seconds": 1,
            "timed_out": False,
        },
    )

    calls = {"n": 0}

    def boom(*a, **k):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("db down")
        return None

    monkeypatch.setattr(delivery, "add_conversation_message", boom)

    async def _run():
        await delivery.enqueue_result(tid)
        assert store.get_delivery(store.new_delivery_id(tid)).get("status") == "failed"
        await delivery.try_deliver(store.new_delivery_id(tid))

    asyncio.run(_run())
    row = store.get_delivery(store.new_delivery_id(tid))
    assert row["status"] == "delivered"
    assert calls["n"] >= 2


def test_wait_for_state_match(bg_db, quiet_delivery, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(manager, "load_config", lambda: _cfg())
    monkeypatch.setattr(worker, "load_config", lambda: _cfg())

    async def fake_deliver(tid):
        store.upsert_delivery(
            delivery_id=store.new_delivery_id(tid),
            task_id=tid,
            status="delivered",
        )

    monkeypatch.setattr(delivery, "enqueue_result", fake_deliver)

    created = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="wait_for_state",
        spec={
            "entity_id": "binary_sensor.door",
            "state": "on",
            "timeout_seconds": 30,
            "accept_already_true": False,
        },
        cfg=_cfg(),
    )
    tid = created["task"]["task_id"]
    store.add_observation(tid, entity_id="binary_sensor.door", old_state="off", new_state="on")

    asyncio.run(worker.process_task(store.get_task(tid)))
    task = store.get_task(tid)
    assert task["status"] == "completed"
    assert (task.get("result") or {}).get("matched") is True


def test_cleanup_old_results(bg_db, quiet_delivery, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "services.background_tasks.delivery.add_conversation_message",
        lambda *a, **k: None,
    )
    created = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="monitor_entities",
        spec={"entity_ids": ["sensor.a"], "duration_seconds": 10},
        cfg=_cfg(),
    )
    tid = created["task"]["task_id"]
    store.update_task(tid, status="completed", result={"ok": True})
    # Force old updated_at
    with __import__("core.database", fromlist=["get_db"]).get_db() as conn:
        conn.execute(
            "UPDATE bg_tasks SET updated_at = ? WHERE task_id = ?",
            (time.time() - 40 * 86400, tid),
        )
    n = store.cleanup_old_results(30)
    assert n == 1
    assert store.get_task(tid) is None


def test_created_card_posted(bg_db, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    posts = []

    def capture(user_id, role, content, session_id=None, meta=None):
        posts.append({"user_id": user_id, "role": role, "content": content, "meta": meta})

    monkeypatch.setattr(
        "services.background_tasks.delivery.add_conversation_message",
        capture,
    )
    out = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="wait_for_state",
        title="Door",
        spec={"entity_id": "binary_sensor.door", "state": "on", "timeout_seconds": 60},
        cfg=_cfg(),
    )
    assert out["ok"]
    assert posts
    assert posts[0]["meta"]["background_task_id"] == out["task"]["task_id"]
    assert "scheduled" in posts[0]["content"].lower()


def test_disabled_in_settings(bg_db, monkeypatch):
    cfg = _cfg()
    cfg["background_tasks"]["enabled"] = False
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    out = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="monitor_entities",
        spec={"entity_ids": ["sensor.a"], "duration_seconds": 10},
        cfg=cfg,
    )
    assert not out["ok"]


def test_is_core_tool():
    from services import toolkits as tk

    assert tk.is_core_tool("background_tasks")


def test_remind_me_becomes_due(bg_db, quiet_delivery, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: False,  # entities OFF must not block reminders
    )
    monkeypatch.setattr(manager, "load_config", lambda: _cfg())
    monkeypatch.setattr(worker, "load_config", lambda: _cfg())

    created = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="remind_me",
        title="Tea",
        spec={"delay_seconds": 30, "message": "Check the kettle"},
        cfg=_cfg(),
    )
    assert created["ok"]
    tid = created["task"]["task_id"]
    task = store.get_task(tid)
    assert task["kind"] == "remind_me"
    assert task["spec"]["message"] == "Check the kettle"
    assert float(task["next_run_at"]) >= float(task["deadline_at"]) - 1

    # Not due yet — stays running/scheduled with next_run at deadline
    asyncio.run(worker.process_task(store.get_task(tid)))
    mid = store.get_task(tid)
    assert mid["status"] in ("running", "scheduled")
    assert mid["status"] != "completed"

    store.update_task(tid, deadline_at=time.time() - 1, next_run_at=time.time())
    delivered = {"n": 0}

    async def capture_enqueue(task_id):
        delivered["n"] += 1
        task = store.get_task(task_id)
        assert task["status"] == "completed"
        assert (task.get("result") or {}).get("message") == "Check the kettle"

    monkeypatch.setattr("services.background_tasks.delivery.enqueue_result", capture_enqueue)
    asyncio.run(worker.process_task(store.get_task(tid)))
    done = store.get_task(tid)
    assert done["status"] == "completed"
    assert delivered["n"] == 1


def test_remind_me_caps_delay(bg_db, quiet_delivery, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    out = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="remind_me",
        spec={"delay_days": 999, "delay_seconds": 99999999, "message": "far future"},
        cfg=_cfg(),
    )
    assert out["ok"]
    delay = float(out["task"]["spec"]["delay_seconds"])
    assert delay <= manager.MAX_REMIND_SECONDS


def test_delivery_notifies_ha_when_configured(bg_db, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "services.background_tasks.delivery.post_created_card",
        lambda *a, **k: None,
    )
    posts = []
    notify_calls = []

    def capture_post(*a, **k):
        posts.append(True)

    async def fake_core(method, path, **kwargs):
        notify_calls.append({"method": method, "path": path, "body": kwargs.get("json_body")})
        return {}

    cfg = _cfg()
    cfg["background_tasks"]["notify_service"] = "notify.sm_s938b"
    cfg["background_tasks"]["notify_on_complete"] = True
    monkeypatch.setattr(delivery, "load_config", lambda: cfg)
    monkeypatch.setattr(manager, "load_config", lambda: cfg)
    monkeypatch.setattr(
        "services.background_tasks.delivery.add_conversation_message",
        capture_post,
    )
    monkeypatch.setattr("services.homeassistant._core", fake_core)

    created = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="remind_me",
        title="Call mom",
        spec={"delay_seconds": 5, "message": "Call mom"},
        cfg=cfg,
    )
    tid = created["task"]["task_id"]
    store.update_task(
        tid,
        status="completed",
        result={"kind": "remind_me", "message": "Call mom", "delay_seconds": 5},
    )
    asyncio.run(delivery.enqueue_result(tid))
    assert posts
    assert notify_calls
    assert notify_calls[0]["path"] == "/services/notify/sm_s938b"
    assert "Call mom" in (notify_calls[0]["body"] or {}).get("message", "")


def test_delivery_skips_notify_without_service(bg_db, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "services.background_tasks.delivery.post_created_card",
        lambda *a, **k: None,
    )
    notify_calls = []

    async def fake_core(*a, **k):
        notify_calls.append(1)
        return {}

    cfg = _cfg()
    cfg["background_tasks"]["notify_service"] = ""
    monkeypatch.setattr(delivery, "load_config", lambda: cfg)
    monkeypatch.setattr(manager, "load_config", lambda: cfg)
    monkeypatch.setattr(
        "services.background_tasks.delivery.add_conversation_message",
        lambda *a, **k: None,
    )
    monkeypatch.setattr("services.homeassistant.is_available", lambda: False)
    monkeypatch.setattr("services.homeassistant._core", fake_core)

    created = manager.create_task(
        owner_id="u1",
        session_id="s1",
        kind="remind_me",
        spec={"delay_minutes": 1, "message": "ping"},
        cfg=cfg,
    )
    tid = created["task"]["task_id"]
    store.update_task(
        tid,
        status="completed",
        result={"kind": "remind_me", "message": "ping", "delay_seconds": 60},
    )
    asyncio.run(delivery.enqueue_result(tid))
    assert notify_calls == []


def test_resolve_notify_from_person_tracker(monkeypatch):
    from services.background_tasks import notify_resolve as nr

    monkeypatch.setattr(
        nr,
        "get_profile",
        lambda username: {"username": username, "ha_id": "abc-123", "display_name": "Andrei"},
    )
    monkeypatch.setattr(nr, "load_config", lambda: _cfg())
    monkeypatch.setattr(manager, "load_config", lambda: _cfg())
    monkeypatch.setattr("services.homeassistant.is_available", lambda: True)

    async def fake_core(method, path, **kwargs):
        if path == "/states":
            return [
                {
                    "entity_id": "person.andrei",
                    "attributes": {
                        "friendly_name": "Andrei",
                        "user_id": "abc-123",
                        "device_trackers": ["device_tracker.sm_s938b"],
                    },
                }
            ]
        if path == "/services":
            return [
                {
                    "domain": "notify",
                    "services": {
                        "sm_s938b": {},
                        "persistent_notification": {},
                    },
                }
            ]
        return {}

    monkeypatch.setattr("services.homeassistant._core", fake_core)
    out = asyncio.run(nr.resolve_notify_service("andrei", cfg=_cfg()))
    assert out == "notify.sm_s938b"


def test_resolve_notify_sole_phone_fallback(monkeypatch):
    from services.background_tasks import notify_resolve as nr

    monkeypatch.setattr(
        nr,
        "get_profile",
        lambda username: {"username": username, "ha_id": "", "display_name": "Andrei"},
    )
    monkeypatch.setattr(nr, "load_config", lambda: _cfg())
    monkeypatch.setattr(manager, "load_config", lambda: _cfg())
    monkeypatch.setattr("services.homeassistant.is_available", lambda: True)

    async def fake_core(method, path, **kwargs):
        if path == "/states":
            return []
        if path == "/services":
            return [{"domain": "notify", "services": {"mobile_app_sm_s938b": {}}}]
        return {}

    monkeypatch.setattr("services.homeassistant._core", fake_core)
    out = asyncio.run(nr.resolve_notify_service("andrei", cfg=_cfg()))
    assert out == "notify.mobile_app_sm_s938b"


def test_resolve_notify_settings_override_wins(monkeypatch):
    from services.background_tasks import notify_resolve as nr

    cfg = _cfg()
    cfg["background_tasks"]["notify_service"] = "notify.forced_phone"
    monkeypatch.setattr(nr, "load_config", lambda: cfg)
    monkeypatch.setattr(manager, "load_config", lambda: cfg)
    out = asyncio.run(nr.resolve_notify_service("andrei", cfg=cfg))
    assert out == "notify.forced_phone"


def test_delivery_auto_notifies_logged_in_user(bg_db, monkeypatch):
    monkeypatch.setattr(
        "services.tool_enable.effectively_enabled",
        lambda *a, **k: True,
    )
    monkeypatch.setattr(
        "services.background_tasks.delivery.post_created_card",
        lambda *a, **k: None,
    )
    notify_calls = []

    async def fake_core(method, path, **kwargs):
        if method == "GET" and path == "/states":
            return [
                {
                    "entity_id": "person.andrei",
                    "attributes": {
                        "friendly_name": "Andrei",
                        "user_id": "ha-1",
                        "device_trackers": ["device_tracker.sm_s938b"],
                    },
                }
            ]
        if method == "GET" and path == "/services":
            return [{"domain": "notify", "services": {"mobile_app_sm_s938b": {}}}]
        if method == "POST":
            notify_calls.append(path)
            return {}
        return {}

    cfg = _cfg()
    cfg["background_tasks"]["notify_service"] = ""
    monkeypatch.setattr(delivery, "load_config", lambda: cfg)
    monkeypatch.setattr(manager, "load_config", lambda: cfg)
    monkeypatch.setattr(
        "services.background_tasks.notify_resolve.get_profile",
        lambda username: {"username": username, "ha_id": "ha-1", "display_name": "Andrei"},
    )
    monkeypatch.setattr("services.homeassistant.is_available", lambda: True)
    monkeypatch.setattr("services.homeassistant._core", fake_core)
    monkeypatch.setattr(
        "services.background_tasks.delivery.add_conversation_message",
        lambda *a, **k: None,
    )

    created = manager.create_task(
        owner_id="andrei",
        session_id="s1",
        kind="remind_me",
        spec={"delay_seconds": 5, "message": "auto"},
        cfg=cfg,
    )
    tid = created["task"]["task_id"]
    # Simulate pin at create
    scope = dict(store.get_task(tid).get("permission_scope") or {})
    scope["notify_service"] = "notify.mobile_app_sm_s938b"
    store.update_task(tid, permission_scope=scope)
    store.update_task(
        tid,
        status="completed",
        result={"kind": "remind_me", "message": "auto", "delay_seconds": 5},
    )
    asyncio.run(delivery.enqueue_result(tid))
    assert notify_calls == ["/services/notify/mobile_app_sm_s938b"]
