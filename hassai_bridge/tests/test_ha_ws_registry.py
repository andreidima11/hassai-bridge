"""HA WebSocket registry size / list_areas isolation."""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from services import homeassistant as ha


@pytest.mark.asyncio
async def test_ws_call_raises_max_size(monkeypatch):
    """Entity registries on busy homes exceed the 1 MiB websockets default."""
    assert ha._WS_MAX_SIZE >= 16 * 1024 * 1024

    seen: dict = {}

    class FakeWs:
        def __init__(self):
            self._n = 0

        async def recv(self):
            self._n += 1
            if self._n == 1:
                return json.dumps({"type": "auth_required"})
            if self._n == 2:
                return json.dumps({"type": "auth_ok"})
            return json.dumps({"id": 1, "success": True, "result": [{"area_id": "living"}]})

        async def send(self, _data):
            return None

    @asynccontextmanager
    async def fake_connect(url, **kwargs):
        seen["kwargs"] = kwargs
        yield FakeWs()

    monkeypatch.setenv("SUPERVISOR_TOKEN", "tok")
    monkeypatch.setenv("HASSAI_HA_WS", "ws://example/websocket")
    monkeypatch.setattr(
        "websockets.asyncio.client.connect",
        fake_connect,
        raising=False,
    )
    # Prefer patching whatever import path _ws_call uses.
    import websockets.asyncio.client as ws_client

    monkeypatch.setattr(ws_client, "connect", fake_connect)

    out = await ha._ws_call({"type": "config/area_registry/list"})
    assert out == [{"area_id": "living"}]
    assert seen["kwargs"].get("max_size") == ha._WS_MAX_SIZE


@pytest.mark.asyncio
async def test_list_areas_skips_full_registry_bundle(monkeypatch):
    calls: list[str] = []

    async def fake_ws(payload, timeout=20.0):
        calls.append(payload.get("type") or "")
        return [{"area_id": "living", "name": "Living", "icon": "mdi:sofa"}]

    async def boom_bundle():
        raise AssertionError("list_areas must not fetch the full registry bundle")

    monkeypatch.setattr(ha, "_ws_call", fake_ws)
    monkeypatch.setattr(ha, "_fetch_registry_bundle", boom_bundle)

    out = await ha._list_areas({})
    assert "living|Living" in out
    assert calls == ["config/area_registry/list"]
