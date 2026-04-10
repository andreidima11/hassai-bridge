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


async def chat_completion(messages: list[dict], model: str | None = None, stream: bool = False) -> dict:
    """Send a chat completion request to LMStudio's OpenAI-compatible API."""
    cfg = load_config()["lmstudio"]
    base_url = cfg["base_url"].rstrip("/")
    url = f"{base_url}/v1/chat/completions"
    used_model = model or cfg["model"]
    timeout = cfg.get("timeout", 120)

    payload = {
        "model": used_model,
        "messages": messages,
        "stream": stream,
    }
    max_tokens = cfg.get("max_tokens")
    if max_tokens:
        payload["max_tokens"] = max_tokens
    temperature = cfg.get("temperature")
    if temperature is not None:
        payload["temperature"] = temperature

    client = _get_client(timeout)
    resp = await client.post(url, json=payload)
    resp.raise_for_status()
    return resp.json()


async def chat_completion_stream(messages: list[dict], model: str | None = None):
    """Stream chat completion from LMStudio, yielding SSE chunks."""
    cfg = load_config()["lmstudio"]
    base_url = cfg["base_url"].rstrip("/")
    url = f"{base_url}/v1/chat/completions"
    used_model = model or cfg["model"]
    timeout = cfg.get("timeout", 120)

    payload = {
        "model": used_model,
        "messages": messages,
        "stream": True,
    }
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
