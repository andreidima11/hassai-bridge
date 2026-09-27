"""Cognitive OS: policy, plan DAG, aliases, experience, metrics, evals."""

from __future__ import annotations

import pytest

from services import autonomy_policy as ap
from services import cognitive_kernel as ck
from services import cognitive_metrics as cm
from services import experience_compiler as ec
from services import plan_engine as pe
from services import working_memory as wmem
from services import world_model as wm
from services import action_compiler as ac
from services import tool_awareness as taw


@pytest.fixture()
def memory_db(tmp_path, monkeypatch):
    import database as db_mod
    from core import database as core_db

    core_db.close_all_connections()
    db_path = tmp_path / "hassai.db"
    monkeypatch.setattr(core_db, "DB_PATH", db_path)
    monkeypatch.setattr(db_mod, "DB_PATH", db_path)
    core_db.init_db()
    yield db_path
    core_db.close_all_connections()


def test_policy_allows_lights():
    assert ap.decide(tool="ha_call_service", domain="light", service="turn_off") == ap.ALLOW


def test_policy_asks_locks():
    assert ap.decide(tool="ha_call_service", domain="lock", service="unlock") == ap.ASK


def test_policy_asks_garage_cover():
    assert ap.decide(
        tool="ha_call_service",
        domain="cover",
        service="open_cover",
        entity_ids=["cover.garage_door"],
    ) == ap.ASK


def test_policy_deny_explicit_entity():
    cfg = {"autonomy_policy": {"deny_entities": ["light.secret"]}}
    assert ap.decide(
        tool="ha_call_service",
        domain="light",
        service="turn_off",
        entity_ids=["light.secret"],
        cfg=cfg,
    ) == ap.DENY


def test_policy_proactive_disabled_asks():
    cfg = {"autonomy_policy": {"proactive_enabled": False}}
    assert ap.decide(
        tool="ha_call_service",
        domain="light",
        service="turn_off",
        entity_ids=["light.x"],
        cfg=cfg,
        proactive=True,
    ) == ap.ASK


def test_plan_dag_ready_order():
    plan = pe.build_control_plan(
        entity_ids=["light.kitchen"],
        domain="light",
        service="turn_off",
        expected_state="off",
    )
    ready = pe.ready_nodes(plan, set())
    assert all(n.phase == pe.PHASE_READ for n in ready)
    done = {n.id for n in ready}
    ready2 = pe.ready_nodes(plan, done)
    assert any(n.phase == pe.PHASE_WRITE for n in ready2)


def test_verify_delta_ok():
    text = "OK: called light.turn_off on light.kitchen\nverify:\nlight.kitchen\nstate: off\n"
    out = pe.verify_delta(text, "off", ["light.kitchen"])
    assert out["ok"] is True


@pytest.mark.asyncio
async def test_execute_plan_parallel_reads():
    calls = []

    async def invoke(tool, args):
        calls.append(tool)
        if tool == "ha_get_state":
            return f"entity_id: {args['entity_id']}\nstate: on"
        return "OK: called light.turn_off on light.a\nverify:\nstate: off"

    plan = pe.build_control_plan(
        entity_ids=["light.a", "light.b"],
        domain="light",
        service="turn_off",
        expected_state="off",
    )
    result = await pe.execute_plan(plan, invoke=invoke)
    assert result["ok"] or "write_0" in result["done"]
    assert calls.count("ha_get_state") >= 2


def test_working_memory_roundtrip(memory_db):
    wmem.save_working_set("u1", "s1", {
        "last_entities": ["light.kitchen"],
        "last_area": "Kitchen",
        "last_action": "turn_on",
    })
    cur = wmem.load_working_set("u1", "s1")
    assert cur["last_entities"] == ["light.kitchen"]
    assert cur["last_area"] == "Kitchen"


def test_learn_alias(memory_db):
    row = wmem.learn_alias("u1", "ambient", "switch.living_ambient", source="correction")
    assert row["ok"]
    hit = wmem.resolve_alias("u1", "Ambient")
    assert hit and hit["resolves_to"] == "switch.living_ambient"


def test_experience_compile_and_match(memory_db):
    skill = ec.compile_from_trace(
        user_id="u1",
        trigger="seară de film",
        tool_steps=[
            {"name": "ha_call_service", "args": {"domain": "light", "service": "turn_off", "entity_id": "light.living"}},
            {"name": "ha_call_service", "args": {"domain": "media_player", "service": "turn_on", "entity_id": "media_player.tv"}},
        ],
        entity_ids=["light.living", "media_player.tv"],
        area="Living",
        success=True,
    )
    assert skill and skill["status"] == "shadow"
    # Reinforce
    for _ in range(3):
        ec.compile_from_trace(
            user_id="u1",
            trigger="seară de film",
            tool_steps=skill["recipe"]["steps"],
            entity_ids=["light.living"],
            success=True,
        )
    ec.maybe_promote(skill["skill_id"])
    promoted = ec.match_skill("u1", "seară de film", include_shadow=True)
    assert promoted is not None


def test_pick_dominant_hypothesis():
    hyps = [
        ck.Hypothesis(intent="turn_off", score=0.9, targets=["light.a"]),
        ck.Hypothesis(intent="close", score=0.5, targets=["cover.a"]),
    ]
    top = ck.pick_dominant_hypothesis(hyps)
    assert top and top.targets == ["light.a"]
    close = [
        ck.Hypothesis(intent="turn_off", score=0.8, targets=["light.a"]),
        ck.Hypothesis(intent="close", score=0.75, targets=["cover.a"]),
    ]
    assert ck.pick_dominant_hypothesis(close) is None


def test_late_context_block():
    ctx = ck.build_turn_context(user_text="x")
    ctx.working_memory = {"last_entities": ["light.a"], "last_area": "Living"}
    ctx.world_snippet = "candidates:\n- light.a"
    ctx.goal = ck.GoalContract(goal="turn_off light.a", success_criteria="state=off")
    block = ck.late_context_block(ctx)
    assert "[Working memory]" in block
    assert "[House index]" in block
    assert "[Goal]" in block


def test_skip_pack_router_pause_status():
    assert taw.should_skip_pack_router_for_control("pause the music")
    assert taw.should_skip_pack_router_for_control("e pornit irigatorul?")


def test_eval_fixtures_reflex_paths():
    states = [
        {"entity_id": "light.kitchen", "state": "off",
         "attributes": {"friendly_name": "Kitchen Light"}},
        {"entity_id": "light.living_main", "state": "on",
         "attributes": {"friendly_name": "Lumina Living"}},
    ]
    registry = {
        "light.kitchen": {"area_id": "kitchen"},
        "light.living_main": {"area_id": "living"},
    }
    areas = {"kitchen": "Kitchen", "living": "Living"}
    entities = wm.build_from_rows(states, registry=registry, area_labels=areas)

    cases = [
        ("turn on kitchen light", "reflex", ["light.kitchen"]),
        ("hello there", "agent", None),
        ("creează o automatizare", "agent", None),
    ]
    for utterance, expected_path, targets in cases:
        ctx = ck.build_turn_context(user_text=utterance, lang="en")
        if ac.can_attempt_reflex(utterance):
            ctx = ac.compile_reflex(ctx, entities=entities)
        else:
            ctx.path = ck.PATH_AGENT
        result = cm.eval_fixture_result(
            utterance=utterance,
            expected_path=expected_path,
            expected_targets=targets,
            ctx=ctx,
        )
        assert result["ok"], result


def test_scorecard_empty(memory_db):
    card = cm.scorecard(user_id="nobody", since_hours=1)
    assert card["turns"] == 0
