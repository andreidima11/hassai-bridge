"""Narration emitted alongside tool calls belongs in the step timeline."""

from __future__ import annotations

from routers.chat import _SAY_DETAIL_MAX, _say_event


def test_say_event_shape():
    ev = _say_event(2, "Hai să caut becul de pe terasă.")
    assert ev == {
        "id": "say-2",
        "name": "say",
        "detail": "Hai să caut becul de pe terasă.",
        "status": "done",
    }


def test_say_event_collapses_whitespace():
    ev = _say_event(0, "  Acum\n\n  îl   comut.  ")
    assert ev["detail"] == "Acum îl comut."


def test_say_event_ignores_empty():
    assert _say_event(0, "") is None
    assert _say_event(0, "   \n ") is None
    assert _say_event(0, None) is None


def test_say_event_truncates_on_word_boundary():
    ev = _say_event(1, "cuvant " * 200)
    assert len(ev["detail"]) <= _SAY_DETAIL_MAX + 1
    assert ev["detail"].endswith("…")
    assert "cuvan…" not in ev["detail"]


def test_say_ids_are_unique_per_round():
    # Distinct ids keep every round's note in the timeline instead of
    # overwriting the previous one when activity is compacted.
    assert _say_event(0, "a b c")["id"] != _say_event(1, "a b c")["id"]


def test_say_steps_are_not_counted_as_tools():
    from routers.chat import _compact_activity

    rows = _compact_activity([
        {"id": "say-0", "name": "say", "detail": "Îl caut.", "status": "done"},
        {"id": "call_1", "name": "ha_call_service", "detail": "light.turn_off", "status": "done"},
    ])
    assert [r["name"] for r in rows] == ["say", "ha_call_service"]
