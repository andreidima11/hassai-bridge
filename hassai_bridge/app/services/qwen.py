"""Qwen (Alibaba DashScope) request quirks on the OpenAI-compatible endpoint.

Documented under alibabacloud.com/help/en/model-studio. The important ones:

* Thinking is a top-level ``enable_thinking`` boolean when calling over plain
  HTTP (``extra_body`` is an SDK detail, not a wire field).
* Several Qwen families reject thinking on non-streaming calls outright:
  ``parameter.enable_thinking only support stream call``. We therefore only ask
  for thinking while streaming, which is safe on every model.
* ``-thinking`` builds refuse ``enable_thinking: false``, so the flag is left
  off entirely for them.
* ``tool_choice`` is limited to ``auto`` / ``none``; forcing a named function is
  rejected in thinking mode.
* Prompt cache is reported the OpenAI way, in
  ``usage.prompt_tokens_details.cached_tokens``.
"""

from __future__ import annotations

import re

from services import deepseek as ds

THINKING_MODES = ds.THINKING_MODES

# Builds where reasoning is always on and the flag must not be sent as false.
_ALWAYS_THINKING = re.compile(r"-thinking\b|^qwq|^qvq", re.I)
# Models with no thinking mode at all reject the flag with NotSupportEnableThinking.
_NO_THINKING = re.compile(r"qwen-?(vl-)?(max|plus|turbo)-\d|qwen2(\.\d)?|qwen1", re.I)


def is_qwen_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "qwen"


def normalize_thinking_mode(value: str | None, default: str = "auto") -> str:
    return ds.normalize_thinking_mode(value, default=default)


def thinking_is_forced(model: str | None) -> bool:
    return bool(model and _ALWAYS_THINKING.search(str(model)))


def supports_thinking_flag(model: str | None) -> bool:
    mid = str(model or "").strip()
    if not mid:
        return False
    if thinking_is_forced(mid):
        return False  # flag must be omitted, not set
    return not _NO_THINKING.search(mid)


def _budget_for(mode: str, auto: dict) -> int | None:
    if mode == "max":
        return 32768
    if mode == "high":
        return 16384
    if mode == "auto" and auto.get("effort") == "max":
        return 32768
    return None


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    """Resolve Qwen thinking for one request. None when the provider is not Qwen."""
    if not is_qwen_provider(provider):
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

    if thinking_is_forced(model):
        enabled = True
        reason = reason or "forced_by_model"

    return {
        "mode": mode,
        "enabled": enabled,
        "budget": _budget_for(mode, auto),
        "auto_reason": reason,
    }


def apply_thinking_payload(payload: dict, thinking: dict | None, *, provider: dict | None = None) -> None:
    """Set enable_thinking, but only where DashScope will accept it.

    Thinking on a non-streaming call is rejected by the open-source Qwen builds,
    and the split between families shifts with every release — so the flag is
    only sent while streaming, which every thinking-capable model accepts.
    """
    if not thinking:
        return
    model = str((provider or {}).get("model") or payload.get("model") or "")
    if not supports_thinking_flag(model):
        return
    if not payload.get("stream"):
        # Non-streaming: never ask for thinking, and say so explicitly so a
        # model that defaults to thinking does not blow the token budget.
        payload["enable_thinking"] = False
        return
    payload["enable_thinking"] = bool(thinking.get("enabled"))
    budget = thinking.get("budget")
    if thinking.get("enabled") and budget:
        payload["thinking_budget"] = int(budget)


def sanitize_tool_choice(value):
    """Named-function forcing is rejected in thinking mode; keep auto/none."""
    if value is None:
        return None
    if isinstance(value, str) and value.lower() in ("auto", "none"):
        return value.lower()
    return "auto"


def cache_tokens_from_usage(usage: dict | None) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    details = usage.get("prompt_tokens_details")
    hit = int((details or {}).get("cached_tokens") or 0) if isinstance(details, dict) else 0
    prompt = int(usage.get("prompt_tokens") or 0)
    return hit, max(prompt - hit, 0)
