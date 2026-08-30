"""Per-session chat provider overrides (do not mutate global Settings)."""

from services import session_chat as sc


def test_session_override_manual_model():
    sid = "sess-test-1"
    sc.clear(sid)
    sc.set_override(sid, provider_id="p1", model="m-a", auto=False)
    row = sc.get(sid)
    assert row["provider_id"] == "p1"
    assert row["model"] == "m-a"
    assert row["auto"] is False

    sc.set_override(sid, model="m-b")
    row = sc.get(sid)
    assert row["provider_id"] == "p1"
    assert row["model"] == "m-b"
    assert row["auto"] is False


def test_session_override_auto_clears_manual():
    sid = "sess-test-2"
    sc.clear(sid)
    sc.set_override(sid, provider_id="p1", model="m-a", auto=False)
    sc.set_override(sid, auto=True)
    row = sc.get(sid)
    assert row["auto"] is True
    assert row["provider_id"] == ""
    assert row["model"] == ""


def test_resolve_route_uses_session_provider(monkeypatch):
    sid = "sess-test-3"
    sc.clear(sid)
    cfg = {
        "routing": {"mode": "manual", "profile": "balanced", "sticky_session": True, "roles": {}},
        "providers": [
            {"id": "a", "name": "A", "type": "openai", "model": "gpt-a"},
            {"id": "b", "name": "B", "type": "openai", "model": "gpt-b"},
        ],
        "active_provider": "a",
    }
    sc.set_override(sid, provider_id="b", model="gpt-b-custom", auto=False)
    route = sc.resolve_route_for_session(
        cfg,
        session_id=sid,
        active=cfg["providers"][0],
        user_text="hi",
    )
    assert route["auto"] is False
    assert route["reason"] == "session"
    assert route["provider"]["id"] == "b"
    assert route["provider"]["model"] == "gpt-b-custom"
    assert route["model"] == "gpt-b-custom"


def test_effective_chat_info_session_scoped():
    sid = "sess-test-4"
    sc.clear(sid)
    cfg = {
        "routing": {"mode": "manual", "profile": "balanced", "sticky_session": True, "roles": {}},
        "providers": [
            {"id": "a", "name": "Alpha", "type": "openai", "model": "gpt-a"},
            {"id": "b", "name": "Beta", "type": "deepseek", "model": "ds-chat"},
        ],
        "active_provider": "a",
    }
    # Without override → global active
    info = sc.effective_chat_info(cfg, None)
    assert info["provider_id"] == "a"
    assert info["session_scoped"] is False

    sc.set_override(sid, provider_id="b", auto=False)
    info = sc.effective_chat_info(cfg, sid)
    assert info["provider_id"] == "b"
    assert info["provider_name"] == "Beta"
    assert info["model"] == "ds-chat"
    assert info["auto"] is False
    assert info["session_scoped"] is True
