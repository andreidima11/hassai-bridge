"""OpenAI Chat Completions request quirks.

Newer ChatGPT / GPT / o-series models reject `max_tokens` and some also reject
a custom `temperature`. Keep the settings UI field as max_tokens; map it here.
"""

from __future__ import annotations

import re

# Models that reject custom temperature / sampling knobs.
_RESTRICTED_SAMPLING = re.compile(
    r"^(o[1-9]([.-]|$)|gpt-5)",
    re.IGNORECASE,
)


def is_openai_provider(provider: dict | None) -> bool:
    if not isinstance(provider, dict):
        return False
    if str(provider.get("type") or "").lower() == "openai":
        return True
    base = str(provider.get("base_url") or "").lower()
    return "api.openai.com" in base


def uses_max_completion_tokens(provider: dict | None, model: str = "") -> bool:
    """OpenAI official API wants max_completion_tokens for current chat models."""
    if not is_openai_provider(provider):
        return False
    # Always remap for api.openai.com — older models accept the new name too.
    return True


def is_restricted_sampling_model(model: str | None) -> bool:
    """o-series / GPT-5 style models that reject custom temperature etc."""
    name = str(model or "").strip()
    if not name:
        return False
    if _RESTRICTED_SAMPLING.match(name):
        return True
    lower = name.lower()
    return any(token in lower for token in ("o1-", "o3-", "o4-", "gpt-5"))


def apply_request_payload(payload: dict, provider: dict | None) -> None:
    """Mutate a chat/completions JSON body for OpenAI compatibility."""
    if not is_openai_provider(provider):
        return
    model = str(payload.get("model") or provider.get("model") or "")
    if uses_max_completion_tokens(provider, model) and "max_tokens" in payload:
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    if is_restricted_sampling_model(model):
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "logit_bias"):
            payload.pop(key, None)
