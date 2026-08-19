"""Provider-specific chat capabilities and request optimizations."""

from __future__ import annotations

from services import deepseek as ds

THINKING = "thinking"
KV_CACHE = "kv_cache"


def preset_capabilities(provider_type: str) -> dict:
    """Capabilities available for a provider type (settings UI + docs)."""
    if provider_type == "deepseek":
        return {
            THINKING: {
                "modes": list(ds.THINKING_MODES),
                "default": "auto",
                "label": "thinking",
            },
            KV_CACHE: {
                "context_budget": 98000,
            },
        }
    return {}


def provider_chat_capabilities(provider: dict | None) -> dict:
    """Effective capabilities for a configured provider instance."""
    if not isinstance(provider, dict):
        return {}
    caps = preset_capabilities(provider.get("type", ""))
    if THINKING in caps:
        thinking = dict(caps[THINKING])
        thinking["default"] = ds.normalize_thinking_mode(provider.get("thinking_mode"))
        caps[THINKING] = thinking
    return caps


def supports_thinking(provider: dict | None) -> bool:
    return THINKING in provider_chat_capabilities(provider)


def supports_kv_cache(provider: dict | None) -> bool:
    return KV_CACHE in provider_chat_capabilities(provider)


def kv_context_budget(provider: dict | None) -> int:
    caps = provider_chat_capabilities(provider)
    kv = caps.get(KV_CACHE) or {}
    return int(kv.get("context_budget") or 98000)


def cache_tokens_from_usage(provider: dict | None, usage: dict | None) -> tuple[int, int]:
    if not isinstance(provider, dict) or not isinstance(usage, dict):
        return 0, 0
    if provider.get("type") == "deepseek":
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        miss = int(usage.get("prompt_cache_miss_tokens") or 0)
        return hit, miss
    return 0, 0


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    ptype = provider.get("type", "")
    if ptype == "deepseek":
        return ds.resolve_thinking(
            provider,
            override=override,
            user_text=user_text,
            tools_active=tools_active,
        )
    return None


def thinking_for_provider(thinking_cfg: dict | None, provider: dict) -> dict | None:
    if not thinking_cfg or not supports_thinking(provider):
        return None
    return thinking_cfg


def apply_provider_payload_extras(payload: dict, provider: dict, thinking: dict | None) -> None:
    ptype = provider.get("type", "")
    if ptype == "deepseek":
        ds.apply_thinking_payload(payload, thinking)


def assistant_turn(provider: dict, message: dict) -> dict:
    if provider.get("type") == "deepseek":
        return ds.assistant_turn(message)
    out = dict(message)
    out.pop("reasoning_content", None)
    return out


def needs_reasoning_in_tool_loop(provider: dict) -> bool:
    return provider.get("type") == "deepseek"


def log_provider_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not isinstance(provider, dict) or not isinstance(usage, dict):
        return
    if provider.get("type") == "deepseek":
        ds.log_cache_usage(provider, usage, user_id=user_id)
