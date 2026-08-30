"""Inline thinking tag + OpenRouter reasoning helpers."""

from services import thinking_text as tt


def test_split_inline_thinking_tags():
    visible, thinking = tt.split_inline_thinking(
        "<thinking>\nstep one\n</thinking>\nHello there."
    )
    assert visible == "Hello there."
    assert "step one" in thinking


def test_split_think_and_reasoning_aliases():
    visible, thinking = tt.split_inline_thinking(
        "<think>alpha</think>answer<reasoning>beta</reasoning>"
    )
    assert visible == "answer"
    assert "alpha" in thinking and "beta" in thinking


def test_message_and_delta_reasoning_fields():
    assert tt.message_reasoning_text({
        "reasoning_content": "a",
        "content": "hi",
    }) == "a"
    assert tt.message_reasoning_text({
        "reasoning": "b",
    }) == "b"
    assert tt.message_reasoning_text({
        "reasoning_details": [
            {"type": "reasoning.text", "text": "part1"},
            {"type": "reasoning.summary", "summary": "part2"},
        ],
    }) == "part1part2"
    assert tt.delta_reasoning_text({
        "reasoning_details": [{"text": "chunk"}],
    }) == "chunk"


def test_stream_parser_splits_tags_across_chunks():
    p = tt.InlineThinkingStreamParser()
    v1, t1 = p.feed("<thin")
    assert v1 == "" and t1 == ""
    v2, t2 = p.feed("king>secret")
    assert v2 == ""
    assert "secret" in (t2 or p.thinking)
    v3, t3 = p.feed("</thinking>Visible")
    assert "Visible" in (v3 + p.visible)
    assert "secret" in p.thinking
    assert "<thinking>" not in p.visible
    assert "</thinking>" not in p.visible


def test_merge_thinking_dedupes():
    assert tt.merge_thinking("same", "same", "other") == "same\n\nother"
