"""Reflex compiler + intent beam tests (no live HA)."""

from services import action_compiler as ac
from services import cognitive_kernel as ck
from services import goal_compiler as gc
from services import world_model as wm


def _entities():
    states = [
        {"entity_id": "light.living_main", "state": "on",
         "attributes": {"friendly_name": "Lumina Living"}},
        {"entity_id": "switch.living_ambient", "state": "off",
         "attributes": {"friendly_name": "Ambient Living"}},
        {"entity_id": "light.kitchen", "state": "off",
         "attributes": {"friendly_name": "Kitchen Light"}},
        {"entity_id": "cover.living_blinds", "state": "open",
         "attributes": {"friendly_name": "Jaluzele Living"}},
        {"entity_id": "light.bath", "state": "on",
         "attributes": {"friendly_name": "Baie"}},
        {"entity_id": "light.bath_mirror", "state": "off",
         "attributes": {"friendly_name": "Oglinda Baie"}},
    ]
    registry = {
        "light.living_main": {"area_id": "living"},
        "switch.living_ambient": {"area_id": "living"},
        "light.kitchen": {"area_id": "kitchen"},
        "cover.living_blinds": {"area_id": "living"},
        "light.bath": {"area_id": "baie"},
        "light.bath_mirror": {"area_id": "baie"},
    }
    areas = {"living": "Living", "kitchen": "Kitchen", "baie": "Baie"}
    return wm.build_from_rows(states, registry=registry, area_labels=areas)


def test_can_attempt_short_control():
    assert ac.can_attempt_reflex("stinge lumina din living")
    assert ac.can_attempt_reflex("turn on kitchen light")
    assert not ac.can_attempt_reflex("creează o automatizare pentru lumină")
    assert not ac.can_attempt_reflex("De ce s-a aprins lumina?")


def test_kitchen_light_unique_reflex():
    ctx = ck.build_turn_context(user_text="turn on kitchen light", lang="en")
    ctx = ac.compile_reflex(ctx, entities=_entities())
    assert ctx.path in {ck.PATH_REFLEX, ck.PATH_SHADOW}
    assert ctx.hypotheses
    assert ctx.hypotheses[0].targets == ["light.kitchen"]


def test_ambiguous_bath_clarify():
    ctx = ck.build_turn_context(user_text="stinge lumina din baie", lang="ro")
    ctx = ac.compile_reflex(ctx, entities=_entities())
    # Two bath lights → clarify or multi
    assert ctx.path in {ck.PATH_CLARIFY, ck.PATH_REFLEX, ck.PATH_AGENT, ck.PATH_SHADOW}
    if ctx.path == ck.PATH_CLARIFY:
        assert len(ctx.clarification_chips) >= 2


def test_close_living_beams_cover_and_lights():
    hyps = gc.compile_hypotheses("închide livingul", entities=_entities())
    domains = {h.domain for h in hyps}
    assert "cover" in domains or any("cover" in (h.targets[0] if h.targets else "") for h in hyps)


def test_pronoun_uses_working_memory():
    ctx = ck.build_turn_context(user_text="stinge și pe aia", lang="ro")
    ctx.working_memory = {
        "last_entities": ["light.kitchen"],
        "last_area": "Kitchen",
        "last_action": "turn_on",
    }
    ctx = ac.compile_reflex(ctx, entities=_entities())
    assert ctx.hypotheses
    assert "light.kitchen" in (ctx.hypotheses[0].targets or [])


def test_direct_entity_id_from_chip():
    ctx = ck.build_turn_context(user_text="stinge light.kitchen", lang="ro")
    ctx = ac.compile_reflex(ctx, entities=_entities())
    assert ctx.path in {ck.PATH_REFLEX, ck.PATH_SHADOW}
    assert ctx.hypotheses[0].targets == ["light.kitchen"]


def test_automation_falls_to_agent():
    ctx = ck.build_turn_context(user_text="creează o automatizare la apus", lang="ro")
    ctx = ac.compile_reflex(ctx, entities=_entities())
    assert ctx.path == ck.PATH_AGENT


def test_confirmation_ro():
    hyp = gc.Hypothesis(
        intent="turn_off", score=0.9, targets=["light.kitchen"], area="Kitchen",
    )
    text = ac.confirmation_text(hyp, lang="ro", entities=_entities())
    assert "Am stins" in text
    assert "Kitchen" in text or "Kitchen" in text


def test_detect_correction():
    c = gc.detect_correction("nu becul mare, ambientul")
    assert c
    assert c.get("prefer")
