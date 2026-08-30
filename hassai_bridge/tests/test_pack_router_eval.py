"""Eval fixtures: pack router prompt contract (no live model calls)."""

from services import pack_router as pr

ELIGIBLE = {
    "entities": "Read entities and states",
    "control": "Turn devices on/off, call services",
    "calendar": "Calendars and todos",
    "frigate": "Cameras and snapshots",
    "automations": "Create/edit automations",
    "hacs": "HACS install/update",
    "bridge_write": "Change HASSAI settings",
    "media_write": "Delete media files",
    "image_gen": "Generate images",
}

# utterance → expected packs when model returns the fixture JSON
CASES = [
    ("hi", {"packs": [], "confidence": 1.0}, set()),
    ("stinge lumina din living", {"packs": ["entities", "control"], "confidence": 0.95}, {"entities", "control"}),
    ("turn off the kitchen lights", {"packs": ["entities", "control"], "confidence": 0.9}, {"entities", "control"}),
    ("what's on the porch camera", {"packs": ["frigate"], "confidence": 0.85}, {"frigate"}),
    ("adaugă pe lista de cumpărături lapte", {"packs": ["calendar"], "confidence": 0.8}, {"calendar"}),
    ("instalează un card din hacs", {"packs": ["hacs"], "confidence": 0.85}, {"hacs"}),
    ("creează o automatizare la apus", {"packs": ["automations", "entities"], "confidence": 0.88}, {"automations", "entities"}),
    ("change your web search setting", {"packs": ["bridge_write"], "confidence": 0.75}, {"bridge_write"}),
    ("delete the photo in /media/foo.jpg", {"packs": ["media_write"], "confidence": 0.9}, {"media_write"}),
    ("draw a logo of a house", {"packs": ["image_gen"], "confidence": 0.9}, {"image_gen"}),
    ("thanks!", {"packs": [], "confidence": 0.99}, set()),
    # low confidence fixture → cleared
    ("maybe something with cameras or lights?", {"packs": ["frigate", "control"], "confidence": 0.3}, set()),
]


def test_eval_fixtures_parse_as_expected():
    import json

    for utterance, fixture, expected_packs in CASES:
        raw = json.dumps(fixture)
        out = pr.parse_router_response(raw, ELIGIBLE)
        assert out["packs"] == expected_packs, (utterance, out)
        if fixture["confidence"] < pr.CONFIDENCE_FLOOR:
            assert out["reason"] == "low_confidence"
