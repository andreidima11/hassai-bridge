"""Tests for browsing /share and /media as chat attachments."""

from __future__ import annotations

import pytest

from services import chat_files as cf


@pytest.fixture
def roots(tmp_path):
    share = tmp_path / "share"
    media = tmp_path / "media"
    (share / "docs").mkdir(parents=True)
    media.mkdir()
    (share / "notes.txt").write_text("hello", encoding="utf-8")
    (share / "docs" / "manual.pdf").write_bytes(b"%PDF-1.4 fake")
    (share / "secrets.yaml").write_text("nope", encoding="utf-8")
    (share / ".hidden.txt").write_text("nope", encoding="utf-8")
    (media / "photo.jpg").write_bytes(b"\xff\xd8\xff\xe0 fake jpeg")
    cf.set_roots_for_test((str(share), str(media)))
    yield {"share": share, "media": media}
    cf.set_roots_for_test(None)


def test_list_roots_when_no_path(roots):
    out = cf.list_dir("")
    assert out["path"] == ""
    assert len(out["dirs"]) == 2
    assert out["roots"] == [str(roots["share"]), str(roots["media"])]


def test_list_dir_filters_unsupported_and_hidden(roots):
    out = cf.list_dir(str(roots["share"]))
    names = [f["name"] for f in out["files"]]
    assert names == ["notes.txt"]
    assert [d["name"] for d in out["dirs"]] == ["docs"]
    assert out["parent"] == ""


def test_list_dir_kind_filter(roots):
    out = cf.list_dir(str(roots["share"]), kind="image")
    assert out["files"] == []
    out = cf.list_dir(str(roots["media"]), kind="image")
    assert [f["name"] for f in out["files"]] == ["photo.jpg"]


def test_subdirectory_reports_parent(roots):
    out = cf.list_dir(str(roots["share"] / "docs"))
    assert out["parent"] == str(roots["share"])
    assert [f["kind"] for f in out["files"]] == ["document"]


def test_paths_outside_roots_rejected(roots, tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError):
        cf.list_dir(str(outside.parent))
    with pytest.raises(ValueError):
        cf.read_file(str(outside))
    with pytest.raises(ValueError):
        cf.read_file(str(roots["share"] / ".." / "outside.txt"))


def test_read_file_returns_bytes_and_name(roots):
    raw, name = cf.read_file(str(roots["share"] / "notes.txt"))
    assert raw == b"hello"
    assert name == "notes.txt"


def test_read_file_rejects_unsupported_type(roots):
    with pytest.raises(ValueError):
        cf.read_file(str(roots["share"] / "secrets.yaml"))


def test_read_file_rejects_too_large(roots, monkeypatch):
    monkeypatch.setattr(cf, "MAX_FILE_BYTES", 2)
    with pytest.raises(ValueError):
        cf.read_file(str(roots["share"] / "notes.txt"))
