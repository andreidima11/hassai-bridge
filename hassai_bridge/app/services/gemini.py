"""Gemini-specific tool-call thought_signature helpers.

Gemini 2.5/3 thinking models return an encrypted ``thought_signature`` on
function-call parts. The OpenAI-compatible endpoint exposes it as
``extra_content.google.thought_signature`` (or ``extra_content.vertex.*``).
It must be echoed back on the next request or the API returns HTTP 400.

See: https://ai.google.dev/gemini-api/docs/thought-signatures
"""

from __future__ import annotations

SKIP_SIGNATURE = "skip_thought_signature_validator"


def is_gemini_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "gemini"


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
    """Ensure the first tool call in each assistant step carries a signature."""
    out: list[dict] = []
    for idx, call in enumerate(tool_calls or []):
        if not isinstance(call, dict):
            continue
        row = dict(call)
        if idx == 0 and not _tool_call_signature(row):
            if inject_skip:
                row = _inject_skip_signature(row)
        out.append(row)
    return out


def assistant_turn(message: dict) -> dict:
    """Preserve Gemini thought signatures from a model tool-call response."""
    out = dict(message)
    if out.get("tool_calls"):
        out["tool_calls"] = ensure_tool_calls_signed(out["tool_calls"], inject_skip=False)
    return out


def prepare_messages_for_tools(messages: list[dict] | None) -> list[dict]:
    """Backfill skip signatures on replayed tool calls that never had one."""
    out: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if msg.get("role") != "assistant" or not msg.get("tool_calls"):
            out.append(msg)
            continue
        row = dict(msg)
        row["tool_calls"] = ensure_tool_calls_signed(msg["tool_calls"], inject_skip=True)
        out.append(row)
    return out


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
