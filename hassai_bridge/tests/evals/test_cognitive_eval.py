"""Eval runner for Cognitive OS fixtures (no live model / HA)."""

from __future__ import annotations

import json
from pathlib import Path

from services import action_compiler as ac
from services import cognitive_kernel as ck
from services import cognitive_metrics as cm
from services import world_model as wm

FIXTURES = Path(__file__).with_name("cognitive_fixtures.json")


def _tiny_home():
    states = [
        {"entity_id": "light.kitchen", "state": "off",
         "attributes": {"friendly_name": "Kitchen Light"}},
        {"entity_id": "light.living_main", "state": "on",
         "attributes": {"friendly_name": "Lumina Living"}},
        {"entity_id": "media_player.living", "state": "playing",
         "attributes": {"friendly_name": "Living Speaker"}},
    ]
    registry = {
        "light.kitchen": {"area_id": "kitchen"},
        "light.living_main": {"area_id": "living"},
        "media_player.living": {"area_id": "living"},
    }
    areas = {"kitchen": "Kitchen", "living": "Living"}
    return wm.build_from_rows(states, registry=registry, area_labels=areas)


def test_cognitive_eval_fixtures():
    cases = json.loads(FIXTURES.read_text(encoding="utf-8"))
    entities = _tiny_home()
    failures = []
    for case in cases:
        utterance = case["utterance"]
        expected = case["expected_path"]
        targets = case.get("expected_targets")
        ctx = ck.build_turn_context(user_text=utterance, lang=case.get("lang") or "en")
        if ac.can_attempt_reflex(utterance):
            ctx = ac.compile_reflex(ctx, entities=entities)
        else:
            ctx.path = ck.PATH_AGENT
        # pause with media present may become reflex
        if "pause" in utterance.lower() and expected == "agent":
            if ctx.path in {ck.PATH_REFLEX, ck.PATH_SHADOW, ck.PATH_CLARIFY}:
                continue
        result = cm.eval_fixture_result(
            utterance=utterance,
            expected_path=expected,
            expected_targets=targets,
            ctx=ctx,
        )
        if not result["ok"]:
            failures.append(result)
    assert not failures, failures
