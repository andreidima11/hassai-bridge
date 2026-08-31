"""Pack router provider resolve + usage helpers."""

from services import providers as pv
from services import pack_router as pr


def test_resolve_toolkit_router_empty_uses_fallback(monkeypatch):
    primary = {"id": "p1", "model": "main-model"}
    monkeypatch.setattr(pv, "get_toolkit_router_provider", lambda p=None: None)
    out_p, out_m = pv.resolve_toolkit_router(
        primary, fallback_provider=primary, fallback_model="route-model",
    )
    assert out_p is primary
    assert out_m == "route-model"


def test_resolve_toolkit_router_dedicated_prefers_fast(monkeypatch):
    primary = {"id": "p1", "toolkit_router_provider": "r1", "model": "main"}
    secondary = {
        "id": "r1",
        "name": "Router",
        "model": "router-default",
        "role_models": {"fast": "router-fast"},
    }
    monkeypatch.setattr(pv, "get_toolkit_router_provider", lambda p=None: secondary)
    out_p, out_m = pv.resolve_toolkit_router(
        primary, fallback_provider=primary, fallback_model="ignored",
    )
    assert out_p is secondary
    assert out_m == "router-fast"


def test_resolve_toolkit_router_missing_id_falls_back(monkeypatch):
    primary = {"id": "p1", "toolkit_router_provider": "gone"}
    monkeypatch.setattr(pv, "get_toolkit_router_provider", lambda p=None: None)
    fb = {"id": "fb", "model": "m"}
    out_p, out_m = pv.resolve_toolkit_router(primary, fallback_provider=fb, fallback_model="m")
    assert out_p is fb
    assert out_m == "m"


def test_usage_from_result():
    assert pr._usage_from_result({"usage": {"prompt_tokens": 10, "completion_tokens": 5}}) == {
        "prompt": 10, "completion": 5, "total": 15,
    }
    assert pr._usage_from_result({}) == {"prompt": 0, "completion": 0, "total": 0}


def test_empty_decision_has_usage():
    out = pr._empty_decision(reason="trivial", confidence=1.0)
    assert out["usage"]["total"] == 0
    assert out["reason"] == "trivial"
