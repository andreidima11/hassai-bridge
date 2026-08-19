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
