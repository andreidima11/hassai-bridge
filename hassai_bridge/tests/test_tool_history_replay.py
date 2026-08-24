"""Follow-up commands must see that the previous turn really called a tool.

Replaying only the assistant's sentence taught weaker models the wrong lesson:
they saw "user asks for an action, assistant says it is done" with no tool in
sight, and copied that on the next command. Nothing here depends on the
language of the request — it is the shape of the transcript that matters.
"""

from __future__ import annotations

from routers.chat import _sanitize_message_roles, _tool_trace
from services import chat_content as cc


ROW_WITH_TOOL = {
    "role": "assistant",
    "content": "Am aprins terasa 2.",
    "tool_calls": [{
        "id": "c1",
        "name": "ha_call_service",
        "arguments": '{"entity_id": "light.terasa_2", "service": "turn_on"}',
        "result": "Turned on light.terasa_2",
    }],
}


def test_assistant_turn_replays_call_result_and_answer():
    out = cc.row_to_messages(ROW_WITH_TOOL, user_id="u")
    assert [m["role"] for m in out] == ["assistant", "tool", "assistant"]
    assert out[0]["tool_calls"][0]["function"]["name"] == "ha_call_service"
    assert out[1]["tool_call_id"] == "c1"
    assert out[1]["content"] == "Turned on light.terasa_2"
    assert out[2]["content"] == "Am aprins terasa 2."


def test_replay_can_be_switched_off_for_older_turns():
    out = cc.row_to_messages(ROW_WITH_TOOL, user_id="u", replay_tools=False)
    assert len(out) == 1
    assert "tool_calls" not in out[0]


def test_row_without_tools_is_unchanged():
    out = cc.row_to_messages({"role": "assistant", "content": "salut"}, user_id="u")
    assert out == [{"role": "assistant", "content": "salut"}]


def test_user_rows_are_never_expanded():
    row = {"role": "user", "content": "stinge terasa 2", "tool_calls": [{"name": "x"}]}
    assert len(cc.row_to_messages(row, user_id="u")) == 1


def test_tool_call_without_a_recorded_result_still_replays():
    row = {**ROW_WITH_TOOL, "tool_calls": [{"id": "c9", "name": "ha_call_service"}]}
    out = cc.row_to_messages(row, user_id="u")
    assert out[1]["role"] == "tool"
    assert out[1]["content"]  # a placeholder, never an empty tool turn


# ── Keeping calls and results paired ───────────────

def test_orphan_tool_turn_is_dropped():
    msgs = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "gone", "content": "leftover"},
        {"role": "assistant", "content": "ok"},
    ]
    out = cc.drop_orphan_tool_messages(msgs)
    assert [m["role"] for m in out] == ["user", "assistant"]


def test_unanswered_tool_call_is_stripped_but_text_survives():
    msgs = [
        {"role": "assistant", "content": "am facut", "tool_calls": [{"id": "c1"}]},
    ]
    out = cc.drop_orphan_tool_messages(msgs)
    assert "tool_calls" not in out[0]
    assert out[0]["content"] == "am facut"


def test_unanswered_tool_call_with_no_text_is_removed():
    msgs = [{"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]}]
    assert cc.drop_orphan_tool_messages(msgs) == []


def test_paired_call_and_result_are_kept():
    msgs = [
        {"role": "user", "content": "aprinde"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "done"},
        {"role": "assistant", "content": "gata"},
    ]
    assert cc.drop_orphan_tool_messages(msgs) == msgs


def test_sanitizer_does_not_merge_assistants_carrying_tool_calls():
    msgs = [
        {"role": "user", "content": "aprinde"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "tool_call_id": "c1", "content": "done"},
        {"role": "assistant", "content": "gata"},
    ]
    out = _sanitize_message_roles(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "assistant"]
    assert out[1]["tool_calls"]


# ── Capturing the trace from a finished turn ───────

def test_tool_trace_pairs_calls_with_their_results():
    augmented = [
        {"role": "user", "content": "aprinde"},
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "type": "function",
             "function": {"name": "ha_call_service", "arguments": '{"a":1}'}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "Turned on"},
        {"role": "assistant", "content": "gata"},
    ]
    trace = _tool_trace(augmented, 1)
    assert len(trace) == 1
    assert trace[0]["name"] == "ha_call_service"
    assert trace[0]["arguments"] == '{"a":1}'
    assert trace[0]["result"] == "Turned on"


def test_tool_trace_ignores_history_before_the_current_turn():
    augmented = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "old", "function": {"name": "from_history"}},
        ]},
        {"role": "tool", "tool_call_id": "old", "content": "x"},
        {"role": "user", "content": "stinge"},
    ]
    assert _tool_trace(augmented, 2) == []


def test_tool_trace_truncates_long_results():
    augmented = [
        {"role": "assistant", "content": "", "tool_calls": [
            {"id": "c1", "function": {"name": "ha_list_entities", "arguments": "{}"}},
        ]},
        {"role": "tool", "tool_call_id": "c1", "content": "x" * 5000},
    ]
    trace = _tool_trace(augmented, 0)
    assert 0 < len(trace[0]["result"]) <= 240


def test_turn_with_no_tools_records_nothing():
    assert _tool_trace([{"role": "assistant", "content": "salut"}], 0) == []
