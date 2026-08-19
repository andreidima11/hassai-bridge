"""
Multi-provider LLM service.

Supports: Local (LM Studio, Ollama, etc.), OpenAI, Grok (xAI), DeepSeek, GLM (Zhipu).
All providers use the OpenAI-compatible /v1/chat/completions format.
"""

import re
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
        "base_url": "https://api.openai.com",
        "requires_key": True,
    },
    "grok": {
        "name": "Grok (xAI)",
        "base_url": "https://api.x.ai",
        "requires_key": True,
    },
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "requires_key": True,
    },
    "glm": {
        "name": "GLM (Zhipu AI)",
        "base_url": "https://api.z.ai/api/paas/v4",
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
    model = str(provider.get("model") or "").strip()
    return bool(model and _VISION_MODEL_HINTS.search(model))


def get_active_provider() -> dict:
    """Get the currently active provider config."""
    cfg = load_config()
    providers = cfg.get("providers", [])
    active_id = cfg.get("active_provider", "")

    # Find active provider
    for p in providers:
        if p.get("id") == active_id:
            return p

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
    return providers[0] if providers else {}


def get_provider_by_id(provider_id: str) -> dict | None:
    """Get a specific provider by ID."""
    cfg = load_config()
    for p in cfg.get("providers", []):
        if p.get("id") == provider_id:
            return p
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


def resolve_image_provider(primary: dict | None = None, secondary: dict | None = None) -> dict | None:
    """Pick provider for image requests when the primary model lacks vision.

    Priority: dedicated vision provider, then auxiliary (secondary) provider.
    """
    if primary is None:
        primary = get_active_provider()
    vision = get_vision_provider(primary)
    if vision:
        return vision
    if secondary is None:
        secondary = get_secondary_provider(primary)
    return secondary


def get_secondary_provider_by_id(provider_id: str) -> dict | None:
    """Get a specific secondary provider by ID."""
    cfg = load_config()
    for p in cfg.get("secondary_providers", []):
        if p.get("id") == provider_id:
            return p
    return None


def _build_headers(provider: dict) -> dict:
    """Build request headers including auth if needed."""
    headers = {"Content-Type": "application/json"}
    api_key = provider.get("api_key", "")
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _normalize_base_url(raw: str) -> str:
    """Strip endpoint paths from base_url to get the API base.

    Users may paste the full endpoint (e.g. https://api.x.ai/v1/chat/completions).
    Strip known suffixes so we get the versioned base (e.g. https://api.x.ai/v1).
    """
    url = raw.rstrip("/")
    url = re.sub(r"/(chat/completions|completions|responses|models|embeddings)$", "", url)
    return url


def _build_url(provider: dict, path: str) -> str:
    """Build the full API URL for a provider.

    Handles various base_url formats:
      - Plain origin:  https://api.openai.com        → /v1/chat/completions
      - With version:  https://api.x.ai/v1           → /chat/completions
      - Full endpoint: https://api.deepseek.com/chat/ → stripped, then rebuilt
      - Custom base:   https://api.z.ai/api/paas/v4  → /chat/completions
    """
    base = _normalize_base_url(provider.get("base_url", ""))
    # Strip /v1 prefix from the requested path — we decide whether to add it
    clean_path = re.sub(r"^/v1", "", path)  # e.g. "/chat/completions", "/models"

    # If base already contains a version segment (/v1, /v2, /v4 …), keep it
    if re.search(r"/v\d+(/|$)", base):
        return base + clean_path
    # Otherwise prepend /v1
    return base + "/v1" + clean_path


async def chat_completion(messages: list[dict], model: str | None = None, stream: bool = False,
                          tools: list | None = None, tool_choice: str | dict | None = None,
                          provider: dict | None = None) -> dict:
    """Send a chat completion request to the active (or specified) provider."""
    if provider is None:
        provider = get_active_provider()

    url = _build_url(provider, "/v1/chat/completions")
    headers = _build_headers(provider)
    timeout = provider.get("timeout", 120)

    # Model priority: provider config > request param > default
    cfg_model = provider.get("model", "default")
    used_model = cfg_model if cfg_model and cfg_model != "default" else (model or "default")

    payload = {
        "model": used_model,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    max_tokens = provider.get("max_tokens")
    if max_tokens:
        payload["max_tokens"] = max_tokens
    temperature = provider.get("temperature")
    if temperature is not None:
        payload["temperature"] = temperature

    client = _get_client()
    # Retry on transient errors (#20)
    last_exc = None
    for attempt in range(_RETRY_COUNT + 1):
        try:
            resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
            if resp.status_code in _RETRYABLE_STATUS and attempt < _RETRY_COUNT:
                log.warning(f"Provider [{provider.get('name', '?')}] returned {resp.status_code}, retrying ({attempt + 1}/{_RETRY_COUNT})")
                await asyncio.sleep(_RETRY_BACKOFF[attempt])
                continue
            if resp.status_code >= 400:
                log.error(f"Provider [{provider.get('name', '?')}] returned {resp.status_code}: {resp.text[:500]}")
            resp.raise_for_status()
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
                                 provider: dict | None = None):
    """Stream chat completion, yielding SSE chunks."""
    if provider is None:
        provider = get_active_provider()

    url = _build_url(provider, "/v1/chat/completions")
    headers = _build_headers(provider)
    timeout = provider.get("timeout", 120)

    cfg_model = provider.get("model", "default")
    used_model = cfg_model if cfg_model and cfg_model != "default" else (model or "default")

    payload = {
        "model": used_model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    max_tokens = provider.get("max_tokens")
    if max_tokens:
        payload["max_tokens"] = max_tokens
    temperature = provider.get("temperature")
    if temperature is not None:
        payload["temperature"] = temperature

    client = _get_client()
    try:
        async with client.stream("POST", url, json=payload, headers=headers, timeout=timeout) as resp:
            if resp.status_code >= 400:
                body = (await resp.aread())[:800].decode("utf-8", "replace")
                log.error("Provider [%s] stream %s: %s", provider.get("name", "?"), resp.status_code, body)
                raise httpx.HTTPStatusError(
                    f"{resp.status_code} {body[:300]}",
                    request=resp.request,
                    response=resp,
                )
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    yield line + "\n\n"
                elif line == "data: [DONE]":
                    yield "data: [DONE]\n\n"
                    break
    except httpx.RequestError as e:
        log.error("Provider [%s] stream connection failed: %s", provider.get("name", "?"), e)
        raise


async def list_models(provider: dict | None = None) -> list[dict]:
    """List available models from a provider."""
    if provider is None:
        provider = get_active_provider()

    url = _build_url(provider, "/v1/models")
    headers = _build_headers(provider)

    client = _get_client()
    resp = await client.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


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
