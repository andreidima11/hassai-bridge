"""OpenRouter OpenAI-compatible gateway helpers.

Docs: https://openrouter.ai/docs/quickstart
Chat Completions: https://openrouter.ai/api/v1
Attribution: HTTP-Referer + X-OpenRouter-Title (+ optional categories).
Extras we surface in Settings:
- models[] fallbacks
- provider preferences (sort, allow_fallbacks, data_collection, zdr)
- context-compression plugin
"""

from __future__ import annotations

_DEFAULT_REFERER = "https://github.com/andreidima11/hassai-bridge"
_DEFAULT_TITLE = "HASSAI Bridge"
# Marketplace categories that fit a Home Assistant agent / chat bridge.
_DEFAULT_CATEGORIES = "personal-agent,general-chat"

_SORT_OPTIONS = frozenset({"", "price", "throughput", "latency"})
_DATA_COLLECTION = frozenset({"allow", "deny"})


def is_openrouter_provider(provider: dict | None) -> bool:
    if not isinstance(provider, dict):
        return False
    if str(provider.get("type") or "").strip().lower() == "openrouter":
        return True
    base = str(provider.get("base_url") or "").strip().lower()
    return "openrouter.ai" in base


def attribution_headers() -> dict[str, str]:
    """Headers OpenRouter uses for app identification / rankings.

    Docs prefer X-OpenRouter-Title; X-Title remains for older gateways.
    """
    return {
        "HTTP-Referer": _DEFAULT_REFERER,
        "X-OpenRouter-Title": _DEFAULT_TITLE,
        "X-Title": _DEFAULT_TITLE,
        "X-OpenRouter-Categories": _DEFAULT_CATEGORIES,
    }


def openrouter_options(provider: dict | None) -> dict:
    """Normalized OpenRouter extras stored on the provider record."""
    if not isinstance(provider, dict):
        return {}
    raw = provider.get("openrouter")
    return dict(raw) if isinstance(raw, dict) else {}


def parse_model_list(value) -> list[str]:
    """Split comma/newline-separated model ids, drop empties, dedupe (order kept)."""
    if isinstance(value, list):
        parts = [str(x or "").strip() for x in value]
    else:
        text = str(value or "").replace("\n", ",")
        parts = [p.strip() for p in text.split(",")]
    out: list[str] = []
    seen: set[str] = set()
    for mid in parts:
        if not mid:
            continue
        key = mid.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(mid)
    return out


def normalize_openrouter_options(raw: dict | None) -> dict:
    """Sanitize Settings payload for storage on the provider."""
    src = raw if isinstance(raw, dict) else {}
    fallbacks = parse_model_list(src.get("fallback_models") or src.get("models") or "")
    sort = str(src.get("sort") or "").strip().lower()
    if sort not in _SORT_OPTIONS:
        sort = ""
    data_collection = str(src.get("data_collection") or "allow").strip().lower()
    if data_collection not in _DATA_COLLECTION:
        data_collection = "allow"
    allow_fallbacks = src.get("allow_fallbacks")
    if allow_fallbacks is None:
        allow_fallbacks = True
    zdr = bool(src.get("zdr"))
    # Tri-state: None = omit (API default), True/False = explicit plugin flag.
    compression = src.get("context_compression")
    if compression in ("", None):
        compression = None
    else:
        compression = bool(compression)
    return {
        "fallback_models": fallbacks,
        "sort": sort,
        "allow_fallbacks": bool(allow_fallbacks),
        "data_collection": data_collection,
        "zdr": zdr,
        "context_compression": compression,
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


def apply_request_extras(payload: dict, provider: dict | None) -> None:
    """Mutate chat/completions JSON with OpenRouter-only fields from Settings."""
    if not is_openrouter_provider(provider):
        return
    opts = normalize_openrouter_options(openrouter_options(provider))

    primary = str(payload.get("model") or "").strip()
    fallbacks = [m for m in opts["fallback_models"] if m.casefold() != primary.casefold()]
    if fallbacks:
        # Primary stays in `model`; `models` is the ordered fallback list.
        payload["models"] = fallbacks

    provider_pref: dict = {}
    if opts["sort"]:
        provider_pref["sort"] = opts["sort"]
    if opts["allow_fallbacks"] is False:
        provider_pref["allow_fallbacks"] = False
    if opts["data_collection"] == "deny":
        provider_pref["data_collection"] = "deny"
    if opts["zdr"]:
        provider_pref["zdr"] = True
    if provider_pref:
        payload["provider"] = provider_pref

    compression = opts["context_compression"]
    if compression is True:
        payload["plugins"] = [{"id": "context-compression"}]
    elif compression is False:
        payload["plugins"] = [{"id": "context-compression", "enabled": False}]
