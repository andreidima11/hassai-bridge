"""
Multi-provider LLM service.

Supports: Local (LM Studio, Ollama, etc.), OpenAI, Grok (xAI), DeepSeek, GLM (Zhipu),
Gemini (Google), Qwen (DashScope).
All providers use the OpenAI-compatible /v1/chat/completions format.
"""

import re
import json
import httpx
import asyncio
import logging
from config import load_config

log = logging.getLogger("hassai.providers")

# Retry config (#20)
_RETRY_COUNT = 2
_RETRY_BACKOFF = [1.0, 3.0]
_RETRYABLE_STATUS = {429, 500, 502, 503}

# ── Persistent connection pool ──
_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    """Return a shared httpx client. Timeout is set per-request, not per-client."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=300,  # generous default; callers override per-request
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


# ── Provider presets (base_url defaults — base URLs only, no endpoint paths #17) ──
PROVIDER_PRESETS = {
    "local": {
        "name": "Local (LM Studio / Ollama)",
        "base_url": "http://localhost:1234",
        "requires_key": False,
    },
    "openai": {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "requires_key": True,
    },
    "grok": {
        "name": "Grok (xAI)",
        "base_url": "https://api.x.ai/v1",
        "requires_key": True,
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "requires_key": True,
    },
    "glm": {
        "name": "GLM (Zhipu AI)",
        "base_url": "https://api.z.ai/api/paas/v4",
        "requires_key": True,
    },
    "gemini": {
        "name": "Gemini (Google)",
        # OpenAI-compatible Chat Completions surface (ai.google.dev/gemini-api/docs/openai)
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "requires_key": True,
    },
    "qwen": {
        "name": "Qwen (DashScope)",
        # International OpenAI-compatible endpoint; China keys use dashscope.aliyuncs.com
        "base_url": "https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        "requires_key": True,
    },
}


_VISION_MODEL_HINTS = re.compile(
    r"gpt-4o|gpt-4-turbo|gpt-4-vision|gpt-4\.1|claude-3|claude-sonnet|claude-opus|gemini|llava|vision|"
    r"qwen.*vl|pixtral|glm-4v|internvl|moondream|minicpm-v",
    re.I,
)


def provider_supports_vision(provider: dict | None) -> bool:
    if not isinstance(provider, dict):
        return False
    flag = provider.get("supports_vision")
    if flag is True:
        return True
    if flag is False:
        return False
    if provider.get("type") == "grok":
        # xAI Grok chat models (incl. grok-4 / grok-4.6) accept text + image input.
        model = str(provider.get("model") or "").strip()
        return bool(model)
    if provider.get("type") == "gemini":
        # Gemini chat models on the OpenAI-compat endpoint accept images.
        model = str(provider.get("model") or "").strip()
        return bool(model)
    model = str(provider.get("model") or "").strip()
    return bool(model and _VISION_MODEL_HINTS.search(model))


def _coerce_provider_record(provider: dict) -> dict:
    """Fix common misconfigurations before outbound API calls."""
    if not isinstance(provider, dict):
        return provider
    from services import openai_api as oai

    p = dict(provider)
    base = str(p.get("base_url") or "").strip()
    ptype = oai._provider_type(p)
    if oai._is_openai_cloud_url(base) and ptype in ("local", "ollama", "lmstudio"):
        p["type"] = "openai"
    if oai.is_openai_provider(p) and not base:
        p["base_url"] = "https://api.openai.com/v1"
    return p


def get_active_provider() -> dict:
    """Get the currently active provider config."""
    cfg = load_config()
    providers = cfg.get("providers", [])
    active_id = cfg.get("active_provider", "")

    # Find active provider
    for p in providers:
        if p.get("id") == active_id:
            return _coerce_provider_record(p)

    # Fallback: migrate from old lmstudio config
    if not providers:
        lm = cfg.get("lmstudio", {})
        return {
            "id": "local_default",
            "name": "LM Studio",
            "type": "local",
            "base_url": lm.get("base_url", "http://localhost:1234"),
            "api_key": "",
            "model": lm.get("model", "default"),
            "timeout": lm.get("timeout", 120),
            "max_tokens": lm.get("max_tokens", 2048),
            "temperature": lm.get("temperature", 0.7),
        }

    # Return first provider if active_id not found
    return _coerce_provider_record(providers[0]) if providers else {}


def get_provider_by_id(provider_id: str) -> dict | None:
    """Get a specific provider by ID."""
    cfg = load_config()
    for p in cfg.get("providers", []):
        if p.get("id") == provider_id:
            return _coerce_provider_record(p)
    return None


def get_secondary_provider(primary: dict | None = None) -> dict | None:
    """Get the secondary provider for the given (or active) primary provider.

    Looks up the secondary_provider ID in the secondary_providers list.
    Returns None if no secondary is configured or the referenced provider
    doesn't exist.
    """
    if primary is None:
        primary = get_active_provider()
    sec_id = primary.get("secondary_provider", "")
    if not sec_id:
        return None
    return get_secondary_provider_by_id(sec_id)


def get_vision_provider(primary: dict | None = None) -> dict | None:
    """Get the dedicated vision provider for the given (or active) primary."""
    if primary is None:
        primary = get_active_provider()
    vision_id = primary.get("vision_provider", "")
    if not vision_id:
        return None
    return get_secondary_provider_by_id(vision_id)


def get_image_generation_provider(primary: dict | None = None) -> dict | None:
    """Get the dedicated image-generation provider for the given (or active) primary."""
    if primary is None:
        primary = get_active_provider()
    gen_id = primary.get("image_generation_provider", "")
    if not gen_id:
        return None
    return get_secondary_provider_by_id(gen_id)


def find_global_image_generation_secondary() -> dict | None:
    """First configured secondary provider that supports image generation."""
    from services import provider_capabilities as pc

    cfg = load_config()
    for provider in cfg.get("secondary_providers", []):
        if pc.supports_image_generation(provider):
            return provider
    return None


def resolve_image_generation_provider(primary: dict | None = None) -> dict | None:
    """Pick provider for the generate_image tool.

    Priority: active Grok (or other capable primary), dedicated Image Gen LLM,
    then any global Grok secondary configured for generation.
    """
    from services import provider_capabilities as pc

    if primary is None:
        primary = get_active_provider()
    if pc.supports_image_generation(primary):
        return primary
    dedicated = get_image_generation_provider(primary)
    if dedicated and pc.supports_image_generation(dedicated):
        return dedicated
    return find_global_image_generation_secondary()


def find_global_vision_secondary() -> dict | None:
    """First configured secondary provider that supports chat vision."""
    cfg = load_config()
    for provider in cfg.get("secondary_providers", []):
        if provider_supports_vision(provider):
            return provider
    return None


def resolve_image_provider(primary: dict | None = None, secondary: dict | None = None) -> dict | None:
    """Pick provider for image requests when the primary model lacks vision.

    Priority: dedicated vision provider, vision-capable secondary, then any
    global vision secondary (e.g. Grok vision configured for another primary).
    """
    if primary is None:
        primary = get_active_provider()
    vision = get_vision_provider(primary)
    if vision:
        return vision
    if secondary is None:
        secondary = get_secondary_provider(primary)
    if secondary and provider_supports_vision(secondary):
        return secondary
    return find_global_vision_secondary()


def get_secondary_provider_by_id(provider_id: str) -> dict | None:
    """Get a specific secondary provider by ID."""
    cfg = load_config()
    for p in cfg.get("secondary_providers", []):
        if p.get("id") == provider_id:
            return _coerce_provider_record(p)
    return None


def _build_headers(provider: dict, *, extra: dict | None = None) -> dict:
    """Build request headers including auth if needed."""
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    api_key = provider.get("api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if extra:
        headers.update(extra)
    return headers


def normalize_provider_base_url(raw: str) -> str:
    """Normalize a user-entered provider base URL (strip endpoint paths)."""
    return _normalize_base_url(str(raw or "").strip())


def _normalize_base_url(raw: str) -> str:
    """Strip endpoint paths from base_url to get the API base.

    Users may paste the full endpoint (e.g. https://api.x.ai/v1/chat/completions).
    Strip known suffixes so we get the versioned base (e.g. https://api.x.ai/v1).
    """
    url = raw.rstrip("/")
    url = re.sub(r"/(chat/completions|completions|responses|models|embeddings|images/generations|images/edits)$", "", url)
    return url


def _base_includes_api_root(base: str) -> bool:
    """True when base_url already includes the API version / compat root.

    Matches /v1, /v4, /v1beta, …/openai, …/compatible-mode — so we do not
    incorrectly append another /v1 (Gemini OpenAI-compat is …/v1beta/openai).
    """
    if re.search(r"/v\d+[a-z]*(/|$)", base, re.I):
        return True
    if re.search(r"/(openai|compatible-mode)(/|$)", base, re.I):
        return True
    return False


def _build_url(provider: dict, path: str) -> str:
    """Build the full API URL for a provider.

    Handles various base_url formats:
      - Plain origin:  https://api.openai.com        → /v1/chat/completions
      - With version:  https://api.x.ai/v1           → /chat/completions
      - Full endpoint: https://api.deepseek.com/chat/ → stripped, then rebuilt
      - Custom base:   https://api.z.ai/api/paas/v4  → /chat/completions
      - Gemini compat: …/v1beta/openai               → /chat/completions
      - Qwen compat:   …/compatible-mode/v1          → /chat/completions
    """
    base = _normalize_base_url(provider.get("base_url", ""))
    # Strip /v1 prefix from the requested path — we decide whether to add it
    clean_path = re.sub(r"^/v1", "", path)  # e.g. "/chat/completions", "/models"

    if _base_includes_api_root(base):
        return base + clean_path
    return base + "/v1" + clean_path


def _provider_request_headers(provider: dict, cache_conv_id: str | None = None) -> dict:
    extra = None
    if provider.get("type") == "grok":
        from services import grok as gk

        extra = gk.grok_conv_header(cache_conv_id)
    return _build_headers(provider, extra=extra)


def _skip_temperature(provider: dict, thinking: dict | None, *, model: str = "") -> bool:
    if provider.get("type") == "grok" and thinking:
        return True
    if bool(thinking and thinking.get("enabled") and provider.get("type") == "deepseek"):
        return True
    from services import openai_api as oai

    if oai.is_openai_provider(provider) and oai.is_restricted_sampling_model(model or provider.get("model")):
        return True
    return False


def _apply_token_limit(payload: dict, provider: dict, *, request_url: str = "") -> None:
    max_tokens = provider.get("max_tokens")
    if not max_tokens:
        return
    from services import openai_api as oai

    model = str(payload.get("model") or provider.get("model") or "")
    # OpenAI docs: GPT-5 / o-series / current ChatGPT models reject max_tokens.
    # Prefer max_completion_tokens whenever the upstream is OpenAI-ish.
    if oai.uses_max_completion_tokens(provider, model, request_url=request_url):
        payload["max_completion_tokens"] = int(max_tokens)
        payload.pop("max_tokens", None)
    else:
        payload["max_tokens"] = max_tokens


def _finalize_chat_payload(
    payload: dict,
    provider: dict,
    *,
    cache_conv_id: str | None = None,
    request_url: str = "",
) -> None:
    """Provider-specific last-mile tweaks (OpenAI tokens, prompt cache, etc.)."""
    from services import openai_api as oai

    # Belt-and-suspenders: strip max_tokens even if an earlier step re-added it.
    oai.apply_request_payload(payload, provider, cache_conv_id=cache_conv_id)
    oai.sanitize_outbound_chat_payload(payload, provider, request_url=request_url)


def _assert_usable_chat_model(provider: dict, used_model: str) -> None:
    if provider.get("type") != "grok":
        return
    from services import grok as gk

    if gk.is_imagine_model(used_model):
        raise ValueError(
            f"'{used_model}' is an Imagine image model, not a chat model. "
            "Set the provider Model to grok-4.6 (or another chat model). "
            "Image generation uses Imagine automatically via the generate_image tool."
        )


def resolve_provider_chat_model(provider: dict, model: str | None = None) -> str:
    cfg_model = provider.get("model", "default")
    used_model = cfg_model if cfg_model and cfg_model != "default" else (model or "default")
    _assert_usable_chat_model(provider, used_model)
    return used_model


def _deepseek_reasoning_fallback(payload: dict, provider: dict, status: int, body: str) -> bool:
    """Repair a payload rejected by DeepSeek's reasoning_content rule.

    Retries without thinking and without reasoning_content, which DeepSeek
    always accepts — used when a stored conversation predates CoT persistence.
    """
    from services import deepseek as ds

    if provider.get("type") != "deepseek":
        return False
    if not ds.is_reasoning_passback_error(status, body):
        return False
    payload["messages"] = ds.strip_reasoning(payload.get("messages") or [])
    payload["thinking"] = {"type": "disabled"}
    payload.pop("reasoning_effort", None)
    log.warning("DeepSeek rejected reasoning_content pass-back; retrying without thinking")
    return True


def _gemini_invalid_argument_fallback(payload: dict, provider: dict, status: int, body: str) -> bool:
    from services import gemini as gm

    if provider.get("type") != "gemini":
        return False
    if not gm.is_gemini_retryable_400(status, body, payload):
        return False
    gm.repair_payload_after_gemini_400(payload)
    log.warning("Gemini rejected chat payload (400); retrying with repaired tools/thinking")
    return True


def _provider_400_fallback(payload: dict, provider: dict, status: int, body: str) -> bool:
    if _deepseek_reasoning_fallback(payload, provider, status, body):
        return True
    return _gemini_invalid_argument_fallback(payload, provider, status, body)


async def chat_completion(messages: list[dict], model: str | None = None, stream: bool = False,
                          tools: list | None = None, tool_choice: str | dict | None = None,
                          provider: dict | None = None, thinking: dict | None = None,
                          cache_conv_id: str | None = None) -> dict:
    """Send a chat completion request to the active (or specified) provider."""
    if provider is None:
        provider = get_active_provider()

    url = _build_url(provider, "/v1/chat/completions")
    headers = _provider_request_headers(provider, cache_conv_id)
    timeout = provider.get("timeout", 120)

    used_model = resolve_provider_chat_model(provider, model)

    from services import chat_content as cc
    from services import provider_capabilities as pc

    shaped = pc.prepare_messages_for_request(
        provider, messages, tools=tools, thinking=thinking,
    )

    payload = {
        "model": used_model,
        "messages": shaped,
        "stream": stream,
    }
    if tools:
        payload["tools"] = pc.shape_tools_for_provider(provider, tools)
    if tool_choice is not None:
        payload["tool_choice"] = pc.sanitize_tool_choice(provider, tool_choice)
    _apply_token_limit(payload, provider, request_url=url)
    temperature = provider.get("temperature")
    if temperature is not None and not _skip_temperature(provider, thinking, model=used_model):
        payload["temperature"] = pc.clamp_temperature(provider, temperature)

    if thinking and pc.supports_thinking(provider):
        pc.apply_provider_payload_extras(
            payload,
            provider,
            thinking,
            has_images=cc.messages_have_images(shaped),
        )

    _finalize_chat_payload(payload, provider, cache_conv_id=cache_conv_id, request_url=url)

    from services import openai_api as oai

    oai.sanitize_outbound_chat_payload(payload, provider, request_url=url)
    oai.finalize_http_payload(payload, provider, request_url=url)
    if oai.is_openai_provider(provider) or "openai.com" in url.lower():
        log.info(
            "OpenAI chat POST model=%s keys=%s",
            payload.get("model"),
            sorted(k for k in payload if k != "messages"),
        )

    client = _get_client()
    # Retry on transient errors (#20)
    last_exc = None
    reasoning_retry_used = False
    for attempt in range(_RETRY_COUNT + 1):
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _RETRY_COUNT:
                log.warning(f"Provider [{provider.get('name', '?')}] returned {resp.status_code}, retrying ({attempt + 1}/{_RETRY_COUNT})")
                await asyncio.sleep(_RETRY_BACKOFF[attempt])
                continue
            if resp.status_code >= 400:
                body = resp.text[:800]
                if not reasoning_retry_used and _provider_400_fallback(
                    payload, provider, resp.status_code, body,
                ):
                    reasoning_retry_used = True
                    resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
                    if resp.status_code < 400:
                        return resp.json()
                    body = resp.text[:800]
                from services.provider_errors import friendly_provider_error

                log.error(
                    "Provider [%s] returned %s: %s",
                    provider.get("name", "?"),
                    resp.status_code,
                    body[:500],
                )
                msg = friendly_provider_error(resp.status_code, body, provider=provider, action="chat")
                raise httpx.HTTPStatusError(msg, request=resp.request, response=resp)
            return resp.json()
        except httpx.TimeoutException as e:
            last_exc = e
            if attempt < _RETRY_COUNT:
                log.warning(f"Provider timeout, retrying ({attempt + 1}/{_RETRY_COUNT})")
                await asyncio.sleep(_RETRY_BACKOFF[attempt])
            else:
                raise
    raise last_exc  # Should not reach here


async def chat_completion_stream(messages: list[dict], model: str | None = None,
                                 tools: list | None = None, tool_choice: str | dict | None = None,
                                 provider: dict | None = None, thinking: dict | None = None,
                                 cache_conv_id: str | None = None):
    """Stream chat completion, yielding SSE chunks."""
    if provider is None:
        provider = get_active_provider()

    url = _build_url(provider, "/v1/chat/completions")
    headers = _provider_request_headers(provider, cache_conv_id)
    timeout = provider.get("timeout", 120)

    cfg_model = provider.get("model", "default")
    used_model = cfg_model if cfg_model and cfg_model != "default" else (model or "default")
    used_model = resolve_provider_chat_model(provider, model)

    from services import chat_content as cc
    from services import provider_capabilities as pc

    shaped = pc.prepare_messages_for_request(
        provider, messages, tools=tools, thinking=thinking,
    )

    payload = {
        "model": used_model,
        "messages": shaped,
        "stream": True,
    }
    if tools:
        payload["tools"] = pc.shape_tools_for_provider(provider, tools)
    if tool_choice is not None:
        payload["tool_choice"] = pc.sanitize_tool_choice(provider, tool_choice)
    _apply_token_limit(payload, provider, request_url=url)
    temperature = provider.get("temperature")
    if temperature is not None and not _skip_temperature(provider, thinking, model=used_model):
        payload["temperature"] = pc.clamp_temperature(provider, temperature)

    if thinking and pc.supports_thinking(provider):
        pc.apply_provider_payload_extras(
            payload,
            provider,
            thinking,
            has_images=cc.messages_have_images(shaped),
        )

    _finalize_chat_payload(payload, provider, cache_conv_id=cache_conv_id, request_url=url)

    from services import openai_api as oai

    oai.sanitize_outbound_chat_payload(payload, provider, request_url=url)
    oai.finalize_http_payload(payload, provider, request_url=url)
    if oai.is_openai_provider(provider) or "openai.com" in url.lower():
        log.info(
            "OpenAI chat stream model=%s keys=%s",
            payload.get("model"),
            sorted(k for k in payload if k != "messages"),
        )

    client = _get_client()
    try:
        for attempt in range(2):
            async with client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread())[:800].decode("utf-8", "replace")
                    if attempt == 0 and _provider_400_fallback(
                        payload, provider, resp.status_code, body,
                    ):
                        continue
                    from services.provider_errors import friendly_provider_error

                    log.error("Provider [%s] stream %s: %s", provider.get("name", "?"), resp.status_code, body[:500])
                    msg = friendly_provider_error(resp.status_code, body, provider=provider, action="chat stream")
                    raise httpx.HTTPStatusError(msg, request=resp.request, response=resp)
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        yield line + "\n\n"
                    elif line == "data: [DONE]":
                        yield "data: [DONE]\n\n"
                        break
            return
    except httpx.RequestError as e:
        log.error("Provider [%s] stream connection failed: %s", provider.get("name", "?"), e)
        raise


async def list_models(provider: dict | None = None) -> list[dict]:
    """List available models from a provider (normalized id + name)."""
    if provider is None:
        provider = get_active_provider()

    url = _build_url(provider, "/v1/models")
    headers = _build_headers(provider)

    client = _get_client()
    resp = await client.get(url, headers=headers, timeout=15)
    body = resp.text
    if resp.status_code >= 400:
        from services.provider_errors import friendly_provider_error

        raise httpx.HTTPStatusError(
            friendly_provider_error(resp.status_code, body, provider=provider, action="model list"),
            request=resp.request,
            response=resp,
        )
    ctype = resp.headers.get("content-type", "")
    if "json" not in ctype.lower() and looks_like_html_body(body):
        from services.provider_errors import friendly_provider_error

        raise ValueError(friendly_provider_error(resp.status_code, body, provider=provider, action="model list"))
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        from services.provider_errors import friendly_provider_error

        raise ValueError(friendly_provider_error(resp.status_code, body, provider=provider, action="model list")) from exc
    models = normalize_model_list(data)
    return filter_models_for_chat(provider, models)


def filter_models_for_chat(provider: dict | None, models: list[dict]) -> list[dict]:
    """Drop Imagine/voice models from Grok chat picker (they are not chat completions)."""
    if not isinstance(provider, dict) or provider.get("type") != "grok":
        return models
    from services import grok as gk

    out: list[dict] = []
    for row in models or []:
        mid = str((row or {}).get("id") or "").strip()
        if not mid:
            continue
        if not gk.is_chat_model(mid):
            continue
        out.append(row)
    return out


def looks_like_html_body(text: str) -> bool:
    from services.provider_errors import looks_like_html

    return looks_like_html(text)


def normalize_model_entry(entry) -> dict | None:
    """Normalize OpenAI / Ollama / vendor-specific model list entries."""
    if isinstance(entry, str):
        mid = entry.strip()
        return {"id": mid, "name": mid} if mid else None
    if not isinstance(entry, dict):
        return None
    mid = str(
        entry.get("id")
        or entry.get("model")
        or entry.get("name")
        or entry.get("model_name")
        or ""
    ).strip()
    if not mid:
        return None
    name = str(entry.get("name") or entry.get("display_name") or mid).strip()
    return {"id": mid, "name": name}


def normalize_model_list(payload) -> list[dict]:
    """Extract and dedupe model rows from assorted /v1/models response shapes."""
    raw = payload
    if isinstance(raw, dict):
        raw = (
            raw.get("data")
            or raw.get("models")
            or raw.get("result")
            or raw.get("items")
            or []
        )
        if isinstance(raw, dict):
            raw = raw.get("data") or raw.get("models") or raw.get("items") or []
    if not isinstance(raw, list):
        return []

    out: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        norm = normalize_model_entry(item)
        if not norm:
            continue
        key = norm["id"].casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(norm)
    out.sort(key=lambda row: row["id"].lower())
    return out


async def health_check(provider: dict | None = None) -> bool:
    """Check if a provider is reachable."""
    if provider is None:
        provider = get_active_provider()
    try:
        url = _build_url(provider, "/v1/models")
        headers = _build_headers(provider)
        client = _get_client()
        resp = await client.get(url, headers=headers, timeout=15)
        return resp.status_code == 200
    except Exception as e:
        log.warning("Provider health check failed [%s]: %s", provider.get("name", "?"), e)
        return False
