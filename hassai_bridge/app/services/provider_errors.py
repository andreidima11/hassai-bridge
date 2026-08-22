"""Sanitize upstream LLM provider errors for logs and user-facing messages."""

from __future__ import annotations

import json
import re

_HTML_HINT = re.compile(r"<!doctype|<html[\s>]", re.I)


def looks_like_html(text: str) -> bool:
    sample = str(text or "").lstrip()[:400].lower()
    return bool(_HTML_HINT.search(sample))


def _parse_json_error(body: str) -> str:
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return ""
    if isinstance(data, dict):
        err = data.get("error")
        if isinstance(err, dict):
            msg = str(err.get("message") or err.get("code") or "").strip()
            if msg:
                return msg
        for key in ("message", "detail", "error"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
    return ""


def friendly_provider_error(
    status: int | None = None,
    body: str = "",
    *,
    provider: dict | None = None,
    action: str = "request",
) -> str:
    """Turn raw upstream HTTP bodies into a short user-safe message."""
    name = str((provider or {}).get("name") or "Provider").strip() or "Provider"
    code = int(status) if status else 0
    text = str(body or "").strip()
    try:
        from core.config import ADDON_VERSION

        ver = f" [hassai {ADDON_VERSION}]"
    except Exception:
        ver = ""

    if looks_like_html(text):
        hint = "Check the server URL (should be the API base, e.g. https://api.x.ai/v1), API key, and outbound network access."
        if code:
            return f"{name} returned an HTML error page (HTTP {code}) during {action}.{ver} {hint}"
        return f"{name} returned an HTML error page during {action}.{ver} {hint}"

    parsed = _parse_json_error(text) if text.startswith("{") else ""
    if parsed:
        if code:
            return f"{name} error (HTTP {code}): {parsed[:240]}{ver}"
        return f"{name} error: {parsed[:240]}{ver}"

    snippet = " ".join(text.split())[:180]
    if code and snippet:
        return f"{name} error (HTTP {code}): {snippet}{ver}"
    if code:
        return f"{name} error (HTTP {code}) during {action}.{ver}"
    if snippet:
        return f"{name} error during {action}: {snippet}{ver}"
    return f"{name} error during {action}.{ver}"


def sanitize_error_message(message: str) -> str:
    """Strip HTML/error noise from exception strings shown in chat."""
    raw = str(message or "").strip()
    if not raw:
        return "Provider request failed."
    if looks_like_html(raw):
        return (
            "Provider returned an HTML error page instead of JSON. "
            "Check the provider URL, API key, and model name."
        )
    if raw.lower().startswith("provider error:"):
        tail = raw.split(":", 1)[1].strip()
        if looks_like_html(tail):
            return (
                "Provider returned an HTML error page instead of JSON. "
                "Check the provider URL, API key, and model name."
            )
    return raw[:500]
