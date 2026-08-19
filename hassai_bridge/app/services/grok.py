"""Grok (x.ai) reasoning, prompt cache, and request helpers."""

from __future__ import annotations

import re

from services import deepseek as ds

THINKING_MODES = ds.THINKING_MODES
GROK_EFFORTS = ("low", "medium", "high", "xhigh")
_XHIGH_MODELS = re.compile(r"grok-4\.6|grok-4\.20-multi-agent", re.I)


def is_grok_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "grok"


def normalize_thinking_mode(value: str | None, default: str = "auto") -> str:
    return ds.normalize_thinking_mode(value, default=default)


def supports_xhigh(model: str | None) -> bool:
    return bool(model and _XHIGH_MODELS.search(str(model)))


def _grok_effort(mode: str, auto: dict, model: str) -> str:
    if mode == "off":
        return "low"
    if mode == "high":
        return "high"
    if mode == "max":
        return "xhigh" if supports_xhigh(model) else "high"
    if not auto.get("enabled"):
        return "low"
    effort = auto.get("effort")
    if effort == "max":
        return "xhigh" if supports_xhigh(model) else "high"
    if effort == "high":
        return "high"
    return "medium"


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    """Resolve Grok reasoning_effort for one chat request."""
    if not is_grok_provider(provider):
        return None

    default_mode = normalize_thinking_mode(provider.get("thinking_mode"))
    mode = normalize_thinking_mode(override, default=default_mode)
    model = str(provider.get("model") or "")
    auto = ds.auto_thinking_decision(user_text, tools_active=tools_active)
    effort = _grok_effort(mode, auto, model)

    return {
        "mode": mode,
        "enabled": True,
        "effort": effort,
        "auto_reason": auto.get("reason") if mode == "auto" else "",
    }


def apply_thinking_payload(payload: dict, thinking: dict | None, *, provider: dict | None = None) -> None:
    if not thinking:
        return
    effort = thinking.get("effort") or "high"
    if effort not in GROK_EFFORTS:
        effort = "high"
    payload["reasoning_effort"] = effort
    payload.pop("temperature", None)
    payload.pop("presence_penalty", None)
    payload.pop("frequency_penalty", None)
    payload.pop("stop", None)


def assistant_turn(message: dict) -> dict:
    out = dict(message)
    reasoning = message.get("reasoning_content")
    if reasoning:
        out["reasoning_content"] = reasoning
    return out


def cache_tokens_from_usage(usage: dict | None) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    prompt = int(usage.get("prompt_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    hit = int(details.get("cached_tokens") or 0)
    miss = max(0, prompt - hit) if prompt else 0
    return hit, miss


def log_cache_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not is_grok_provider(provider) or not isinstance(usage, dict):
        return
    hit, miss = cache_tokens_from_usage(usage)
    if hit or miss:
        log_prefix = f"[{user_id}] " if user_id else ""
        from logging import getLogger

        getLogger("hassai.providers").info(
            "%sGrok prompt cache: hit=%s miss=%s",
            log_prefix,
            hit,
            miss,
        )


def grok_conv_header(session_id: str | None) -> dict[str, str]:
    """Sticky routing header recommended by x.ai for prompt cache hits."""
    sid = str(session_id or "").strip()
    if not sid:
        return {}
    return {"x-grok-conv-id": sid[:128]}
