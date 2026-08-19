from services import vision_relay as vr


def test_normalize_vision_mode():
    assert vr.normalize_vision_mode("relay") == "relay"
    assert vr.normalize_vision_mode("direct") == "direct"
    assert vr.normalize_vision_mode("invalid", default="relay") == "relay"


def test_inject_vision_analysis():
    content = [
        {"type": "text", "text": "what is this?"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
    ]
    out = vr.inject_vision_analysis(content, "A red button on a white panel.")
    assert "what is this?" in out
    assert "[Vision analysis]" in out
    assert "red button" in out


def test_apply_vision_relay_replaces_images():
    messages = [
        {"role": "user", "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
        ]},
    ]
    out = vr.apply_vision_relay(messages, "Blue sky.")
    assert isinstance(out[0]["content"], str)
    assert "Blue sky." in out[0]["content"]
    assert "image_url" not in str(out[0]["content"])
