"""Opportunity engine evidence rules."""

from services import opportunity_engine as opp


def test_stuck_open_needs_duration(monkeypatch):
    import time

    eid = "cover.garage_door"
    now = time.time()
    opp._RECENT[eid] = [
        {"ts": now - 40 * 60, "state": "open", "old": "closed"},
        {"ts": now - 10, "state": "open", "old": "open"},
    ]
    hits = opp.evaluate_entity(eid, "open")
    assert any(h["kind"] == "stuck_open" for h in hits)


def test_recent_open_not_flagged():
    import time

    eid = "cover.living"
    now = time.time()
    opp._RECENT[eid] = [{"ts": now - 60, "state": "open", "old": "closed"}]
    assert opp.evaluate_entity(eid, "open") == []


def test_suggestion_chip_ro():
    chip = opp.suggestion_chip(
        {"kind": "stuck_open", "entity_id": "cover.garage_door"},
        lang="ro",
    )
    assert "Închide" in chip["label"]
    assert "cover.garage_door" in chip["prompt"]
