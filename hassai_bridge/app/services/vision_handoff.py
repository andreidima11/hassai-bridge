"""Hand photo understanding from a Vision LLM to a text-only follow-up model.

On a photo turn the Vision provider answers the user and also emits a dense
`<<<photo_context>>>` block (stripped from the UI). Later text turns inject that
context so the primary model still “remembers” the image without seeing pixels
or staying on the expensive Vision provider.
"""

from __future__ import annotations

import re
from typing import Any

_OPEN = "<<<photo_context>>>"
_CLOSE = "<<<end_photo_context>>>"
_BLOCK_RE = re.compile(
    re.escape(_OPEN) + r"(.*?)" + re.escape(_CLOSE),
    re.I | re.S,
)
# Unclosed block at the end (model ran out of tokens / stream cut).
_OPEN_TAIL_RE = re.compile(re.escape(_OPEN) + r"(.*)\Z", re.I | re.S)


def handoff_instruction(lang: str = "en") -> str:
    if (lang or "").startswith("ro"):
        body = (
            "Poți vedea imaginea/imaginile atașate. Răspunde utilizatorului normal, "
            "în limba lui. După răspuns, adaugă neapărat un bloc mașină (utilizatorul "
            "nu trebuie să-l vadă) cu o descriere densă, factuală a imaginii — obiecte, "
            "text vizibil, culori, persoane, layout, detalii utile pentru întrebări "
            "ulterioare — ca un alt asistent text-only să poată continua conversația "
            "fără poză:\n"
            f"{_OPEN}\n"
            "…descriere densă…\n"
            f"{_CLOSE}"
        )
    else:
        body = (
            "You can see the attached image(s). Answer the user normally in their "
            "language. After your answer you MUST append a machine-only block "
            "(the user must not see it) with a dense factual description of the "
            "image — objects, visible text, colors, people, layout, details useful "
            "for follow-up questions — so a text-only assistant can continue this "
            "chat without the photo:\n"
            f"{_OPEN}\n"
            "…dense description…\n"
            f"{_CLOSE}"
        )
    return "[Vision handoff]\n" + body


def split_photo_context(text: str | None) -> tuple[str, str]:
    """Return (user_visible_text, photo_context)."""
    raw = text if isinstance(text, str) else ""
    if not raw:
        return "", ""
    if _OPEN.lower() not in raw.lower():
        return raw, ""
    ctx_parts: list[str] = []
    visible = raw
    for match in _BLOCK_RE.finditer(raw):
        piece = (match.group(1) or "").strip()
        if piece:
            ctx_parts.append(piece)
    visible = _BLOCK_RE.sub("", visible)
    # Drop an unclosed trailer so it never lands in the chat bubble.
    tail = _OPEN_TAIL_RE.search(visible)
    if tail:
        piece = (tail.group(1) or "").strip()
        if piece:
            ctx_parts.append(piece)
        visible = visible[: tail.start()]
    visible = visible.strip()
    ctx = "\n\n".join(ctx_parts).strip()
    return visible, ctx


def fallback_photo_context(visible_reply: str, *, limit: int = 1200) -> str:
    """If the model forgot the block, reuse a trimmed copy of the answer."""
    text = (visible_reply or "").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def collect_photo_contexts(rows: list[dict] | None, *, limit: int = 3) -> list[str]:
    """Newest-last photo contexts from stored history rows (max `limit`)."""
    found: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        ctx = str(row.get("photo_context") or "").strip()
        if ctx:
            found.append(ctx)
    if not found:
        return []
    return found[-limit:]


def format_photo_context_block(contexts: list[str], *, lang: str = "en") -> str:
    parts = [c.strip() for c in contexts if c and str(c).strip()]
    if not parts:
        return ""
    if (lang or "").startswith("ro"):
        header = (
            "[Context foto din conversație — nu poți vedea imaginile; "
            "folosește doar aceste note]"
        )
    else:
        header = (
            "[Photo context from earlier in this chat — you cannot see the images; "
            "rely on these notes]"
        )
    body = "\n\n---\n\n".join(parts)
    return f"{header}\n\n{body}"


class PhotoContextStreamFilter:
    """Hide `<<<photo_context>>>…<<<end_photo_context>>>` while streaming."""

    def __init__(self) -> None:
        self.visible = ""
        self.context = ""
        self._raw = ""
        self._in_block = False
        self._hold = ""

    def feed(self, chunk: str) -> str:
        """Accumulate raw text; return only newly visible characters to show."""
        if not chunk:
            return ""
        self._raw += chunk
        data = self._hold + chunk
        self._hold = ""
        out = []
        i = 0
        while i < len(data):
            if not self._in_block:
                lower = data.lower()
                open_at = lower.find(_OPEN.lower(), i)
                if open_at < 0:
                    # Maybe a partial open marker at the end — hold the tail.
                    tail = data[i:]
                    keep = _partial_suffix(tail, _OPEN)
                    if keep:
                        out.append(tail[:-keep])
                        self._hold = tail[-keep:]
                    else:
                        out.append(tail)
                    break
                out.append(data[i:open_at])
                self._in_block = True
                i = open_at + len(_OPEN)
                continue
            lower = data.lower()
            close_at = lower.find(_CLOSE.lower(), i)
            if close_at < 0:
                tail = data[i:]
                keep = _partial_suffix(tail, _CLOSE)
                if keep:
                    self.context += tail[:-keep]
                    self._hold = tail[-keep:]
                else:
                    self.context += tail
                break
            self.context += data[i:close_at]
            self._in_block = False
            i = close_at + len(_CLOSE)
        visible_chunk = "".join(out)
        self.visible += visible_chunk
        return visible_chunk

    def finish(self) -> tuple[str, str]:
        """Flush hold buffer and return (visible, context)."""
        if self._hold:
            if self._in_block:
                self.context += self._hold
            else:
                # Unclosed open marker held back — treat remainder as context start.
                held = self._hold
                self._hold = ""
                if _OPEN.lower() in held.lower() or _partial_suffix(held, _OPEN):
                    self._in_block = True
                    # Drop partial/full open from visible path
                    idx = held.lower().find(_OPEN.lower())
                    if idx >= 0:
                        self.visible += held[:idx]
                        self.context += held[idx + len(_OPEN) :]
                    else:
                        self.context += held
                else:
                    self.visible += held
            self._hold = ""
        visible, ctx = split_photo_context(self._raw)
        # Prefer regex split on full raw (handles odd casing); fall back to incremental.
        if ctx:
            return visible, ctx.strip()
        return self.visible.strip(), self.context.strip()


def _partial_suffix(text: str, marker: str) -> int:
    """How many trailing chars of `text` could be the start of `marker`."""
    if not text:
        return 0
    max_k = min(len(text), len(marker) - 1)
    lower_t = text.lower()
    lower_m = marker.lower()
    for k in range(max_k, 0, -1):
        if lower_m.startswith(lower_t[-k:]):
            return k
    return 0


def finalize_reply(text: str | None) -> tuple[str, str]:
    """Visible reply + photo_context (with answer fallback if block missing)."""
    visible, ctx = split_photo_context(text)
    if not ctx:
        ctx = fallback_photo_context(visible)
    return visible, ctx
