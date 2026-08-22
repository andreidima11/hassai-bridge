"""DeepSeek reasoning_content pass-back across stored / client-replayed history."""

from services import chat_content as cc
from services import deepseek as ds
from services import provider_capabilities as pc


def test_backfill_reasoning_from_stored_history():
    history = [
        {"role": "user", "content": "ce e prin fata casei?"},
        {
            "role": "assistant",
            "content": "Nimic suspect, boss.",
            "reasoning_content": "checked frigate events",
        },
    ]
    client_messages = [
        {"role": "user", "content": "ce e prin fata casei?"},
        {"role": "assistant", "content": "Nimic suspect, boss."},
        {"role": "user", "content": "da ultimul snap"},
    ]
    out = cc.backfill_reasoning(client_messages, history)
    assert out[1]["reasoning_content"] == "checked frigate events"
    assert out[0] == client_messages[0]
    assert "reasoning_content" not in out[2]


def test_backfill_reasoning_ignores_whitespace_differences():
    history = [
        {"role": "assistant", "content": "Line one\n\nLine two", "reasoning_content": "cot"},
    ]
    messages = [{"role": "assistant", "content": "Line one Line two"}]
    assert cc.backfill_reasoning(messages, history)[0]["reasoning_content"] == "cot"


def test_backfill_reasoning_keeps_existing():
    history = [{"role": "assistant", "content": "hi", "reasoning_content": "stored"}]
    messages = [{"role": "assistant", "content": "hi", "reasoning_content": "live"}]
    assert cc.backfill_reasoning(messages, history)[0]["reasoning_content"] == "live"


def test_backfill_reasoning_no_history_is_noop():
    messages = [{"role": "assistant", "content": "hi"}]
    assert cc.backfill_reasoning(messages, []) is messages


def test_full_replay_chain_leaves_no_assistant_without_reasoning():
    """End state sent to DeepSeek: every assistant turn carries the field."""
    history = [
        {"role": "assistant", "content": "Nimic suspect.", "reasoning_content": "cot-1"},
    ]
    messages = [
        {"role": "user", "content": "ce e prin fata casei?"},
        {"role": "assistant", "content": "Nimic suspect."},
        {"role": "user", "content": "da ultimul snap"},
    ]
    filled = cc.backfill_reasoning(messages, history)
    shaped = pc.prepare_messages_for_request(
        {"type": "deepseek"},
        filled,
        tools=[{"type": "function"}],
        thinking={"enabled": False},
    )
    assistants = [m for m in shaped if m.get("role") == "assistant"]
    assert assistants and all("reasoning_content" in m for m in assistants)
    assert assistants[0]["reasoning_content"] == "cot-1"


def test_tool_loop_turn_keeps_reasoning_for_deepseek():
    msg = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "frigate_events", "arguments": "{}"}},
        ],
        "reasoning_content": "need a snapshot",
    }
    out = pc.assistant_turn({"type": "deepseek"}, msg)
    assert out["reasoning_content"] == "need a snapshot"
    assert out["tool_calls"] == msg["tool_calls"]


def test_fallback_strips_reasoning_for_poisoned_history():
    msgs = ds.prepare_messages_for_tools([{"role": "assistant", "content": "x"}])
    assert msgs[0]["reasoning_content"] == ""
    assert "reasoning_content" not in ds.strip_reasoning(msgs)[0]
