"""Provider-specific chat capabilities and request optimizations."""

from __future__ import annotations

from services import deepseek as ds
from services import gemini as gm
from services import grok as gk
from services import qwen as qw
from services import zai as zi

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
                "models": list(gk.IMAGE_MODELS),
            },
        }
    if provider_type == "openai":
        return {
            KV_CACHE: {
                # Leave headroom under typical 128K context for output + tools.
                "context_budget": 120000,
            },
        }
    if provider_type == "openrouter":
        return {
            KV_CACHE: {
                # Gateway — budget depends on the routed model; keep a generous default.
                "context_budget": 120000,
            },
        }
    if provider_type == "gemini":
        return {
            THINKING: {
                "modes": list(gm.THINKING_MODES),
                "default": "auto",
                "label": "thinking",
                "note": "Maps to reasoning_effort (low/medium/high). "
                        "Off uses none on Gemini 2.5 Flash/Lite; Gemini 3 keeps minimal thinking.",
            },
            KV_CACHE: {
                # Gemini long context — leave room for tools + output.
                "context_budget": 200000,
            },
        }
    if provider_type == "qwen":
        return {
            THINKING: {
                "modes": list(qw.THINKING_MODES),
                "default": "auto",
                "label": "thinking",
                "note": "DashScope rejects thinking on non-streaming calls for some Qwen builds, "
                        "so it is requested only while streaming.",
            },
            KV_CACHE: {
                "context_budget": 120000,
            },
        }
    if provider_type == "glm":
        return {
            THINKING: {
                "modes": list(zi.THINKING_MODES),
                "default": "auto",
                "label": "thinking",
            },
            KV_CACHE: {
                "context_budget": 120000,
            },
        }
    if provider_type in ("local", "ollama", "lmstudio"):
        return {
            KV_CACHE: {
                # Modest message budget — tool schemas dominate local latency.
                "context_budget": 6144,
            },
        }
    return {}


def provider_chat_capabilities(provider: dict | None) -> dict:
    """Effective capabilities for a configured provider instance."""
    if not isinstance(provider, dict):
        return {}
    from services import openai_api as oai

    caps = preset_capabilities(provider.get("type", ""))
    if not caps:
        if oai.is_openai_provider(provider):
            caps = preset_capabilities("openai")
    if oai.is_openai_provider(provider) and oai.supports_reasoning_effort(provider.get("model")):
        caps = dict(caps)
        caps[THINKING] = {
            "modes": list(oai.THINKING_MODES),
            "default": oai.normalize_thinking_mode(provider.get("thinking_mode")),
            "label": "reasoning",
            "note": "Maps to reasoning_effort (none/low/high/max). "
                    "GPT-5.6+ with HA tools is forced to none on Chat Completions.",
        }
    if THINKING in caps:
        thinking = dict(caps[THINKING])
        ptype = provider.get("type", "")
        if ptype == "deepseek":
            thinking["default"] = ds.normalize_thinking_mode(provider.get("thinking_mode"))
        elif ptype == "grok":
            thinking["default"] = gk.normalize_thinking_mode(provider.get("thinking_mode"))
        elif ptype == "qwen":
            thinking["default"] = qw.normalize_thinking_mode(provider.get("thinking_mode"))
        elif ptype == "glm":
            thinking["default"] = zi.normalize_thinking_mode(provider.get("thinking_mode"))
        elif ptype == "gemini":
            thinking["default"] = gm.normalize_thinking_mode(provider.get("thinking_mode"))
        elif oai.is_openai_provider(provider):
            thinking["default"] = oai.normalize_thinking_mode(provider.get("thinking_mode"))
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
    models = image_generation_models(provider) or list(gk.IMAGE_MODELS)
    default_model = gk.default_image_model(provider if isinstance(provider, dict) else None)
    return {
        "type": "function",
        "function": {
            "name": "generate_image",
            "description": (
                "Generate a new image from a detailed text prompt using Grok Imagine "
                f"(server uses {default_model}). "
                "Use when the user asks to create, draw, design, or visualize something. "
                "Do NOT use for Frigate/camera/security snapshots, outdoor detections, or "
                "photos of people/cars already detected — use frigate_events / frigate_snapshot instead. "
                "Do not use for editing an uploaded photo unless the user explicitly asks to generate a new image. "
                "Do not invent or pass a model id — the bridge selects a valid Imagine model."
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
                    # Optional for backward compatibility; bridge validates/ignores bad values
                    "model": {
                        "type": "string",
                        "description": (
                            f"Optional Imagine model id. Prefer omitting; default is {default_model}. "
                            f"Allowed: {', '.join(models)}."
                        ),
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


def context_budget(provider: dict | None) -> int:
    """Prompt budget for a provider — KV window, or a multiple of max_tokens."""
    if supports_kv_cache(provider):
        return kv_context_budget(provider)
    if not isinstance(provider, dict):
        return 2048 * 3
    try:
        return int(provider.get("max_tokens", 2048)) * 3
    except (TypeError, ValueError):
        return 2048 * 3


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
    if ptype == "glm":
        return zi.cache_tokens_from_usage(usage)
    if ptype == "qwen":
        return qw.cache_tokens_from_usage(usage)
    from services import openai_api as oai

    if oai.is_openai_provider(provider):
        return oai.cache_tokens_from_usage(usage)
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
    if ptype == "qwen":
        return qw.resolve_thinking(
            provider,
            override=override,
            user_text=user_text,
            tools_active=tools_active,
        )
    if ptype == "glm":
        return zi.resolve_thinking(
            provider,
            override=override,
            user_text=user_text,
            tools_active=tools_active,
        )
    if ptype == "gemini":
        return gm.resolve_thinking(
            provider,
            override=override,
            user_text=user_text,
            tools_active=tools_active,
        )
    from services import openai_api as oai

    if oai.is_openai_provider(provider):
        return oai.resolve_thinking(
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


def prepare_messages_for_request(
    provider: dict,
    messages: list[dict],
    *,
    tools: list | None = None,
    thinking: dict | None = None,
) -> list[dict]:
    """Provider-specific message shaping before chat completions.

    DeepSeek requires reasoning_content on every assistant turn whenever the
    request carries ``tools`` — independent of the current thinking toggle,
    because earlier turns in the same conversation may have used thinking.

    Providers without vision get image parts stripped from the whole history:
    an old photo left in the transcript is an HTTP 400 on a text-only model, not
    something it quietly skips.
    """
    from services import chat_content as cc
    from services import providers as pv

    shaped = messages
    if not pv.provider_supports_vision(provider) and cc.messages_have_images(shaped):
        shaped = cc.strip_all_images(shaped)
    if provider.get("type") == "gemini":
        shaped = gm.prepare_messages_for_tools(shaped)
    if provider.get("type") == "deepseek" and tools:
        return ds.prepare_messages_for_tools(shaped)
    if provider.get("type") == "glm" and tools:
        return zi.prepare_messages_for_tools(shaped)
    return shaped


def apply_provider_payload_extras(payload: dict, provider: dict, thinking: dict | None, *, has_images: bool = False) -> None:
    ptype = provider.get("type", "")
    if ptype == "deepseek":
        ds.apply_thinking_payload(payload, thinking)
    elif ptype == "grok":
        gk.apply_thinking_payload(payload, thinking, provider=provider, has_images=has_images)
    elif ptype == "qwen":
        qw.apply_thinking_payload(payload, thinking, provider=provider)
    elif ptype == "glm":
        zi.apply_thinking_payload(payload, thinking, provider=provider)
    elif ptype == "gemini":
        gm.apply_thinking_payload(payload, thinking, provider=provider)
    else:
        from services import openai_api as oai

        if oai.is_openai_provider(provider):
            oai.apply_thinking_payload(payload, thinking, provider=provider)


def sanitize_tool_choice(provider: dict | None, value):
    """Narrow tool_choice to what the provider actually accepts."""
    ptype = (provider or {}).get("type", "")
    if ptype == "glm":
        return zi.sanitize_tool_choice(value)
    if ptype == "qwen":
        return qw.sanitize_tool_choice(value)
    return value


def shape_tools_for_provider(provider: dict | None, tools: list | None) -> list | None:
    """Fill in fields a provider requires on function declarations."""
    ptype = (provider or {}).get("type")
    if ptype == "glm":
        return zi.shape_tools(tools)
    if ptype == "gemini":
        from services import gemini as gm

        return gm.shape_tools(tools)
    return tools


def clamp_temperature(provider: dict | None, value):
    """Clamp sampling to the provider's accepted range (GLM tops out at 1.0)."""
    if (provider or {}).get("type") == "glm":
        return zi.clamp_temperature(value)
    return value


def assistant_turn(provider: dict, message: dict) -> dict:
    ptype = provider.get("type")
    if ptype == "deepseek":
        return ds.assistant_turn(message)
    if ptype == "grok":
        return gk.assistant_turn(message)
    if ptype == "glm":
        return zi.assistant_turn(message)
    if ptype == "gemini":
        out = gm.assistant_turn(message)
        out.pop("reasoning_content", None)
        return out
    out = dict(message)
    out.pop("reasoning_content", None)
    return out


def needs_reasoning_in_tool_loop(provider: dict) -> bool:
    return provider.get("type") in ("deepseek", "grok", "glm")


def log_provider_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not isinstance(provider, dict) or not isinstance(usage, dict):
        return
    if provider.get("type") == "deepseek":
        ds.log_cache_usage(provider, usage, user_id=user_id)
    elif provider.get("type") == "grok":
        gk.log_cache_usage(provider, usage, user_id=user_id)
    elif provider.get("type") == "glm":
        zi.log_cache_usage(provider, usage, user_id=user_id)
    else:
        from services import openai_api as oai

        if oai.is_openai_provider(provider):
            oai.log_cache_usage(provider, usage, user_id=user_id)
