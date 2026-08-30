"""Extract model thinking from message fields and inline XML tags.

Many OpenRouter / free models emit CoT as ``<thinking>…</thinking>`` (or
``<think>`` / ``<reasoning>``) inside ``content`` instead of a separate
``reasoning`` / ``reasoning_content`` field. OpenRouter also returns
``reasoning_details`` arrays. This module normalizes those into visible text
+ thinking text for the chat UI.
"""

from __future__ import annotations

import re

# Common inline CoT wrappers seen on OpenRouter / local reasoning models.
_INLINE_THINK_RE = re.compile(
    r"<(thinking|think|reasoning|thought)>(.*?)</\1>",
    re.IGNORECASE | re.DOTALL,
)
_OPEN_THINK_RE = re.compile(
    r"<(thinking|think|reasoning|thought)\b[^>]*>",
    re.IGNORECASE,
)
_CLOSE_THINK_RE = re.compile(
    r"</(thinking|think|reasoning|thought)\s*>",
    re.IGNORECASE,
)


def reasoning_details_text(details) -> str:
    """Flatten OpenRouter ``reasoning_details`` into plain text."""
    if not isinstance(details, list):
        return ""
    parts: list[str] = []
    for item in details:
        if not isinstance(item, dict):
            continue
        for key in ("text", "summary", "content", "reasoning"):
            val = item.get(key)
            if isinstance(val, str) and val.strip():
                parts.append(val)
                break
    return "".join(parts)


def message_reasoning_text(message: dict | None) -> str:
    """Best-effort reasoning string from an assistant message object."""
    if not isinstance(message, dict):
        return ""
    for key in ("reasoning_content", "reasoning"):
        val = message.get(key)
        if isinstance(val, str) and val.strip():
            return val
    details = reasoning_details_text(message.get("reasoning_details"))
    if details.strip():
        return details
    return ""


def delta_reasoning_text(delta: dict | None) -> str:
    """Reasoning fragment from a streaming delta (OpenRouter / DeepSeek / etc.)."""
    if not isinstance(delta, dict):
        return ""
    for key in ("reasoning_content", "reasoning"):
        val = delta.get(key)
        if isinstance(val, str) and val:
            return val
    return reasoning_details_text(delta.get("reasoning_details"))


def split_inline_thinking(text: str | None) -> tuple[str, str]:
    """Pull complete inline thinking tags out of assistant content.

    Returns ``(visible_content, thinking_text)``.
    """
    raw = text or ""
    if not raw:
        return "", ""
    chunks: list[str] = []

    def _collect(match: re.Match) -> str:
        body = (match.group(2) or "").strip()
        if body:
            chunks.append(body)
        return ""

    visible = _INLINE_THINK_RE.sub(_collect, raw)
    # Drop orphan open/close tags left behind by partial model output.
    visible = _OPEN_THINK_RE.sub("", visible)
    visible = _CLOSE_THINK_RE.sub("", visible)
    visible = re.sub(r"\n{3,}", "\n\n", visible).strip()
    thinking = "\n\n".join(chunks).strip()
    return visible, thinking


def merge_thinking(*parts: str | None) -> str:
    chunks = [str(p or "").strip() for p in parts if str(p or "").strip()]
    if not chunks:
        return ""
    # Deduplicate exact repeats (field + inline tag often duplicate).
    out: list[str] = []
    seen: set[str] = set()
    for c in chunks:
        key = c.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(c)
    return "\n\n".join(out)


class InlineThinkingStreamParser:
    """Stateful filter for streaming content that may contain thinking tags."""

    def __init__(self) -> None:
        self._buf = ""
        self._in_think = False
        self.thinking = ""
        self.visible = ""

    def feed(self, chunk: str) -> tuple[str, str]:
        """Feed a content delta; returns newly emitted ``(visible, thinking)``."""
        if not chunk:
            return "", ""
        self._buf += chunk
        vis_out = ""
        think_out = ""

        while self._buf:
            if self._in_think:
                close = _CLOSE_THINK_RE.search(self._buf)
                if not close:
                    # Hold a short tail in case the close tag is split.
                    keep = min(len(self._buf), 24)
                    emit, self._buf = self._buf[:-keep] if keep < len(self._buf) else ("", self._buf)
                    if not emit and len(self._buf) > 64:
                        # Unlikely incomplete tag — flush most of the buffer as thinking.
                        emit, self._buf = self._buf[:-16], self._buf[-16:]
                    if emit:
                        self.thinking += emit
                        think_out += emit
                    break
                body = self._buf[: close.start()]
                self.thinking += body
                think_out += body
                self._buf = self._buf[close.end() :]
                self._in_think = False
                continue

            open_m = _OPEN_THINK_RE.search(self._buf)
            if not open_m:
                # Hold trailing '<' so a split open tag is not leaked as text.
                lt = self._buf.rfind("<")
                if lt >= 0 and len(self._buf) - lt < 24:
                    emit, self._buf = self._buf[:lt], self._buf[lt:]
                else:
                    emit, self._buf = self._buf, ""
                if emit:
                    self.visible += emit
                    vis_out += emit
                break

            before = self._buf[: open_m.start()]
            if before:
                self.visible += before
                vis_out += before
            self._buf = self._buf[open_m.end() :]
            self._in_think = True

        return vis_out, think_out

    def flush(self) -> tuple[str, str]:
        """Flush any remainder (incomplete tags treated as visible)."""
        if not self._buf:
            return "", ""
        emit = self._buf
        self._buf = ""
        if self._in_think:
            self.thinking += emit
            return "", emit
        self.visible += emit
        return emit, ""
