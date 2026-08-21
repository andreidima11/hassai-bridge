"""Tests for short-lived phone-browser upload links."""

from __future__ import annotations

import pytest

from services import upload_links as ul


@pytest.fixture(autouse=True)
def clean_links():
    ul.reset_for_test()
    yield
    ul.reset_for_test()


def test_create_returns_token_bound_to_user():
    link = ul.create("andrei")
    assert len(link["token"]) == 32
    assert ul.owner(link["token"]) == "andrei"


def test_unknown_token_has_no_owner():
    assert ul.owner("nope") is None
    assert ul.owner("") is None


def test_expired_token_is_dropped(monkeypatch):
    monkeypatch.setattr(ul, "TTL_SECONDS", -1.0)
    link = ul.create("andrei")
    assert ul.owner(link["token"]) is None
    assert ul.take_files(link["token"], "andrei") == {"expired": True, "files": []}


def test_files_are_returned_once():
    link = ul.create("andrei")
    ul.add_file(link["token"], {"id": "a", "name": "doc.pdf"})
    first = ul.take_files(link["token"], "andrei")
    assert [f["name"] for f in first["files"]] == ["doc.pdf"]
    assert ul.take_files(link["token"], "andrei")["files"] == []


def test_files_only_go_to_the_owner():
    link = ul.create("andrei")
    ul.add_file(link["token"], {"id": "a", "name": "doc.pdf"})
    other = ul.take_files(link["token"], "altcineva")
    assert other == {"expired": True, "files": []}
    assert len(ul.take_files(link["token"], "andrei")["files"]) == 1


def test_add_file_rejects_unknown_token():
    with pytest.raises(ValueError):
        ul.add_file("nope", {"id": "a"})


def test_add_file_caps_per_link():
    link = ul.create("andrei")
    for i in range(ul.MAX_FILES_PER_LINK):
        ul.add_file(link["token"], {"id": str(i)})
    with pytest.raises(ValueError):
        ul.add_file(link["token"], {"id": "overflow"})
