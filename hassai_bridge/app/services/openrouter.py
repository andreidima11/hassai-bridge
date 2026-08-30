"""OpenRouter OpenAI-compatible gateway helpers.

Docs: https://openrouter.ai/docs — Chat Completions at
https://openrouter.ai/api/v1 with Bearer auth. Attribution headers
(HTTP-Referer, X-Title) are recommended for app rankings.
The completion `model` field is the routed id (may differ from request
when using auto / :nitro / fallbacks).
"""

from __future__ import annotations

_DEFAULT_REFERER = "https://github.com/andreidima11/hassai-bridge"
_DEFAULT_TITLE = "HASSAI Bridge"


def is_openrouter_provider(provider: dict | None) -> bool:
    if not isinstance(provider, dict):
        return False
    if str(provider.get("type") or "").strip().lower() == "openrouter":
        return True
    base = str(provider.get("base_url") or "").strip().lower()
    return "openrouter.ai" in base


def attribution_headers() -> dict[str, str]:
    """Headers OpenRouter uses for app identification / rankings."""
    return {
        "HTTP-Referer": _DEFAULT_REFERER,
        "X-Title": _DEFAULT_TITLE,
    }


def resolve_reply_model(
    *,
    response: dict | None = None,
    stream_model: str | None = None,
    usage: dict | None = None,
    configured: str | None = None,
) -> str:
    """Prefer the model id the gateway actually served over the configured one."""
    candidates = []
    if isinstance(response, dict):
        candidates.append(response.get("model"))
    candidates.append(stream_model)
    if isinstance(usage, dict):
        candidates.append(usage.get("model"))
    candidates.append(configured)
    for raw in candidates:
        mid = str(raw or "").strip()
        if mid and mid.lower() != "default":
            return mid
    return ""
