"""A camera snapshot must not come back with a bogus generated image or a marker."""

from __future__ import annotations

from routers.chat import _markdown_for_generated_attachments
from services import chat_content as cc


SNAP = {"id": "aaa111", "mime": "image/jpeg", "kind": "image",
        "name": "frigate-curte_dreapta-1787548956.jpg"}
MEDIA = {"id": "bbb222", "mime": "image/png", "kind": "image", "name": "poza.png"}
IMAGINE = {"id": "ccc333", "mime": "image/png", "kind": "image",
           "name": "generated-1", "source": "generated"}


def test_frigate_snapshot_gets_no_generated_image_markdown():
    # The chat already draws snapshots from the message attachments; markdown
    # here produced a second, broken copy labelled "Generated image".
    assert _markdown_for_generated_attachments([SNAP], "sess") == ""


def test_media_file_gets_no_generated_image_markdown():
    assert _markdown_for_generated_attachments([MEDIA], "sess") == ""


def test_imagine_output_still_renders_markdown():
    md = _markdown_for_generated_attachments([IMAGINE], "sess")
    assert md.startswith("![Generated image](")
    assert "ccc333" in md


def test_mixed_list_only_renders_the_generated_one():
    md = _markdown_for_generated_attachments([SNAP, IMAGINE, MEDIA], "sess")
    assert md.count("![Generated image]") == 1
    assert "ccc333" in md
    assert "aaa111" not in md


def test_already_referenced_image_is_not_repeated():
    assert _markdown_for_generated_attachments([IMAGINE], "sess", "see ccc333") == ""


# ── The "[Photos shown in chat: …]" marker ─────────

def test_strip_photo_note_with_closing_bracket():
    text = "Uite cine a trecut.\n\n[Photos shown in chat: frigate-curte.jpg]"
    assert cc.strip_photo_notes(text) == "Uite cine a trecut."


def test_strip_photo_note_left_unterminated():
    # Exactly what a model echoed in the wild — no closing bracket.
    text = "Uite snapul.\n[Photos shown in chat: frigate-curte_dreapta-1787548956.890503-zay2t1.jpg."
    assert cc.strip_photo_notes(text) == "Uite snapul."


def test_strip_photo_note_mid_stream_tail():
    assert cc.strip_photo_notes("Gata. [Photos shown in chat: frig") == "Gata."


def test_strip_photo_note_leaves_normal_text_alone():
    text = "Am gasit doua poze in curte si le arat mai jos."
    assert cc.strip_photo_notes(text) == text


def test_strip_photo_note_is_case_insensitive():
    assert cc.strip_photo_notes("Hi\n\n[photos shown in chat: a.jpg]") == "Hi"


def test_strip_photo_note_handles_empty_and_none():
    assert cc.strip_photo_notes("") == ""
    assert cc.strip_photo_notes(None) is None


def test_replay_marker_is_still_produced_for_history():
    # The marker itself must stay: it tells the model the photo was displayed.
    content = cc.build_multimodal_content(
        "Two people at the gate", [SNAP], user_id="tester", include_images=False,
    )
    assert "Photos shown in chat" in content
