"""SSRF helper behaviour for SearXNG result filtering."""

from services.searxng import is_internal_url


def test_public_hosts_allowed():
    assert is_internal_url("https://example.com/path") is False
    assert is_internal_url("https://en.wikipedia.org/wiki/X") is False


def test_private_hosts_blocked():
    assert is_internal_url("http://127.0.0.1/") is True
    assert is_internal_url("http://localhost:8080/") is True
    assert is_internal_url("http://192.168.1.10/admin") is True


def test_dns_fail_open_for_search(monkeypatch):
    import socket

    def boom(*a, **k):
        raise OSError("dns down")

    monkeypatch.setattr(socket, "getaddrinfo", boom)
    # Search path must not wipe all results when DNS hiccups.
    assert is_internal_url("https://example.com", dns_fail_closed=False) is False
    assert is_internal_url("https://example.com", dns_fail_closed=True) is True
