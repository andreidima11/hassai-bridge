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
    msgs = payload.get("messages") or []
    in_tool_loop = any(
        isinstance(m, dict) and (m.get("role") == "tool" or m.get("tool_calls"))
        for m in msgs
    )
    effort = thinking.get("effort")

    # Mid tool-loop: omit reasoning_effort — signatures + thinking flags often
    # combine into a generic INVALID_ARGUMENT on the OpenAI-compat surface.
    if in_tool_loop:
        return
    if isinstance(effort, str) and effort:
        if effort == "none" and has_tools:
            return
        payload["reasoning_effort"] = effort
    elif not thinking.get("enabled") and can_disable_thinking(model) and not has_tools:
        payload["reasoning_effort"] = "none"


def is_thought_signature_error(status_code: int, body: str | None) -> bool:
    if status_code != 400:
        return False
    text = (body or "").lower()
    return "thought_signature" in text and ("function call" in text or "functioncall" in text)


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
        fn = dict(row.get("function") or {})
        if not str(fn.get("arguments") or "").strip():
            fn["arguments"] = "{}"
            row["function"] = fn
        if not str(row.get("id") or "").strip():
            row["id"] = f"call_{len(out)}"
        if inject_skip and not _tool_call_signature(row):
            row = _inject_skip_signature(row)
        out.append(row)
    return out


def force_skip_signatures(messages: list[dict] | None) -> list[dict]:
    """Overwrite every tool-call signature with skip (truncated/bad streamed sigs)."""
    out: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("role") != "assistant" or not msg.get("tool_calls"):
            out.append(msg)
            continue
        row = dict(msg)
        if row.get("content") is None:
            row["content"] = ""
        signed = []
        for call in row.get("tool_calls") or []:
            if isinstance(call, dict):
                signed.append(_inject_skip_signature(dict(call)))
        row["tool_calls"] = ensure_tool_calls_signed(signed, inject_skip=False)
        out.append(row)
    return ensure_tool_result_names(out)


def assistant_turn(message: dict) -> dict:
    """Preserve Gemini thought signatures; backfill skip when stream omitted them."""
    out = dict(message)
    if out.get("content") is None:
        out["content"] = ""
    if out.get("tool_calls"):
        # Streaming often drops extra_content — skip keeps the next turn alive.
        out["tool_calls"] = ensure_tool_calls_signed(out["tool_calls"], inject_skip=True)
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
        if row.get("content") is None:
            row["content"] = ""
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


def repair_payload_after_gemini_400(payload: dict) -> None:
    """Best-effort repair before retrying a Gemini 400.

    Truncated streamed signatures look present but are invalid — overwrite with
    skip rather than only filling blanks. Drop reasoning_effort too.
    """
    payload["messages"] = force_skip_signatures(payload.get("messages") or [])
    payload.pop("reasoning_effort", None)


def merge_tool_call_delta(entry: dict, delta: dict) -> None:
    """Merge a streaming tool_calls delta, keeping Gemini extra_content."""
    if delta.get("id"):
        entry["id"] = delta["id"]
    fn = delta.get("function") or {}
    if fn.get("name"):
        entry["name"] = fn["name"]
    if fn.get("arguments"):
        entry["arguments"] = entry.get("arguments", "") + fn["arguments"]
    extra = delta.get("extra_content")
    if isinstance(extra, dict) and extra:
        # Prefer later chunks — signature often arrives after name/args.
        entry["extra_content"] = extra


def attach_message_extra_content(entry: dict, extra: dict | None) -> None:
    """Attach delta-level extra_content (pre-tool thinking) onto a tool call."""
    if not isinstance(extra, dict) or not extra:
        return
    if _tool_call_signature(entry):
        return
    entry["extra_content"] = extra


def allocate_stream_tool_index(
    tc: dict,
    accum: dict[int, dict],
    *,
    fallback_i: int,
) -> int:
    """Gemini often omits tool_calls[].index — avoid collapsing parallel calls into 0."""
    if "index" in tc and tc["index"] is not None:
        try:
            return int(tc["index"])
        except (TypeError, ValueError):
            pass
    cid = str(tc.get("id") or "").strip()
    if cid:
        for idx, row in accum.items():
            if row.get("id") == cid:
                return idx
    if fallback_i not in accum:
        return fallback_i
    return max(accum.keys(), default=-1) + 1


def build_tool_call(entry: dict, *, fallback_idx: int) -> dict:
    """Build an OpenAI-style tool call dict from stream accumulation."""
    args = entry.get("arguments") or ""
    if not str(args).strip():
        args = "{}"
    call: dict = {
        "id": entry.get("id") or f"call_{fallback_idx}",
        "type": "function",
        "function": {
            "name": entry.get("name") or "",
            "arguments": args,
        },
    }
    extra = entry.get("extra_content")
    if isinstance(extra, dict) and extra:
        call["extra_content"] = extra
    elif not _tool_call_signature(call):
        call = _inject_skip_signature(call)
    return call
