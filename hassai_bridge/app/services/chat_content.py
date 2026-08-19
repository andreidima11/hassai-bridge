"""Helpers for OpenAI-style multimodal chat message content."""

from __future__ import annotations

import json
from typing import Any

from services import chat_media


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return str(content).strip()


def has_images(content: Any) -> bool:
    if not isinstance(content, list):
        return False
    return any(isinstance(part, dict) and part.get("type") == "image_url" for part in content)


def content_size(content: Any) -> int:
    if isinstance(content, str):
        return len(content)
    if isinstance(content, list):
        return len(json.dumps(content, ensure_ascii=False))
    if content is None:
        return 0
    return len(str(content))


def estimate_tokens(content: Any) -> int:
    text = content_text(content)
    words = text.split()
    if not words and has_images(content):
        return 512 * max(1, sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url"))
    if not words:
        return 1
    non_ascii_ratio = sum(1 for c in text if ord(c) > 127) / max(len(text), 1)
    multiplier = 1.5 if non_ascii_ratio > 0.1 else 1.3
    tokens = max(1, int(len(words) * multiplier))
    if isinstance(content, list):
        tokens += 512 * sum(1 for p in content if isinstance(p, dict) and p.get("type") == "image_url")
    return tokens


def message_has_payload(message: dict) -> bool:
    if message.get("tool_calls"):
        return True
    content = message.get("content")
    if isinstance(content, list):
        return bool(content_text(content)) or has_images(content)
    return bool(content_text(content))


def summary_snippet(content: Any, limit: int = 80) -> str:
    text = content_text(content)
    if text:
        return text[:limit].replace("\n", " ").strip()
    if has_images(content):
        return "[image]"
    return ""


def build_multimodal_content(text: str, attachments: list[dict] | None, *, user_id: str) -> str | list[dict]:
    parts: list[dict] = []
    clean = (text or "").strip()
    if clean and clean != "(image)":
        parts.append({"type": "text", "text": clean})
    for att in attachments or []:
        url = chat_media.attachment_data_url(user_id, att)
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
    if not parts:
        return clean or ""
    if len(parts) == 1 and parts[0].get("type") == "text":
        return str(parts[0]["text"])
    return parts


def row_to_message(row: dict, *, user_id: str) -> dict:
    attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
    content = build_multimodal_content(row.get("content") or "", attachments, user_id=user_id)
    return {"role": row.get("role") or "user", "content": content}


def public_attachments(attachments: list[dict] | None, session_id: str = "") -> list[dict]:
    out: list[dict] = []
    for att in attachments or []:
        att_id = str(att.get("id") or "").strip()
        if not att_id:
            continue
        out.append({
            "id": att_id,
            "mime": att.get("mime") or "image/jpeg",
            "name": att.get("name") or "",
            "url": chat_media.attachment_public_url(att_id, session_id),
        })
    return out
