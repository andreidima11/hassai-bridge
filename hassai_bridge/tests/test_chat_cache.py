"""KV-cache friendly prompt assembly."""

from routers.chat import _inject_late_user_context, _trim_messages_kv_friendly


def test_inject_late_user_context_prefixes_last_user():
    msgs = [
        {"role": "system", "content": "stable"},
        {"role": "user", "content": "earlier"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "current question"},
    ]
    _inject_late_user_context(msgs, "[Memories]:\n• likes coffee")
    assert msgs[2]["content"] == "reply"
    assert msgs[3]["content"].startswith("[Memories]:")
    assert "current question" in msgs[3]["content"]


def test_inject_late_user_context_multimodal():
    msgs = [
        {"role": "user", "content": [
            {"type": "text", "text": "look at this"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
        ]},
    ]
    _inject_late_user_context(msgs, "[Memories]:\n• garden lights")
    assert msgs[0]["content"][0]["text"].startswith("[Memories]:")
    assert "look at this" in msgs[0]["content"][0]["text"]


def test_trim_messages_kv_friendly_preserves_order():
    msgs = [
        {"role": "system", "content": "x" * 100},
        {"role": "user", "content": "old turn " + "y" * 200},
        {"role": "assistant", "content": "old reply"},
        {"role": "user", "content": "[Memories]\n\nlatest " + "z" * 50},
    ]
    trimmed = _trim_messages_kv_friendly(msgs, max_tokens=80)
    assert trimmed[0]["role"] == "system"
    assert trimmed[-1]["role"] == "user"
    assert "[Memories]" in trimmed[-1]["content"]
    assert all("old turn" not in (m.get("content") or "") for m in trimmed)
