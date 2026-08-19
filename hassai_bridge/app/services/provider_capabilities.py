"""Provider-specific chat capabilities and request optimizations."""

from __future__ import annotations

from services import deepseek as ds
from services import grok as gk

THINKING = "thinking"
KV_CACHE = "kv_cache"
IMAGE_GENERATION = "image_generation"


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
    if provider_type == "grok":
        return {
            THINKING: {
                "modes": list(gk.THINKING_MODES),
                "default": "auto",
                "label": "reasoning",
                "note": "Grok reasoning cannot be fully disabled; Off uses low effort.",
            },
            KV_CACHE: {
                "context_budget": 480000,
            },
            IMAGE_GENERATION: {
                "endpoint": "/v1/images/generations",
                "models": ["grok-imagine-image-2.0", "grok-imagine-image"],
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
        ptype = provider.get("type", "")
        if ptype == "deepseek":
            thinking["default"] = ds.normalize_thinking_mode(provider.get("thinking_mode"))
        elif ptype == "grok":
            thinking["default"] = gk.normalize_thinking_mode(provider.get("thinking_mode"))
        caps[THINKING] = thinking
    return caps


def supports_thinking(provider: dict | None) -> bool:
    return THINKING in provider_chat_capabilities(provider)


def supports_kv_cache(provider: dict | None) -> bool:
    return KV_CACHE in provider_chat_capabilities(provider)


def supports_image_generation(provider: dict | None) -> bool:
    return IMAGE_GENERATION in provider_chat_capabilities(provider)


def image_generation_models(provider: dict | None) -> list[str]:
    caps = provider_chat_capabilities(provider)
    ig = caps.get(IMAGE_GENERATION) or {}
    models = ig.get("models") or []
    return [str(m) for m in models if m]


def build_image_generation_tool(provider: dict | None) -> dict:
    models = image_generation_models(provider) or ["grok-imagine-image-2.0"]
    default_model = gk.default_image_model(provider if isinstance(provider, dict) else None)
    return {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate a new image from a detailed text prompt using Grok Imagine. "
                "Use when the user asks to create, draw, design, or visualize something. "
                "Do not use for editing an uploaded photo unless the user explicitly asks to generate a new image."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": "Detailed visual description of the image to create.",
                    },
                    "n": {
                        "type": "integer",
                        "description": "Number of images to generate (1-4). Default 1.",
                        "minimum": 1,
                        "maximum": 4,
                    },
                    "model": {
                        "type": "string",
                        "enum": models,
                        "description": f"Imagine model to use. Default: {default_model}.",
                    },
                },
                "required": ["prompt"],
            },
        },
    }


def kv_context_budget(provider: dict | None) -> int:
    caps = provider_chat_capabilities(provider)
    kv = caps.get(KV_CACHE) or {}
    return int(kv.get("context_budget") or 98000)


def cache_tokens_from_usage(provider: dict | None, usage: dict | None) -> tuple[int, int]:
    if not isinstance(provider, dict) or not isinstance(usage, dict):
        return 0, 0
    ptype = provider.get("type", "")
    if ptype == "deepseek":
        hit = int(usage.get("prompt_cache_hit_tokens") or 0)
        miss = int(usage.get("prompt_cache_miss_tokens") or 0)
        return hit, miss
    if ptype == "grok":
        return gk.cache_tokens_from_usage(usage)
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
    if ptype == "grok":
        return gk.resolve_thinking(
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
    elif ptype == "grok":
        gk.apply_thinking_payload(payload, thinking, provider=provider)


def assistant_turn(provider: dict, message: dict) -> dict:
    ptype = provider.get("type")
    if ptype == "deepseek":
        return ds.assistant_turn(message)
    if ptype == "grok":
        return gk.assistant_turn(message)
    out = dict(message)
    out.pop("reasoning_content", None)
    return out


def needs_reasoning_in_tool_loop(provider: dict) -> bool:
    return provider.get("type") in ("deepseek", "grok")


def log_provider_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not isinstance(provider, dict) or not isinstance(usage, dict):
        return
    if provider.get("type") == "deepseek":
        ds.log_cache_usage(provider, usage, user_id=user_id)
    elif provider.get("type") == "grok":
        gk.log_cache_usage(provider, usage, user_id=user_id)
