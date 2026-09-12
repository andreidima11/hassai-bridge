"""Allowlist and policy tests for browser_interact (no Chromium required)."""

from services import browser_interact as bi


def test_url_allowed_blocks_file_and_offlist():
    cfg = {
        "browser": {
            "enabled": True,
            "ha_url": "http://homeassistant:8123",
            "allowlist": ["example.com"],
        }
    }
    ok, _ = bi.url_allowed("https://example.com/docs", cfg)
    assert ok
    ok, reason = bi.url_allowed("https://evil.test/", cfg)
    assert not ok
    assert "allowlist" in reason
    ok, reason = bi.url_allowed("file:///etc/passwd", cfg)
    assert not ok


def test_url_allowed_blocks_sensitive_ha_paths():
    cfg = {"browser": {"enabled": True, "ha_url": "http://homeassistant:8123", "allowlist": []}}
    ok, reason = bi.url_allowed("http://homeassistant:8123/auth/login", cfg)
    assert not ok
    assert "blocked" in reason
    ok, _ = bi.url_allowed("http://homeassistant:8123/lovelace/home", cfg)
    assert ok


def test_is_enabled_default_false():
    assert not bi.is_enabled({"browser": {}, "bridge_tools": {}})
    assert not bi.is_enabled({"browser": {"enabled": False}, "bridge_tools": {"browser": False}})
    assert bi.is_enabled({"browser": {}, "bridge_tools": {"browser": True}})
    assert bi.is_enabled({"browser": {"enabled": True}, "bridge_tools": {"browser": False}})
