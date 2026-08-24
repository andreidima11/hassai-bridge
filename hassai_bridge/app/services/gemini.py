"""Gemini-specific request helpers (thought signatures + thinking).

Gemini 2.5/3 thinking models return an encrypted ``thought_signature`` on
function-call parts. The OpenAI-compatible endpoint exposes it as
``extra_content.google.thought_signature`` (or ``extra_content.vertex.*``).
It must be echoed back on the next request or the API returns HTTP 400.

Thinking is controlled via ``reasoning_effort`` on the OpenAI-compat surface
(low / medium / high; ``none`` disables thinking on some 2.5 models only).

See: https://ai.google.dev/gemini-api/docs/openai
"""

from __future__ import annotations

import re

from services import deepseek as ds

THINKING_MODES = ds.THINKING_MODES

SKIP_SIGNATURE = "skip_thought_signature_validator"

_GEMINI_25 = re.compile(r"gemini-2\.5", re.I)
_GEMINI_25_PRO = re.compile(r"gemini-2\.5-pro", re.I)


def is_gemini_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "gemini"


def normalize_thinking_mode(value: str | None, default: str = "auto") -> str:
    return ds.normalize_thinking_mode(value, default=default)


def can_disable_thinking(model: str | None) -> bool:
    """Some Gemini 2.5 models accept reasoning_effort=none; Gemini 3 cannot."""
    mid = str(model or "").lower()
    if not mid or _GEMINI_25_PRO.search(mid):
        return False
    return bool(_GEMINI_25.search(mid))


def _reasoning_effort(mode: str, auto: dict, model: str) -> str | None:
    if mode == "off":
        return "none" if can_disable_thinking(model) else None
    if mode == "max" or mode == "high":
        return "high"
    if mode == "auto":
        if not auto.get("enabled"):
            return "none" if can_disable_thinking(model) else None
        if auto.get("effort") in ("max", "high"):
            return "high"
        return "low"
    return None


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    """Resolve Gemini thinking for one chat request."""
    if not is_gemini_provider(provider):
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

    effort = _reasoning_effort(mode, auto, model)
    if effort == "none":
        enabled = False

    return {
        "mode": mode,
        "enabled": enabled,
        "effort": effort,
        "auto_reason": reason,
    }


def apply_thinking_payload(payload: dict, thinking: dict | None, *, provider: dict | None = None) -> None:
    if not thinking:
        return
    model = str((provider or {}).get("model") or payload.get("model") or "")
    has_tools = bool(payload.get("tools"))
    effort = thinking.get("effort")

    # Gemini rejects some reasoning_effort + tools combos on the OpenAI-compat
    # surface (generic INVALID_ARGUMENT). Omit "none" when tools are loaded and
    # let the model default — same idea as GPT-5.6+ on OpenAI Chat Completions.
    if isinstance(effort, str) and effort:
        if effort == "none" and has_tools:
            return
        payload["reasoning_effort"] = effort
    elif not thinking.get("enabled") and can_disable_thinking(model) and not has_tools:
        payload["reasoning_effort"] = "none"


def is_gemini_retryable_400(status_code: int, body: str | None, payload: dict | None) -> bool:
    if status_code != 400 or not isinstance(payload, dict):
        return False
    text = (body or "").lower()
    if is_thought_signature_error(status_code, body or ""):
        return True
    # Generic INVALID_ARGUMENT often means missing tool-result `name` or
    # thought signatures — retry after repair even when tools were dropped
    # on the final agent round.
    return "invalid argument" in text


def repair_payload_after_gemini_400(payload: dict) -> None:
    """Best-effort repair before retrying a Gemini 400."""
    payload["messages"] = prepare_messages_for_tools(payload.get("messages") or [])
    payload.pop("reasoning_effort", None)


def shape_tools(tools: list | None) -> list | None:
    """Fill required OpenAI-compat fields Gemini rejects when omitted."""
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


def _tool_call_signature(tool_call: dict) -> str:
    extra = tool_call.get("extra_content")
    if not isinstance(extra, dict):
        return ""
    for vendor in ("google", "vertex"):
        block = extra.get(vendor)
        if isinstance(block, dict):
            sig = str(block.get("thought_signature") or "").strip()
            if sig:
                return sig
    return ""


def _inject_skip_signature(tool_call: dict, *, vendor: str = "google") -> dict:
    out = dict(tool_call)
    extra = dict(out.get("extra_content") or {})
    block = dict(extra.get(vendor) or {})
    block["thought_signature"] = SKIP_SIGNATURE
    extra[vendor] = block
    out["extra_content"] = extra
    return out


def ensure_tool_calls_signed(tool_calls: list[dict] | None, *, inject_skip: bool = False) -> list[dict]:
    """Ensure tool calls carry a signature (all when backfilling replayed history)."""
    out: list[dict] = []
    for call in tool_calls or []:
        if not isinstance(call, dict):
            continue
        row = dict(call)
        if inject_skip and not _tool_call_signature(row):
            row = _inject_skip_signature(row)
        out.append(row)
    return out


def assistant_turn(message: dict) -> dict:
    """Preserve Gemini thought signatures from a model tool-call response."""
    out = dict(message)
    if out.get("content") is None:
        out["content"] = ""
    if out.get("tool_calls"):
        out["tool_calls"] = ensure_tool_calls_signed(out["tool_calls"], inject_skip=False)
    return out


def _tool_call_names_by_id(messages: list[dict]) -> dict[str, str]:
    """Map tool_call id → function name from assistant turns."""
    names: dict[str, str] = {}
    for msg in messages:
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        for call in msg.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            cid = str(call.get("id") or "").strip()
            fname = str((call.get("function") or {}).get("name") or "").strip()
            if cid and fname:
                names[cid] = fname
    return names


def ensure_tool_result_names(messages: list[dict] | None) -> list[dict]:
    """Gemini requires `name` on role=tool (function_response.name cannot be empty)."""
    msgs = list(messages or [])
    names = _tool_call_names_by_id(msgs)
    out: list[dict] = []
    for msg in msgs:
        if not isinstance(msg, dict) or msg.get("role") != "tool":
            out.append(msg)
            continue
        row = dict(msg)
        if not str(row.get("name") or "").strip():
            cid = str(row.get("tool_call_id") or "").strip()
            if cid and cid in names:
                row["name"] = names[cid]
        out.append(row)
    return out


def prepare_messages_for_tools(messages: list[dict] | None) -> list[dict]:
    """Backfill skip signatures + tool-result names Gemini requires."""
    out: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            out.append(msg)
            continue
        row = dict(msg)
        if row.get("content") is None:
            row["content"] = ""
        row["tool_calls"] = ensure_tool_calls_signed(msg["tool_calls"], inject_skip=True)
        out.append(row)
    return ensure_tool_result_names(out)


def merge_tool_call_delta(entry: dict, delta: dict) -> None:
    """Merge a streaming tool_calls delta, keeping Gemini extra_content."""
    if delta.get("id"):
        entry["id"] = delta["id"]
    fn = delta.get("function") or {}
    if fn.get("name"):
        entry["name"] = fn["name"]
    if fn.get("arguments"):
        entry["arguments"] = entry.get("arguments", "") + fn["arguments"]
    if delta.get("extra_content"):
        entry["extra_content"] = delta["extra_content"]


def build_tool_call(entry: dict, *, fallback_idx: int) -> dict:
    """Build an OpenAI-style tool call dict from stream accumulation."""
    call: dict = {
        "id": entry.get("id") or f"call_{fallback_idx}",
        "type": "function",
        "function": {
            "name": entry.get("name") or "",
            "arguments": entry.get("arguments") or "",
        },
    }
    extra = entry.get("extra_content")
    if isinstance(extra, dict) and extra:
        call["extra_content"] = extra
    return call


def is_thought_signature_error(status_code: int, body: str | None) -> bool:
    if status_code != 400:
        return False
    text = (body or "").lower()
    return "thought_signature" in text and "function call" in text
