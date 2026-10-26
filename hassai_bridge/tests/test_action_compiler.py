"""Reflex compiler tests (no live HA).

Contract: the reflex executes only on a certain target — raw entity_id,
learned alias, or a phrase equal to exactly one friendly name. Everything
else goes to the agent with the full house index. It never asks "which one?".
"""

from services import action_compiler as ac
from services import cognitive_kernel as ck
from services import cognitive_runtime as cogrt
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
        {"entity_id": "light.releu_living_l1", "state": "off",
         "attributes": {"friendly_name": "Bec balcon"}},
        {"entity_id": "light.releu_living_l3", "state": "off",
         "attributes": {"friendly_name": "Bec living"}},
        {"entity_id": "light.lampa_dormitor_1", "state": "on",
         "attributes": {"friendly_name": "Lampa Dormitor 1"}},
        {"entity_id": "light.lampa_dormitor_2", "state": "on",
         "attributes": {"friendly_name": "Lampa Dormitor 2"}},
        {"entity_id": "light.lamp_pat_a", "state": "on",
         "attributes": {"friendly_name": "Lampă pat"}},
        {"entity_id": "light.lamp_pat_b", "state": "off",
         "attributes": {"friendly_name": "Lampă pat"}},
        {"entity_id": "lock.front", "state": "locked",
         "attributes": {"friendly_name": "Yala"}},
        {"entity_id": "media_player.living", "state": "playing",
         "attributes": {"friendly_name": "Boxa Living"}},
    ]
    registry = {
        "light.living_main": {"area_id": "living"},
        "switch.living_ambient": {"area_id": "living"},
        "light.kitchen": {"area_id": "kitchen"},
        "cover.living_blinds": {"area_id": "living"},
        "light.bath": {"area_id": "baie"},
        "light.bath_mirror": {"area_id": "baie"},
        "light.releu_living_l1": {"area_id": "balcon", "name": "Bec balcon"},
        "light.releu_living_l3": {"area_id": "living", "name": "Bec living"},
        "light.lampa_dormitor_1": {"area_id": "dorm1", "name": "Lampa Dormitor 1"},
        "light.lampa_dormitor_2": {"area_id": "dorm2", "name": "Lampa Dormitor 2"},
        "light.lamp_pat_a": {"area_id": "dorm1", "name": "Lampă pat"},
        "light.lamp_pat_b": {"area_id": "dorm2", "name": "Lampă pat"},
        "lock.front": {"area_id": "hol"},
        "media_player.living": {"area_id": "living"},
    }
    areas = {
        "living": "Living",
        "kitchen": "Kitchen",
        "baie": "Baie",
        "balcon": "Balcon",
        "dorm1": "Dormitor 1",
        "dorm2": "Dormitor 2",
        "hol": "Hol",
    }
    return wm.build_from_rows(states, registry=registry, area_labels=areas)


def _compile(text: str, lang: str = "ro", aliases=None, cfg=None):
    ctx = ck.build_turn_context(user_text=text, lang=lang, cfg=cfg)
    return ac.compile_reflex(ctx, entities=_entities(), aliases=aliases)


# ── Intent lexicon ──────────────────────────────────────


def test_parse_command_verbs_and_target():
    assert gc.parse_command("stinge lampa dormitor 1") == ("turn_off", "off", "lampa dormitor 1")
    assert gc.parse_command("Turn on the kitchen light!") == ("turn_on", "on", "kitchen light")
    assert gc.parse_command("aprinde-mi te rog bec balcon") == ("turn_on", "on", "bec balcon")
    assert gc.parse_command("închide jaluzele living") == ("close", "closed", "jaluzele living")
    assert gc.parse_command("pause boxa living") == ("pause", "paused", "boxa living")


def test_parse_command_rejects_questions_and_prose():
    assert gc.parse_command("De ce s-a aprins lumina?")[0] == ""
    assert gc.parse_command("creează o automatizare la apus")[0] == ""
    assert gc.parse_command("ce glumă știi?")[0] == ""
    assert gc.parse_command("")[0] == ""


def test_can_attempt_short_control():
    assert ac.can_attempt_reflex("stinge lumina living")
    assert ac.can_attempt_reflex("turn on kitchen light")
    assert not ac.can_attempt_reflex("creează o automatizare pentru lumină")
    assert not ac.can_attempt_reflex("De ce s-a aprins lumina?")
    assert not ac.can_attempt_reflex("hello")


# ── Exact resolution → reflex ───────────────────────────


def test_exact_name_is_reflex():
    ctx = _compile("turn on kitchen light", lang="en")
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.kitchen"]
    assert ctx.hypotheses[0].service == "turn_on"
    assert ctx.hypotheses[0].expected_state == "on"


def test_numbered_lamps_resolve_exactly():
    ctx = _compile("stinge lampa dormitor 1")
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.lampa_dormitor_1"]
    ctx = _compile("stinge lampa dormitor 2")
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.lampa_dormitor_2"]


def test_friendly_name_beats_entity_slug():
    """'bec living' is the friendly name of releu_l3; slug of l1 contains 'living'."""
    ctx = _compile("aprinde bec living")
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.releu_living_l3"]


def test_diacritics_and_case_are_folded():
    ctx = _compile("Stinge Lumină Living")
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.living_main"]


def test_duplicate_name_plus_area_is_exact():
    ctx = _compile("stinge lampă pat din dormitor 2")
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.lamp_pat_b"]


def test_direct_entity_id_is_reflex():
    ctx = _compile("stinge light.kitchen")
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.kitchen"]
    assert ctx.hypotheses[0].reason == "resolved=entity_id"


def test_learned_alias_is_reflex():
    aliases = [{"surface": "becul de pe balcon", "resolves_to": "light.releu_living_l1"}]
    ctx = _compile("aprinde becul de pe balcon", aliases=aliases)
    assert ctx.path == ck.PATH_REFLEX
    assert ctx.hypotheses[0].targets == ["light.releu_living_l1"]
    assert ctx.hypotheses[0].reason == "resolved=alias"


def test_cover_service_mapping():
    ctx = _compile("închide jaluzele living")
    assert ctx.path == ck.PATH_REFLEX
    hyp = ctx.hypotheses[0]
    assert hyp.service == "close_cover"
    assert hyp.expected_state == "closed"


def test_shadow_mode_logs_instead_of_executing():
    ctx = _compile("stinge lampa dormitor 1", cfg={"performance": {"cognitive_shadow": True}})
    assert ctx.path == ck.PATH_SHADOW
    assert ctx.hypotheses[0].targets == ["light.lampa_dormitor_1"]


# ── Anything uncertain → agent, never a question ───────


def test_partial_name_goes_to_agent():
    ctx = _compile("stinge lampa dormitor")
    assert ctx.path == ck.PATH_AGENT
    assert not ctx.hypotheses


def test_duplicate_names_go_to_agent():
    ctx = _compile("stinge lampa pat")
    assert ctx.path == ck.PATH_AGENT
    assert not ctx.hypotheses


def test_area_only_goes_to_agent():
    ctx = _compile("stinge lumina din baie")
    assert ctx.path == ck.PATH_AGENT


def test_pronoun_goes_to_agent():
    ctx = _compile("stinge și pe aia")
    assert ctx.path == ck.PATH_AGENT


def test_verb_domain_mismatch_goes_to_agent():
    ctx = _compile("aprinde yala")
    assert ctx.path == ck.PATH_AGENT


def test_locks_never_silent_reflex():
    ctx = _compile("încuie yala")
    assert ctx.path == ck.PATH_AGENT
    assert ctx.goal is not None and ctx.goal.needs_approval


def test_automation_goes_to_agent():
    ctx = _compile("creează o automatizare la apus")
    assert ctx.path == ck.PATH_AGENT


def test_no_clarify_path_exists():
    assert not hasattr(ck, "PATH_CLARIFY")
    assert not hasattr(ck.TurnContext, "clarification_chips")


# ── Confirmation + undo chip ───────────────────────────


def test_confirmation_ro_uses_friendly_name():
    hyp = ck.Hypothesis(
        intent="turn_off", score=0.9, targets=["light.kitchen"], area="Kitchen",
    )
    text = ac.confirmation_text(hyp, lang="ro", entities=_entities())
    assert text == "Am stins Kitchen Light din Kitchen."


def test_undo_chip_is_structured():
    chip = cogrt._undo_chip("mut_abc123def456", "ro")
    assert chip["action"] == {"type": "undo", "ledger_id": "mut_abc123def456"}
    assert chip["kind"] == "undo"
    assert "/undo" not in chip["prompt"]
    assert "mut_" not in chip["label"]
    assert chip["display_text"] == "Anulează"
    assert cogrt._undo_chip("mut_x", "en")["label"] == "Undo"
