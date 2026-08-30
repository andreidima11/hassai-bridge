"""Unit tests for LLM pack router parsing (no live HTTP)."""

from services import pack_router as pr


ELIGIBLE = {
    "entities": "Read entities",
    "control": "Call services",
    "frigate": "Cameras",
    "media_write": "Delete media files",
}


def test_trivial_message():
    assert pr.is_trivial_message("") is True
    assert pr.is_trivial_message("ok") is True
    assert pr.is_trivial_message("hello") is False


def test_parse_ok():
    raw = '{"packs":["entities","control","nope"],"confidence":0.9}'
    out = pr.parse_router_response(raw, ELIGIBLE)
    assert out["reason"] == "ok"
    assert out["packs"] == {"entities", "control"}
    assert out["confidence"] == 0.9


def test_parse_low_confidence_clears_packs():
    raw = '{"packs":["frigate"],"confidence":0.2}'
    out = pr.parse_router_response(raw, ELIGIBLE)
    assert out["reason"] == "low_confidence"
    assert out["packs"] == set()
    assert out["raw_packs"] == ["frigate"]


def test_parse_embedded_json():
    raw = 'Sure.\n```json\n{"packs":["media_write"],"confidence":0.8}\n```'
    out = pr.parse_router_response(raw, ELIGIBLE)
    assert out["packs"] == {"media_write"}


def test_parse_bad_json():
    out = pr.parse_router_response("not json", ELIGIBLE)
    assert out["packs"] == set()
    assert out["reason"] == "bad_json"


def test_build_messages_lists_catalog():
    msgs = pr.build_router_messages("stinge lumina", ELIGIBLE)
    assert msgs[0]["role"] == "system"
    assert "entities" in msgs[1]["content"]
    assert "stinge lumina" in msgs[1]["content"]
