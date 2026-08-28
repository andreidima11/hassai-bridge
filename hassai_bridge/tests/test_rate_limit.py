"""Rate-limit policy: GETs and sensor polls must not freeze the add-on."""

from main import _should_rate_limit


def test_gets_are_never_rate_limited():
    assert _should_rate_limit("GET", "/api/settings/info") is False
    assert _should_rate_limit("GET", "/api/settings/health") is False
    assert _should_rate_limit("GET", "/api/settings/stats") is False
    assert _should_rate_limit("GET", "/api/me") is False
    assert _should_rate_limit("GET", "/api/build") is False
    assert _should_rate_limit("GET", "/api/settings/") is False
    assert _should_rate_limit("HEAD", "/api/settings/info") is False
    assert _should_rate_limit("OPTIONS", "/v1/chat/completions") is False


def test_chat_posts_are_rate_limited():
    assert _should_rate_limit("POST", "/v1/chat/completions") is True
    assert _should_rate_limit("PUT", "/api/settings/") is True
    assert _should_rate_limit("DELETE", "/api/conversations/abc") is True


def test_activity_and_backup_posts_exempt():
    assert _should_rate_limit("POST", "/v1/chat/activity/trace-1") is False
    assert _should_rate_limit("POST", "/api/settings/import/chunk") is False
    assert _should_rate_limit("POST", "/api/settings/export") is False
