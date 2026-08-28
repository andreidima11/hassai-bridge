"""Provider Personality must layer on the global system prompt and win for tone."""

from __future__ import annotations

from routers.chat import build_stable_system_parts, resolve_provider_personality


def test_resolve_keeps_global_when_personality_set():
    cfg = {"system_prompt": "You are HASSAI."}
    active = {"system_prompt": "Answer in Romanian. Be witty."}
    base, persona = resolve_provider_personality(active, cfg)
    assert base == "You are HASSAI."
    assert persona == "Answer in Romanian. Be witty."


def test_resolve_empty_personality_uses_global_only():
    cfg = {"system_prompt": "You are HASSAI."}
    base, persona = resolve_provider_personality({"system_prompt": "  "}, cfg)
    assert base == "You are HASSAI."
    assert persona == ""


def test_resolve_personality_alone_when_global_empty():
    base, persona = resolve_provider_personality(
        {"system_prompt": "Be a pirate."},
        {"system_prompt": ""},
    )
    assert base == ""
    assert persona == "Be a pirate."


def test_stable_parts_append_personality_after_bridge_hints():
    parts = build_stable_system_parts(
        global_prompt="You are HASSAI.",
        provider_personality="Speak like a pirate.",
        bridge_hint="[HASSAI Bridge] You run as an add-on.",
        memory_hint="Use memories when relevant.",
        agentic="Work style: autonomous agent.",
    )
    assert parts[0] == "You are HASSAI."
    assert "[HASSAI Bridge]" in parts[1]
    assert "memories" in parts[2]
    assert "autonomous agent" in parts[3]
    assert parts[-1].startswith("Personality (follow for tone")
    assert "Speak like a pirate." in parts[-1]


def test_stable_parts_omit_personality_header_when_empty():
    parts = build_stable_system_parts(
        global_prompt="You are HASSAI.",
        provider_personality="",
        agentic="Work style: autonomous agent.",
    )
    assert parts == ["You are HASSAI.", "Work style: autonomous agent."]
    assert not any(p.startswith("Personality") for p in parts)


def test_personality_does_not_replace_global_in_joined_prompt():
    """Regression: short provider notes must not drop the global identity."""
    parts = build_stable_system_parts(
        global_prompt="You are HASSAI, a Home Assistant copilot.",
        provider_personality="Răspunde mereu în română.",
        bridge_hint="[HASSAI Bridge] identity boilerplate",
        agentic="Finish the job.",
    )
    joined = "\n\n".join(parts)
    assert "You are HASSAI, a Home Assistant copilot." in joined
    assert "Răspunde mereu în română." in joined
    assert joined.index("You are HASSAI") < joined.index("Răspunde mereu")
    assert joined.index("identity boilerplate") < joined.index("Răspunde mereu")
