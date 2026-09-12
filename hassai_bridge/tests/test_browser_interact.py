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
    # Off-list hosts are allowed at the policy layer — chat Approve gates them.
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
