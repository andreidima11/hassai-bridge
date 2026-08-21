"""Tests for the /media and /share agent tools."""

from __future__ import annotations

import pytest

from services import chat_files as cf
from services import media_tools as mt


@pytest.fixture
def roots(tmp_path):
    media = tmp_path / "media"
    share = tmp_path / "share"
    (media / "poze").mkdir(parents=True)
    share.mkdir()
    (media / "poze" / "vacanta.jpg").write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")
    (media / "clip.mp4").write_bytes(b"\x00\x00\x00\x18ftypmp42")
    (media / "lista.txt").write_text("lapte\npaine", encoding="utf-8")
    (media / ".hidden.txt").write_text("nope", encoding="utf-8")
    (share / "note.md").write_text("# titlu", encoding="utf-8")
    cf.set_roots_for_test((str(media), str(share)))
    yield {"media": media, "share": share}
    cf.set_roots_for_test(None)


def test_list_without_path_shows_roots(roots):
    out = mt.list_media()
    assert str(roots["media"]) in out
    assert str(roots["share"]) in out


def test_list_folder_shows_files_and_kinds(roots):
    out = mt.list_media(str(roots["media"]))
    assert "clip.mp4\tvideo" in out
    assert "lista.txt\tdocument" in out
    assert "poze\tfolder" in out
    assert ".hidden.txt" not in out


def test_list_accepts_path_relative_to_a_root(roots):
    assert "vacanta.jpg" in mt.list_media("poze")


def test_search_walks_subfolders(roots):
    out = mt.list_media(str(roots["media"]), search="vacanta")
    assert "vacanta.jpg" in out
    assert "lista.txt" not in out


def test_read_document_returns_text(roots):
    info = mt.read_media(str(roots["media"] / "lista.txt"))
    assert info["kind"] == "document"
    assert "lapte" in info["text"]


def test_read_image_returns_bytes(roots):
    info = mt.read_media("poze/vacanta.jpg")
    assert info["kind"] == "image"
    assert info["bytes"].startswith(b"\xff\xd8")


def test_read_video_returns_metadata_only(roots):
    info = mt.read_media(str(roots["media"] / "clip.mp4"))
    assert info["kind"] == "video"
    assert "bytes" not in info and "text" not in info


def test_read_rejects_paths_outside_roots(roots, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        mt.read_media(str(outside))
    with pytest.raises(ValueError):
        mt.read_media("../secret.txt")


def test_delete_needs_confirmation(roots):
    target = roots["media"] / "lista.txt"
    assert "confirm=true" in mt.delete_media(str(target))
    assert target.is_file()


def test_delete_removes_the_file(roots):
    target = roots["media"] / "lista.txt"
    out = mt.delete_media(str(target), confirm=True)
    assert out.startswith("OK:")
    assert not target.exists()


def test_delete_refuses_folders_and_outside_paths(roots, tmp_path):
    assert "folder" in mt.delete_media(str(roots["media"] / "poze"), confirm=True)
    outside = tmp_path / "secret.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        mt.delete_media(str(outside), confirm=True)
    assert outside.is_file()


def test_missing_roots_report_cleanly(monkeypatch):
    cf.set_roots_for_test(())
    try:
        assert "not mounted" in mt.list_media()
    finally:
        cf.set_roots_for_test(None)
