"""Allowlist and policy tests for browser_interact (no Chromium required)."""

from services import browser_interact as bi


def test_url_allowed_blocks_file_not_offlist():
    cfg = {
        "browser": {
            "enabled": True,
            "ha_url": "http://homeassistant:8123",
            "allowlist": ["example.com"],
        }
    }
    ok, _ = bi.url_allowed("https://example.com/docs", cfg)
    assert ok
    # Off-list hosts still pass url_allowed; chat asks Allow/Decline via host_preapproved.
    ok, _ = bi.url_allowed("https://evil.test/", cfg)
    assert ok
    ok, reason = bi.url_allowed("file:///etc/passwd", cfg)
    assert not ok


def test_url_allowed_blocks_sensitive_ha_paths():
    cfg = {"browser": {"enabled": True, "ha_url": "http://homeassistant:8123", "allowlist": []}}
    ok, reason = bi.url_allowed("http://homeassistant:8123/auth/login", cfg)
    assert not ok
    assert "blocked" in reason
    ok, _ = bi.url_allowed("http://homeassistant:8123/lovelace/home", cfg)
    assert ok


def test_host_preapproved_allowlist_and_session():
    cfg = {"browser": {"enabled": True, "ha_url": "http://homeassistant:8123", "allowlist": ["google.ro"]}}
    assert bi.host_preapproved("https://www.google.ro/search", cfg, None)
    assert not bi.host_preapproved("https://example.com/", cfg, None)
    bi.clear_session_hosts("s1")
    bi.grant_session_host("s1", "example.com")
    assert bi.host_preapproved("https://example.com/x", cfg, "s1")
    bi.clear_session_hosts("s1")


def test_is_enabled_default_false():
    assert not bi.is_enabled({"browser": {}, "bridge_tools": {}})
    assert not bi.is_enabled({"browser": {"enabled": False}, "bridge_tools": {"browser": False}})
    assert bi.is_enabled({"browser": {}, "bridge_tools": {"browser": True}})
    assert bi.is_enabled({"browser": {"enabled": True}, "bridge_tools": {"browser": False}})


def test_page_ws_url_prefers_page_target_not_browser():
    """Regression: browser-level WS has no Page.enable / Emulation.*."""
    targets = [
        {
            "type": "browser",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9/devtools/browser/abc",
        },
        {
            "type": "page",
            "url": "about:blank",
            "webSocketDebuggerUrl": "ws://127.0.0.1:9/devtools/page/xyz",
        },
    ]
    assert bi._page_ws_url_from_targets(targets) == "ws://127.0.0.1:9/devtools/page/xyz"
    assert bi._page_ws_url_from_targets([]) is None
    assert bi._page_ws_url_from_targets({"webSocketDebuggerUrl": "ws://nope"}) is None


def test_is_enabled_honors_session_grant():
    from services import tool_enable as te

    te.clear_session("br-sess")
    cfg = {"bridge_tools": {"browser": False}, "browser": {"enabled": False}}
    assert not bi.is_enabled(cfg, "br-sess")
    te.grant_session("br-sess", "bridge:browser")
    assert bi.is_enabled(cfg, "br-sess")
    te.clear_session("br-sess")


def test_persist_host_to_allowlist(monkeypatch):
    state = {"browser": {"enabled": True, "allowlist": ["a.com"]}}

    def _load():
        return {
            "browser": {
                "enabled": True,
                "allowlist": list(state["browser"]["allowlist"]),
            }
        }

    def _save(cfg):
        state["browser"] = dict(cfg.get("browser") or {})

    monkeypatch.setattr("config.load_config", _load)
    monkeypatch.setattr("config.save_config", _save)
    msg = bi.persist_host_to_allowlist("YouTube.COM")
    assert "youtube.com" in msg.lower()
    assert "youtube.com" in state["browser"]["allowlist"]
    assert "a.com" in state["browser"]["allowlist"]
    # idempotent
    bi.persist_host_to_allowlist("youtube.com")
    assert state["browser"]["allowlist"].count("youtube.com") == 1


def test_host_approval_preview():
    text = bi.host_approval_preview("https://www.youtube.com/watch?v=1")
    assert "youtube.com" in text
    assert "https://" in text
