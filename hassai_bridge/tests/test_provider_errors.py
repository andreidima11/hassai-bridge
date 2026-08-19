from services.provider_errors import friendly_provider_error, looks_like_html, sanitize_error_message


def test_looks_like_html():
    assert looks_like_html("<!DOCTYPE html><html>")
    assert not looks_like_html('{"error":"bad key"}')


def test_friendly_provider_error_html():
    msg = friendly_provider_error(403, "<!DOCTYPE html><html><body>blocked</body></html>", provider={"name": "Grok"})
    assert "HTML error page" in msg
    assert "Grok" in msg
    assert "<!DOCTYPE" not in msg


def test_sanitize_error_message_strips_html():
    raw = "Provider error: 403 <!DOCTYPE html><html><body>x</body></html>"
    msg = sanitize_error_message(raw)
    assert "<!DOCTYPE" not in msg
    assert "HTML error page" in msg
