import base64
import tempfile
from pathlib import Path

import pytest

from services import chat_content as cc
from services import chat_media as cm


def test_content_text_from_multimodal():
    content = [
        {"type": "text", "text": "  hello  "},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
    ]
    assert cc.content_text(content) == "hello"
    assert cc.has_images(content) is True


def test_save_uploaded_file_png(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "UPLOADS_ROOT", tmp_path / "uploads")
    tiny = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    att = cm.save_uploaded_file("tester", tiny, filename="dot.png", content_type="image/png")
    assert att["id"]
    assert att["mime"] == "image/png"
    assert cm.resolve_attachment_path("tester", att["id"]).is_file()


def test_build_multimodal_content_from_attachments(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "UPLOADS_ROOT", tmp_path)
    user_id = "tester"
    tiny = base64.b64encode(b"\x89PNG\r\n\x1a\n").decode("ascii")
    data_url = f"data:image/png;base64,{tiny}"
    saved = cm.persist_attachments_from_content(
        user_id,
        [{"type": "image_url", "image_url": {"url": data_url}}],
    )
    assert len(saved) == 1
    built = cc.build_multimodal_content("what is this?", saved, user_id=user_id)
    assert isinstance(built, list)
    assert built[0]["type"] == "text"
    assert built[1]["type"] == "image_url"


def test_sanitize_does_not_crash_on_multimodal():
    from routers.chat import _sanitize_message_roles

    messages = [
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]},
    ]
    cleaned = _sanitize_message_roles(messages)
    assert cleaned[0]["role"] == "user"
    assert isinstance(cleaned[0]["content"], list)


def test_messages_have_images():
    assert cc.messages_have_images([]) is False
    assert cc.messages_have_images([{"role": "user", "content": "hello"}]) is False
    assert cc.messages_have_images([
        {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]},
    ]) is True
    # Assistant Frigate/Imagine snaps must not trigger vision routing
    assert cc.messages_have_images([
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Detected 2 people"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}},
            ],
        },
    ]) is False


def test_strip_non_user_images():
    msgs = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "image_url", "image_url": {"url": "data:x"}}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "snap"},
                {"type": "image_url", "image_url": {"url": "data:y"}},
            ],
        },
    ]
    cleaned = cc.strip_non_user_images(msgs)
    assert cc.has_images(cleaned[0]["content"]) is True
    assert cleaned[1]["content"] == "snap"
    assert cc.messages_have_images(cleaned) is True


def test_row_to_message_skips_assistant_attachments(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "UPLOADS_ROOT", tmp_path)
    user_id = "tester"
    tiny = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
    )
    att = cm.save_uploaded_file(user_id, tiny, filename="frigate.jpg", content_type="image/jpeg")
    user_row = cc.row_to_message(
        {"role": "user", "content": "what is this?", "attachments": [att]},
        user_id=user_id,
    )
    asst_row = cc.row_to_message(
        {"role": "assistant", "content": "Two people at the gate", "attachments": [att]},
        user_id=user_id,
    )
    assert isinstance(user_row["content"], list)
    assert cc.has_images(user_row["content"]) is True
    assert isinstance(asst_row["content"], str)
    assert "Photos shown in chat" in asst_row["content"] or "frigate" in asst_row["content"].lower()
    assert cc.has_images(asst_row["content"]) is False


def test_provider_supports_vision():
    from services import providers as prov

    assert prov.provider_supports_vision({"model": "gpt-4o-mini"}) is True
    assert prov.provider_supports_vision({"model": "claude-3-5-sonnet"}) is True
    assert prov.provider_supports_vision({"model": "llama-3.1-8b"}) is False
    assert prov.provider_supports_vision({"model": "gpt-4o-mini", "supports_vision": False}) is False
    assert prov.provider_supports_vision({"model": "llama-3.1-8b", "supports_vision": True}) is True
    assert prov.provider_supports_vision({"type": "grok", "model": "grok-4.6"}) is True
    assert prov.provider_supports_vision({"type": "grok", "model": "grok-2-vision-1212"}) is True
    assert prov.provider_supports_vision({"type": "grok", "model": "grok-4.6", "supports_vision": False}) is False
    assert prov.provider_supports_vision({"type": "grok", "model": ""}) is False


def test_recall_provider_uses_image_provider_when_set():
    from routers.chat import _recall_provider

    active = {"id": "primary", "model": "llama-3.1-8b"}
    secondary = {"id": "secondary", "model": "gpt-4o-mini"}
    vision = {"id": "vision", "model": "gpt-4o"}
    img_gen = {"id": "imggen", "type": "grok", "model": "grok-4.6"}
    tool_calls = [{"function": {"name": "web_search"}}]

    assert _recall_provider(tool_calls, active, secondary)["id"] == "secondary"
    assert _recall_provider(tool_calls, active, secondary, image_provider=vision)["id"] == "vision"
    assert _recall_provider(
        [{"function": {"name": "ha_call_service"}}], active, secondary, image_provider=vision,
    )["id"] == "vision"
    assert _recall_provider(
        [{"function": {"name": "generate_image"}}], active, secondary, image_gen_provider=img_gen,
    )["id"] == "imggen"
    assert _recall_provider(
        [{"function": {"name": "generate_image"}}], active, secondary,
    )["id"] == "primary"


def test_resolve_image_provider(monkeypatch):
    from services import providers as prov

    primary = {"id": "p1", "vision_provider": "vis1", "secondary_provider": "sec1"}
    vision = {"id": "vis1", "model": "gpt-4o"}
    secondary = {"id": "sec1", "model": "gpt-4o-mini"}

    monkeypatch.setattr(prov, "get_vision_provider", lambda p=None: vision)
    assert prov.resolve_image_provider(primary, secondary) is vision

    monkeypatch.setattr(prov, "get_vision_provider", lambda p=None: None)
    assert prov.resolve_image_provider(primary, secondary) is secondary

    monkeypatch.setattr(prov, "get_secondary_provider", lambda p=None: secondary)
    assert prov.resolve_image_provider(primary) is secondary

    grok_vision = {"id": "grok-vis", "type": "grok", "model": "grok-2-vision-1212"}
    monkeypatch.setattr(prov, "get_vision_provider", lambda p=None: None)
    monkeypatch.setattr(prov, "get_secondary_provider", lambda p=None: None)
    monkeypatch.setattr(prov, "find_global_vision_secondary", lambda: grok_vision)
    assert prov.resolve_image_provider({"id": "grok-main", "type": "grok", "model": "grok-4.6"}) is grok_vision


def test_resolve_image_generation_provider(monkeypatch):
    from services import providers as prov

    grok_primary = {"id": "grok-main", "type": "grok", "model": "grok-4.6"}
    assert prov.resolve_image_generation_provider(grok_primary) is grok_primary

    deepseek = {"id": "ds", "type": "deepseek", "model": "deepseek-chat", "image_generation_provider": "grok-gen"}
    grok_gen = {"id": "grok-gen", "type": "grok", "model": "grok-4.6"}
    monkeypatch.setattr(prov, "get_image_generation_provider", lambda p=None: grok_gen)
    assert prov.resolve_image_generation_provider(deepseek) is grok_gen

    monkeypatch.setattr(prov, "get_image_generation_provider", lambda p=None: None)
    monkeypatch.setattr(prov, "find_global_image_generation_secondary", lambda: grok_gen)
    assert prov.resolve_image_generation_provider(deepseek) is grok_gen


def test_vision_required_error_localized():
    from routers.chat import _vision_required_error

    en = _vision_required_error({"language": "en"})
    assert en.status_code == 400
    assert "Vision LLM" in en.body.decode()

    ro = _vision_required_error({"language": "ro"})
    assert ro.status_code == 400
    assert "llm vision" in ro.body.decode().lower()
