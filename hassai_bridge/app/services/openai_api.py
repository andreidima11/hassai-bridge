"""OpenAI Chat Completions request quirks and prompt-cache helpers.

Newer ChatGPT / GPT / o-series models reject `max_tokens` and some also reject
a custom `temperature`. Keep the settings UI field as max_tokens; map it here.

Prompt caching: set a stable `prompt_cache_key` (session id) so OpenAI routes
related turns to the same cache; report hits from `prompt_tokens_details`.
"""

from __future__ import annotations

import re
from logging import getLogger

# Models that reject custom temperature / sampling knobs.
_RESTRICTED_SAMPLING = re.compile(
    r"^(o[1-9]([.-]|$)|gpt-5)",
    re.IGNORECASE,
)

# OpenAI / ChatGPT model ids that reject `max_tokens` on the official API.
_OPENAI_CHAT_MODEL = re.compile(
    r"^(gpt-|chatgpt-|o[1-9]([.-]|$)|o[1-9]-)",
    re.IGNORECASE,
)
# Gateway prefixes (OpenRouter, LiteLLM, etc.): openai/gpt-5.6, …/gpt-4o
_OPENAI_CHAT_MODEL_SUFFIX = re.compile(
    r"(^|/)(gpt-|chatgpt-|o[1-9]([.-]|$)|o[1-9]-)",
    re.IGNORECASE,
)

log = getLogger("hassai.providers")


def _norm(value) -> str:
    return str(value or "").strip().lower()


def _provider_type(provider: dict | None) -> str:
    if not isinstance(provider, dict):
        return ""
    return _norm(provider.get("type"))


def _is_openai_cloud_url(url: str) -> bool:
    u = _norm(url)
    return bool(u and ("openai.com" in u or "openai.azure.com" in u))


def _is_local_provider(provider: dict | None) -> bool:
    if not isinstance(provider, dict):
        return False
    base = _norm(provider.get("base_url"))
    # Mis-typed "local" with an OpenAI cloud URL should still remap tokens.
    if base and _is_openai_cloud_url(base):
        return False
    ptype = _provider_type(provider)
    if ptype in ("local", "ollama", "lmstudio"):
        return True
    return bool(base and _is_local_base(base))


def _is_local_base(base: str) -> bool:
    b = _norm(base)
    return any(
        token in b
        for token in (
            "localhost",
            "127.0.0.1",
            "0.0.0.0",
            "host.docker.internal",
            "homeassistant.local",
        )
    )


def is_openai_provider(provider: dict | None) -> bool:
    if not isinstance(provider, dict):
        return False
    if _provider_type(provider) == "openai":
        return True
    if _is_local_provider(provider):
        return False
    base = _norm(provider.get("base_url"))
    if _is_openai_cloud_url(base):
        return True
    # Renamed providers ("ChatGPT") — do not require base_url to be set.
    name = _norm(provider.get("name"))
    if "chatgpt" in name or name == "openai" or name.startswith("openai "):
        return True
    return False


def looks_like_openai_model(model: str | None) -> bool:
    mid = _norm(model)
    if not mid or mid == "default":
        return False
    if _OPENAI_CHAT_MODEL.match(mid):
        return True
    return bool(_OPENAI_CHAT_MODEL_SUFFIX.search(mid))


def uses_max_completion_tokens(
    provider: dict | None,
    model: str = "",
    *,
    request_url: str = "",
) -> bool:
    """True when the upstream API wants max_completion_tokens instead of max_tokens."""
    if _is_openai_cloud_url(request_url):
        return True
    if is_openai_provider(provider):
        return True
    if _is_local_provider(provider):
        return False
    mid = _norm(model) or (_norm(provider.get("model")) if isinstance(provider, dict) else "")
    return looks_like_openai_model(mid)


def is_restricted_sampling_model(model: str | None) -> bool:
    """o-series / GPT-5 style models that reject custom temperature etc."""
    name = str(model or "").strip()
    if not name:
        return False
    if _RESTRICTED_SAMPLING.match(name):
        return True
    lower = name.lower()
    return any(token in lower for token in ("o1-", "o3-", "o4-", "gpt-5"))


def prompt_cache_key(session_id: str | None) -> str | None:
    """Stable routing key for OpenAI prompt cache (session / conversation id)."""
    key = str(session_id or "").strip()
    if not key:
        return None
    return key[:128]


def _strip_max_tokens(payload: dict) -> None:
    """Remove max_tokens; preserve an existing max_completion_tokens if set."""
    if "max_tokens" not in payload:
        return
    if "max_completion_tokens" not in payload:
        payload["max_completion_tokens"] = payload.pop("max_tokens")
    else:
        payload.pop("max_tokens", None)


def remap_token_limit(
    payload: dict,
    provider: dict | None,
    *,
    request_url: str = "",
) -> None:
    """Ensure OpenAI payloads never keep `max_tokens` when the API rejects it."""
    model = str(payload.get("model") or (provider or {}).get("model") or "")
    if not uses_max_completion_tokens(provider, model, request_url=request_url):
        return
    _strip_max_tokens(payload)


def outbound_targets_openai_cloud(
    provider: dict | None,
    request_url: str = "",
) -> bool:
    """True when the HTTP request is headed to OpenAI / Azure OpenAI."""
    if _is_openai_cloud_url(request_url):
        return True
    if isinstance(provider, dict) and _is_openai_cloud_url(provider.get("base_url", "")):
        return True
    return is_openai_provider(provider)


def finalize_http_payload(
    payload: dict,
    provider: dict | None,
    *,
    request_url: str = "",
) -> None:
    """Absolute last mutation before httpx POST — OpenAI must never see max_tokens."""
    model = str(payload.get("model") or (provider or {}).get("model") or "")
    url = str(request_url or "")
    if not (
        outbound_targets_openai_cloud(provider, url)
        or uses_max_completion_tokens(provider, model, request_url=url)
    ):
        return
    if "max_tokens" in payload:
        log.warning(
            "Stripped max_tokens from outbound payload (provider=%s model=%s url=%s)",
            (provider or {}).get("name"),
            model,
            url[:80],
        )
    _strip_max_tokens(payload)
    payload.pop("max_tokens", None)


def sanitize_outbound_chat_payload(
    payload: dict,
    provider: dict | None,
    *,
    request_url: str = "",
) -> None:
    """Last gate before HTTP — never send max_tokens to OpenAI chat models."""
    remap_token_limit(payload, provider, request_url=request_url)
    finalize_http_payload(payload, provider, request_url=request_url)


def apply_request_payload(
    payload: dict,
    provider: dict | None,
    *,
    cache_conv_id: str | None = None,
) -> None:
    """Mutate a chat/completions JSON body for OpenAI compatibility + cache."""
    model = str(payload.get("model") or (provider or {}).get("model") or "")
    remap_token_limit(payload, provider)
    openaiish = is_openai_provider(provider) or uses_max_completion_tokens(provider, model)
    if not openaiish:
        return
    if is_restricted_sampling_model(model):
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty", "logit_bias"):
            payload.pop(key, None)
    if not is_openai_provider(provider):
        return
    cache_key = prompt_cache_key(cache_conv_id)
    if cache_key:
        payload["prompt_cache_key"] = cache_key
    # Streaming responses omit usage unless include_usage is set — needed for
    # cache hit reporting when we parse the final usage chunk.
    if payload.get("stream"):
        opts = payload.get("stream_options")
        if not isinstance(opts, dict):
            opts = {}
        else:
            opts = dict(opts)
        opts["include_usage"] = True
        payload["stream_options"] = opts
    sanitize_outbound_chat_payload(payload, provider)


def cache_tokens_from_usage(usage: dict | None) -> tuple[int, int]:
    """Return (cache_hit, cache_miss) from Chat Completions usage."""
    if not isinstance(usage, dict):
        return 0, 0
    prompt = int(usage.get("prompt_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    if not isinstance(details, dict):
        details = {}
    hit = int(details.get("cached_tokens") or 0)
    miss = max(0, prompt - hit) if prompt else 0
    return hit, miss


def log_cache_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not is_openai_provider(provider) or not isinstance(usage, dict):
        return
    hit, miss = cache_tokens_from_usage(usage)
    details = usage.get("prompt_tokens_details") or {}
    write = 0
    if isinstance(details, dict):
        write = int(details.get("cache_write_tokens") or 0)
    if hit or miss or write:
        log_prefix = f"[{user_id}] " if user_id else ""
        if write:
            log.info(
                "%sOpenAI prompt cache: hit=%s miss=%s write=%s",
                log_prefix,
                hit,
                miss,
                write,
            )
        else:
            log.info(
                "%sOpenAI prompt cache: hit=%s miss=%s",
                log_prefix,
                hit,
                miss,
            )
