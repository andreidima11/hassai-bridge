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

# Models known to reject `max_tokens` on OpenAI-compatible cloud APIs.
_NEEDS_MAX_COMPLETION = re.compile(
    r"^(gpt-5|gpt-4\.1|chatgpt-|o1|o3|o4)",
    re.IGNORECASE,
)

log = getLogger("hassai.providers")


def _norm(value) -> str:
    return str(value or "").strip().lower()


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
    if _norm(provider.get("type")) == "openai":
        return True
    base = _norm(provider.get("base_url"))
    if "api.openai.com" in base or "openai.azure.com" in base:
        return True
    # Users often rename the provider to "ChatGPT" — treat non-local URLs as OpenAI.
    name = _norm(provider.get("name"))
    if ("chatgpt" in name or name == "openai" or name.startswith("openai ")) and base and not _is_local_base(base):
        return True
    return False


def uses_max_completion_tokens(provider: dict | None, model: str = "") -> bool:
    """True when the upstream API wants max_completion_tokens instead of max_tokens."""
    if is_openai_provider(provider):
        return True
    # Misconfigured type/URL but an OpenAI model id that rejects max_tokens.
    mid = _norm(model) or (_norm(provider.get("model")) if isinstance(provider, dict) else "")
    if mid and _NEEDS_MAX_COMPLETION.match(mid):
        base = _norm(provider.get("base_url")) if isinstance(provider, dict) else ""
        # Avoid remapping for local Ollama/LM Studio named like gpt-*.
        if base and _is_local_base(base):
            return False
        ptype = _norm(provider.get("type")) if isinstance(provider, dict) else ""
        if ptype in ("local", "ollama", "lmstudio"):
            return False
        return True
    return False


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


def remap_token_limit(payload: dict, provider: dict | None) -> None:
    """Ensure OpenAI payloads never keep `max_tokens` when the API rejects it."""
    model = str(payload.get("model") or (provider or {}).get("model") or "")
    if not uses_max_completion_tokens(provider, model):
        return
    if "max_tokens" in payload:
        payload["max_completion_tokens"] = payload.pop("max_tokens")


def apply_request_payload(
    payload: dict,
    provider: dict | None,
    *,
    cache_conv_id: str | None = None,
) -> None:
    """Mutate a chat/completions JSON body for OpenAI compatibility + cache."""
    model = str(payload.get("model") or (provider or {}).get("model") or "")
    # Token remap even when provider typing is messy (ChatGPT name / custom URL).
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
