"""Tests for ha_get_logs add-on support (e.g. Zigbee2MQTT)."""

from __future__ import annotations

import pytest

from services import homeassistant as ha


@pytest.mark.asyncio
async def test_resolve_addon_slug_z2m_alias(monkeypatch):
    async def fake_supervisor(method, path, **kwargs):
        assert path == "/addons"
        return {
            "addons": [
                {"slug": "core_ssh", "name": "Terminal & SSH"},
                {"slug": "45df7312_zigbee2mqtt", "name": "Zigbee2MQTT"},
            ]
        }

    monkeypatch.setattr(ha, "_supervisor", fake_supervisor)
    slug, err = await ha._resolve_addon_slug("z2m")
    assert err is None
    assert slug == "45df7312_zigbee2mqtt"


@pytest.mark.asyncio
async def test_resolve_addon_slug_exact(monkeypatch):
    async def fake_supervisor(method, path, **kwargs):
        return {"addons": [{"slug": "45df7312_zigbee2mqtt", "name": "Zigbee2MQTT"}]}

    monkeypatch.setattr(ha, "_supervisor", fake_supervisor)
    slug, err = await ha._resolve_addon_slug("45df7312_zigbee2mqtt")
    assert err is None
    assert slug == "45df7312_zigbee2mqtt"


@pytest.mark.asyncio
async def test_get_logs_addon(monkeypatch):
    calls: list[str] = []

    async def fake_supervisor(method, path, **kwargs):
        calls.append(path)
        if path == "/addons":
            return {"addons": [{"slug": "45df7312_zigbee2mqtt", "name": "Zigbee2MQTT"}]}
        if path.endswith("/logs"):
            assert kwargs.get("text") is True
            return "line1\nERROR mqtt offline\nline3\n"
        raise AssertionError(path)

    monkeypatch.setattr(ha, "_supervisor", fake_supervisor)
    out = await ha._get_logs({"source": "addon", "slug": "z2m", "search": "error", "lines": 50})
    assert "45df7312_zigbee2mqtt" in out
    assert "ERROR mqtt offline" in out
    assert "/addons/45df7312_zigbee2mqtt/logs" in calls


@pytest.mark.asyncio
async def test_get_logs_slug_implies_addon(monkeypatch):
    async def fake_supervisor(method, path, **kwargs):
        if path == "/addons":
            return {"addons": [{"slug": "a0d7b954_nodered", "name": "Node-RED"}]}
        if path.endswith("/logs"):
            return "nodered ok\n"
        raise AssertionError(path)

    monkeypatch.setattr(ha, "_supervisor", fake_supervisor)
    out = await ha._get_logs({"slug": "nodered"})
    assert "nodered ok" in out
