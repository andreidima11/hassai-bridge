"""DeepSeek-specific thinking mode and request helpers."""

from __future__ import annotations

import re

THINKING_MODES = ("auto", "off", "high", "max")

_SIMPLE_RE = re.compile(
    r"^\s*(?:"
    r"salut|bun[aă]|hello|hi|hey|ce faci|what(?:'s| are) you doing|how are you|"
    r"mulțumesc|multumesc|mersi|thanks|thank you|ok|okay|da|nu|yes|no|"
    r"👋|🙂"
    r")\b[\s!?.,]*$",
    re.I,
)

_PLANNING_RE = re.compile(
    r"\b(?:"
    r"plan(?:u(?:im|l|a)?|ning)?|arhitect|architect|design|analiz|analyze|analyse|"
    r"compare|compar|implement|refactor|debug|troubleshoot|strateg|optimiz|"
    r"explain|explic[aă]|step[\s-]by[\s-]step|pas cu pas|cum constru|how to build|"
    r"how should we|hai sa planu|let'?s plan|scheme|structur|architectur|"
    r"pro(?:iect|ject)|roadmap|trade[\s-]off|decide|evaluat"
    r")\b",
    re.I,
)

_MAX_RE = re.compile(
    r"\b(?:"
    r"from scratch|de la zero|entire system|complete architecture|full refactor|"
    r"production[\s-]ready|comprehensive|g(?:â|a)nde(?:ș|s)te mult|think hard|"
    r"maximum effort|effort max"
    r")\b",
    re.I,
)


def is_deepseek_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "deepseek"


def normalize_thinking_mode(value: str | None, default: str = "auto") -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in THINKING_MODES else default


def auto_thinking_decision(user_text: str, *, tools_active: bool = False) -> dict:
    """Heuristic: simple chat off, planning/architecture on."""
    text = (user_text or "").strip()
    compact = re.sub(r"\s+", " ", text)
    lower = compact.lower()

    if not compact:
        return {"enabled": False, "effort": None, "reason": "empty"}

    if _MAX_RE.search(lower) or (len(_PLANNING_RE.findall(lower)) >= 2 and len(compact) > 120):
        return {"enabled": True, "effort": "max", "reason": "complex"}

    if _SIMPLE_RE.match(compact) or (len(compact) < 28 and not _PLANNING_RE.search(lower)):
        return {"enabled": False, "effort": None, "reason": "simple"}

    if _PLANNING_RE.search(lower):
        return {"enabled": True, "effort": "high", "reason": "planning"}

    if tools_active and len(compact) > 80:
        return {"enabled": True, "effort": "high", "reason": "tools"}

    if len(compact) > 220:
        return {"enabled": True, "effort": "high", "reason": "long"}

    return {"enabled": False, "effort": None, "reason": "default_off"}


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    """Resolve DeepSeek thinking for one chat request. None if not DeepSeek."""
    if not is_deepseek_provider(provider):
        return None

    default_mode = normalize_thinking_mode(
        provider.get("thinking_mode") or provider.get("deepseek_thinking"),
    )
    mode = normalize_thinking_mode(override, default=default_mode)

    if mode == "off":
        return {"mode": "off", "enabled": False, "effort": None, "auto_reason": ""}

    if mode == "high":
        return {"mode": "high", "enabled": True, "effort": "high", "auto_reason": ""}

    if mode == "max":
        return {"mode": "max", "enabled": True, "effort": "max", "auto_reason": ""}

    auto = auto_thinking_decision(user_text, tools_active=tools_active)
    return {
        "mode": "auto",
        "enabled": auto["enabled"],
        "effort": auto["effort"],
        "auto_reason": auto["reason"],
    }


def apply_thinking_payload(payload: dict, thinking: dict | None) -> None:
    if not thinking:
        return
    if thinking.get("enabled"):
        payload["thinking"] = {"type": "enabled"}
        effort = thinking.get("effort") or "high"
        payload["reasoning_effort"] = effort
    else:
        payload["thinking"] = {"type": "disabled"}


def assistant_turn(message: dict) -> dict:
    """Preserve reasoning_content for DeepSeek tool / multi-turn loops.

    When the message includes tool_calls (or already has reasoning), always
    keep the ``reasoning_content`` key — DeepSeek returns HTTP 400 if it is
    omitted after thinking-mode tool turns.
    """
    out = dict(message)
    if "reasoning_content" in message or out.get("tool_calls"):
        out["reasoning_content"] = message.get("reasoning_content") or ""
    return out


def prepare_messages_for_tools(messages: list[dict] | None) -> list[dict]:
    """Ensure every assistant message carries reasoning_content when tools are used.

    DeepSeek docs (Thinking Mode → Tool Calls): when a request carries ``tools``,
    the reasoning_content of every intermediate assistant turn must be passed
    back — including turns that did not call a tool. Missing field → HTTP 400.
    Assistant turns with no recorded CoT use an empty string.
    """
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


def strip_reasoning(messages: list[dict] | None) -> list[dict]:
    """Drop reasoning_content everywhere (fallback when pass-back is rejected)."""
    out: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, dict) or "reasoning_content" not in msg:
            out.append(msg)
            continue
        row = dict(msg)
        row.pop("reasoning_content", None)
        out.append(row)
    return out


def is_reasoning_passback_error(status_code: int, body: str | None) -> bool:
    """True for DeepSeek's 'reasoning_content must be passed back' HTTP 400."""
    if status_code != 400:
        return False
    text = (body or "").lower()
    return "reasoning_content" in text and (
        "passed back" in text or "thinking mode" in text
    )


def log_cache_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not is_deepseek_provider(provider) or not isinstance(usage, dict):
        return
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens") or 0)
    if hit or miss:
        log_prefix = f"[{user_id}] " if user_id else ""
        from logging import getLogger

        getLogger("hassai.providers").info(
            "%sDeepSeek KV cache: hit=%s miss=%s",
            log_prefix,
            hit,
            miss,
        )
