"""Recover DeepSeek-style DSML tool markup leaked into assistant text.

Some local / secondary models (and DeepSeek V4 when the upstream parser
misses) emit tool calls as text:

  <｜DSML｜tool_calls>
  <｜DSML｜invoke name="search_web">
  <｜DSML｜parameter name="query" string="true">...</｜DSML｜parameter>
  </｜DSML｜invoke>
  </｜DSML｜tool_calls>

Doubled separators (<｜｜DSML｜｜…>) also appear in the wild. We parse these
into OpenAI-style tool_calls and strip the markup from user-visible text.
"""

from __future__ import annotations

import json
import re

# Fullwidth vertical bar used in DeepSeek special tokens.
_FW = "\uff5c"

# <｜DSML｜tag …> or <｜｜DSML｜｜tag …>
_TAG_OPEN = re.compile(
    rf"<{_FW}+DSML{_FW}+(?P<tag>[\w]+)(?P<attrs>[^>]*)>",
    re.IGNORECASE,
)
_TAG_CLOSE = re.compile(
    rf"</{_FW}+DSML{_FW}+(?P<tag>[\w]+)\s*>",
    re.IGNORECASE,
)
_INVOKE_RE = re.compile(
    rf"<{_FW}+DSML{_FW}+invoke\b(?P<attrs>[^>]*)>(?P<body>.*?)</{_FW}+DSML{_FW}+invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_PARAM_RE = re.compile(
    rf"<{_FW}+DSML{_FW}+parameter\b(?P<attrs>[^>]*)>(?P<body>.*?)</{_FW}+DSML{_FW}+parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_CALLS_BLOCK = re.compile(
    rf"<{_FW}+DSML{_FW}+tool_calls\s*>.*?</{_FW}+DSML{_FW}+tool_calls\s*>",
    re.IGNORECASE | re.DOTALL,
)
_ANY_DSML_TAG = re.compile(rf"</?{_FW}+DSML{_FW}+[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""(\w+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def looks_like_dsml(text: str | None) -> bool:
    raw = text or ""
    if "DSML" not in raw:
        return False
    return _FW in raw or "<|" in raw


def _parse_attrs(raw: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for m in _ATTR_RE.finditer(raw or ""):
        out[m.group(1)] = m.group(2) if m.group(2) is not None else (m.group(3) or "")
    return out


def _parse_param_value(attrs: dict[str, str], body: str):
    text = (body or "").strip()
    if attrs.get("string", "").lower() in ("true", "1", "yes"):
        return text
    if not text:
        return text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return text


def extract_tool_calls(text: str | None) -> tuple[str, list[dict]]:
    """Return ``(cleaned_text, openai_tool_calls)`` from DSML markup in ``text``."""
    raw = text or ""
    if not looks_like_dsml(raw):
        return raw, []

    calls: list[dict] = []
    for m in _INVOKE_RE.finditer(raw):
        attrs = _parse_attrs(m.group("attrs"))
        name = (attrs.get("name") or "").strip()
        if not name:
            continue
        args: dict = {}
        for pm in _PARAM_RE.finditer(m.group("body") or ""):
            pa = _parse_attrs(pm.group("attrs"))
            pname = (pa.get("name") or "").strip()
            if not pname:
                continue
            args[pname] = _parse_param_value(pa, pm.group("body") or "")
        calls.append({
            "id": f"dsml_{len(calls)}",
            "type": "function",
            "function": {
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False),
            },
        })

    return strip_dsml(raw), calls


def strip_dsml(text: str | None) -> str:
    """Remove DSML tool markup; leave other prose intact."""
    raw = text or ""
    if not looks_like_dsml(raw):
        return raw
    cleaned = _TOOL_CALLS_BLOCK.sub("", raw)
    cleaned = _INVOKE_RE.sub("", cleaned)
    cleaned = _ANY_DSML_TAG.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def recover_message_tool_calls(message: dict | None) -> list[dict]:
    """If ``message`` has no tool_calls, try DSML in content / reasoning fields.

    Mutates ``message`` content/reasoning to strip markup when recovery runs.
    Returns the recovered (or existing) tool_calls list.
    """
    if not isinstance(message, dict):
        return []
    existing = message.get("tool_calls") or []
    if existing:
        return existing

    sources = [
        ("content", message.get("content") or ""),
        ("reasoning_content", message.get("reasoning_content") or ""),
        ("reasoning", message.get("reasoning") or ""),
    ]
    recovered: list[dict] = []
    for key, val in sources:
        if not isinstance(val, str) or not looks_like_dsml(val):
            continue
        cleaned, calls = extract_tool_calls(val)
        if key == "content":
            message["content"] = cleaned
        else:
            message[key] = cleaned
        if calls and not recovered:
            recovered = calls

    if recovered:
        message["tool_calls"] = recovered
    return recovered
