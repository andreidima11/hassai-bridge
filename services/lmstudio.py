import httpx
from config import load_config

# ── Persistent connection pool ──
_client: httpx.AsyncClient | None = None


def _get_client(timeout: int = 120) -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=timeout,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
        )
    return _client


async def chat_completion(messages: list[dict], model: str | None = None, stream: bool = False,
                          tools: list | None = None, tool_choice: str | dict | None = None) -> dict:
    """Send a chat completion request to LMStudio's OpenAI-compatible API."""
    cfg = load_config()["lmstudio"]
    base_url = cfg["base_url"].rstrip("/")
    url = f"{base_url}/v1/chat/completions"
    # Config model takes priority (user explicitly set it); fallback to request model
    cfg_model = cfg.get("model", "default")
    used_model = cfg_model if cfg_model and cfg_model != "default" else (model or "default")
    timeout = cfg.get("timeout", 120)

    payload = {
        "model": used_model,
        "messages": messages,
        "stream": stream,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    max_tokens = cfg.get("max_tokens")
    if max_tokens:
        payload["max_tokens"] = max_tokens
    temperature = cfg.get("temperature")
    if temperature is not None:
        payload["temperature"] = temperature

    client = _get_client(timeout)
    resp = await client.post(url, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        import logging
        logging.getLogger("hassai.lmstudio").error(
            f"LMStudio returned {resp.status_code}: {resp.text[:500]}"
        )
    resp.raise_for_status()
    return resp.json()


async def chat_completion_stream(messages: list[dict], model: str | None = None,
                                 tools: list | None = None, tool_choice: str | dict | None = None):
    """Stream chat completion from LMStudio, yielding SSE chunks."""
    cfg = load_config()["lmstudio"]
    base_url = cfg["base_url"].rstrip("/")
    url = f"{base_url}/v1/chat/completions"
    cfg_model = cfg.get("model", "default")
    used_model = cfg_model if cfg_model and cfg_model != "default" else (model or "default")
    timeout = cfg.get("timeout", 120)

    payload = {
        "model": used_model,
        "messages": messages,
        "stream": True,
    }
    if tools:
        payload["tools"] = tools
    if tool_choice is not None:
        payload["tool_choice"] = tool_choice
    max_tokens = cfg.get("max_tokens")
    if max_tokens:
        payload["max_tokens"] = max_tokens
    temperature = cfg.get("temperature")
    if temperature is not None:
        payload["temperature"] = temperature

    client = _get_client(timeout)
    async with client.stream("POST", url, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if line.startswith("data: "):
                yield line + "\n\n"
            elif line == "data: [DONE]":
                yield "data: [DONE]\n\n"
                break


async def list_models() -> list[dict]:
    """List available models from LMStudio."""
    cfg = load_config()["lmstudio"]
    base_url = cfg["base_url"].rstrip("/")
    url = f"{base_url}/v1/models"

    client = _get_client(15)
    resp = await client.get(url)
    resp.raise_for_status()
    data = resp.json()
    return data.get("data", [])


async def health_check() -> bool:
    """Check if LMStudio is reachable."""
    try:
        cfg = load_config()["lmstudio"]
        base_url = cfg["base_url"].rstrip("/")
        client = _get_client(5)
        resp = await client.get(f"{base_url}/v1/models")
        return resp.status_code == 200
    except Exception:
        return False
