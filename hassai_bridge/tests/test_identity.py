from core.identity import resolve_display_name, user_context_for_prompt


def test_resolve_display_name_from_profile(monkeypatch):
    monkeypatch.setattr(
        "core.identity.list_profiles",
        lambda: [{"username": "andrei", "display_name": "Andrei", "ha_id": "abc", "source": "home_assistant"}],
    )
    assert resolve_display_name("andrei") == "Andrei"
    assert resolve_display_name("default") == ""
    assert resolve_display_name("webui") == ""


def test_user_context_for_prompt(monkeypatch):
    monkeypatch.setattr(
        "core.identity.list_profiles",
        lambda: [{"username": "andrei", "display_name": "Andrei", "ha_id": "abc", "source": "home_assistant"}],
    )
    ctx = user_context_for_prompt("andrei")
    assert "Andrei" in ctx
    assert "[User]" in ctx


def test_user_context_empty_for_default():
    assert user_context_for_prompt("default") == ""
