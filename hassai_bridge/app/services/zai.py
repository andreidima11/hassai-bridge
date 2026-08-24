"""GLM (Z.ai / Zhipu) request quirks.

Documented at docs.z.ai. The OpenAI-compatible surface deviates in ways that
produce HTTP 400 rather than being ignored:

* ``temperature`` is capped at 1.0, not OpenAI's 2.0.
* ``tool_choice`` accepts only ``auto``.
* Every function needs both ``description`` and ``parameters``; OpenAI lets
  either be omitted.
* Thinking is ``{"thinking": {"type": "enabled", "clear_thinking": false}}`` with
  a separate top-level ``reasoning_effort``. Preserved Thinking keeps prior
  ``reasoning_content`` in context for tool loops and better prompt-cache hits.
* Prompt cache is reported the OpenAI way, in
  ``usage.prompt_tokens_details.cached_tokens``, with no miss counter.
"""

from __future__ import annotations

import re

from services import deepseek as ds

THINKING_MODES = ds.THINKING_MODES

MAX_TEMPERATURE = 1.0
MAX_OUTPUT_TOKENS = 131072

# reasoning_effort landed with GLM-5.2; older families take thinking on/off only.
_EFFORT_MODELS = re.compile(r"glm-5(\.\d+)?(-|$)|glm-5", re.I)
# GLM-5.3 accepts only low / high / max.
_LIMITED_EFFORT_MODELS = re.compile(r"glm-5\.3", re.I)
# Families that always think — sending disabled will not turn it off.
_FORCED_THINKING = re.compile(r"glm-5\.3|glm-4\.7|glm-4\.5v", re.I)


def is_glm_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "glm"


def normalize_thinking_mode(value: str | None, default: str = "auto") -> str:
    return ds.normalize_thinking_mode(value, default=default)


def supports_reasoning_effort(model: str | None) -> bool:
    return bool(model and _EFFORT_MODELS.search(str(model)))


def thinking_is_forced(model: str | None) -> bool:
    return bool(model and _FORCED_THINKING.search(str(model)))


def _effort_for(mode: str, auto: dict, model: str) -> str | None:
    if not supports_reasoning_effort(model):
        return None
    limited = bool(_LIMITED_EFFORT_MODELS.search(str(model)))
    if mode == "off":
        # GLM-5.2 maps "none" to skip-thinking; GLM-5.3 cannot go below low.
        return "low" if limited else "none"
    if mode == "max":
        return "max"
    if mode == "high":
        return "high"
    if not auto.get("enabled"):
        return "low" if limited else "none"
    return "max" if auto.get("effort") == "max" else "high"


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    """Resolve GLM thinking for one request. None when the provider is not GLM."""
    if not is_glm_provider(provider):
        return None

    model = str(provider.get("model") or "")
    default_mode = normalize_thinking_mode(provider.get("thinking_mode"))
    mode = normalize_thinking_mode(override, default=default_mode)

    if mode == "auto":
        auto = ds.auto_thinking_decision(user_text, tools_active=tools_active)
        enabled = bool(auto.get("enabled"))
        reason = auto.get("reason", "")
    else:
        auto = {}
        enabled = mode != "off"
        reason = ""

    if not enabled and thinking_is_forced(model):
        # Be honest about what the server will do rather than reporting "off".
        enabled = True
        reason = reason or "forced_by_model"

    return {
        "mode": mode,
        "enabled": enabled,
        "effort": _effort_for(mode, auto, model),
        "auto_reason": reason,
    }


def apply_thinking_payload(payload: dict, thinking: dict | None, *, provider: dict | None = None) -> None:
    if not thinking:
        return
    enabled = bool(thinking.get("enabled"))
    thinking_body: dict = {"type": "enabled" if enabled else "disabled"}
    if enabled:
        # Preserved Thinking — docs.z.ai recommends clear_thinking=false for agents.
        thinking_body["clear_thinking"] = False
    payload["thinking"] = thinking_body
    effort = thinking.get("effort")
    model = str((provider or {}).get("model") or payload.get("model") or "")
    if effort and supports_reasoning_effort(model):
        payload["reasoning_effort"] = effort


def assistant_turn(message: dict) -> dict:
    """Preserve reasoning_content for GLM tool / multi-turn loops."""
    out = dict(message)
    if "reasoning_content" in message or out.get("tool_calls"):
        out["reasoning_content"] = message.get("reasoning_content") or ""
    return out


def prepare_messages_for_tools(messages: list[dict] | None) -> list[dict]:
    """Ensure assistant turns carry reasoning_content when tools are active."""
    out: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if msg.get("role") != "assistant":
            out.append(msg)
            continue
        row = dict(msg)
        reasoning = row.get("reasoning_content")
        row["reasoning_content"] = str(reasoning) if reasoning else ""
        out.append(row)
    return out


def clamp_temperature(value):
    """GLM rejects anything above 1.0 with 'Parameter is invalid'."""
    try:
        temp = float(value)
    except (TypeError, ValueError):
        return value
    return min(max(temp, 0.0), MAX_TEMPERATURE)


def sanitize_tool_choice(value):
    """GLM documents `auto` as the only accepted value."""
    if value is None:
        return None
    return "auto"


def shape_tools(tools: list | None) -> list | None:
    """Fill in the fields GLM requires on every function declaration."""
    if not tools:
        return tools
    shaped = []
    for tool in tools:
        if not isinstance(tool, dict) or tool.get("type") != "function":
            shaped.append(tool)
            continue
        fn = dict(tool.get("function") or {})
        if not fn.get("description"):
            fn["description"] = fn.get("name") or "tool"
        params = fn.get("parameters")
        if not isinstance(params, dict) or not params:
            fn["parameters"] = {"type": "object", "properties": {}}
        shaped.append({**tool, "function": fn})
    return shaped


def cache_tokens_from_usage(usage: dict | None) -> tuple[int, int]:
    """(hit, miss) — GLM reports hits only, so the miss count is derived."""
    if not isinstance(usage, dict):
        return 0, 0
    details = usage.get("prompt_tokens_details")
    hit = int((details or {}).get("cached_tokens") or 0) if isinstance(details, dict) else 0
    prompt = int(usage.get("prompt_tokens") or 0)
    miss = max(prompt - hit, 0)
    return hit, miss


def log_cache_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not is_glm_provider(provider) or not isinstance(usage, dict):
        return
    hit, miss = cache_tokens_from_usage(usage)
    if hit or miss:
        from logging import getLogger

        prefix = f"[{user_id}] " if user_id else ""
        getLogger("hassai.providers").info(
            "%sGLM prompt cache: hit=%s miss=%s",
            prefix,
            hit,
            miss,
        )
