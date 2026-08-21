"""Document attachment helpers."""

from __future__ import annotations

from services import chat_media as cm


def test_strip_and_parse_document_blocks():
    block = cm.format_document_block(
        att_id="abcd1234abcd1234",
        name="notes.txt",
        mime="text/plain",
        text="hello world",
    )
    full = f"Please summarize.\n\n{block}\n\nThanks"
    assert "hello world" not in cm.strip_document_blocks(full)
    assert "Please summarize." in cm.strip_document_blocks(full)
    refs = cm.parse_document_refs_from_content(full)
    assert len(refs) == 1
    assert refs[0]["id"] == "abcd1234abcd1234"
    assert refs[0]["kind"] == "document"


def test_extract_plain_text_document():
    text = cm.extract_document_text(b"line one\nline two", mime="text/plain", filename="a.txt")
    assert "line one" in text
    assert "line two" in text


def test_resolve_doc_mime():
    assert cm.resolve_doc_mime(filename="report.PDF") == "application/pdf"
    assert cm.resolve_doc_mime(content_type="application/json") == "application/json"
    assert cm.resolve_doc_mime(filename="photo.jpg") is None


def test_persist_document_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(cm, "UPLOADS_ROOT", tmp_path / "uploads")
    att = cm.persist_document_bytes(
        "tester",
        b"Hello document",
        mime="text/plain",
        name="hello.txt",
    )
    assert att["kind"] == "document"
    assert cm.resolve_attachment_path("tester", att["id"]).is_file()
    assert cm.read_extracted_text("tester", att) == "Hello document"
