"""Helpers for OpenAI-style multimodal chat message content."""

from __future__ import annotations

import json
from typing import Any

from services import chat_media


def content_text(content: Any) -> str:
    if isinstance(content, str):
        return chat_media.strip_document_blocks(content.strip())
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text = chat_media.strip_document_blocks(str(part.get("text") or "").strip())
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
    if content is None:
        return ""
    return chat_media.strip_document_blocks(str(content).strip())


def content_text_for_llm(content: Any) -> str:
    """Like content_text but keeps document bodies (for prompt size estimates)."""
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


def messages_have_images(messages: list[dict] | None) -> bool:
    for msg in messages or []:
        if has_images(msg.get("content")):
            return True
    return False


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
        return (
            bool(content_text(content))
            or has_images(content)
            or bool(chat_media.parse_document_refs_from_content(content))
        )
    if bool(content_text(content)):
        return True
    return bool(chat_media.parse_document_refs_from_content(content))


def summary_snippet(content: Any, limit: int = 80) -> str:
    text = content_text(content)
    if text:
        return text[:limit].replace("\n", " ").strip()
    if has_images(content):
        return "[image]"
    if chat_media.parse_document_refs_from_content(content):
        return "[document]"
    return ""


def build_multimodal_content(text: str, attachments: list[dict] | None, *, user_id: str) -> str | list[dict]:
    parts: list[dict] = []
    clean = chat_media.strip_document_blocks((text or "").strip())
    if clean and clean != "(image)" and clean != "(document)":
        parts.append({"type": "text", "text": clean})
    doc_chunks: list[str] = []
    for att in attachments or []:
        kind = str(att.get("kind") or "")
        mime = str(att.get("mime") or "")
        if kind == "document" or (mime and not mime.startswith("image/")):
            extracted = chat_media.read_extracted_text(user_id, att) or ""
            if not extracted:
                continue
            doc_chunks.append(
                chat_media.format_document_block(
                    att_id=str(att.get("id") or ""),
                    name=str(att.get("name") or "document"),
                    mime=mime or "text/plain",
                    text=extracted,
                )
            )
            continue
        url = chat_media.attachment_data_url(user_id, att)
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
    if doc_chunks:
        parts.append({"type": "text", "text": "\n\n".join(doc_chunks)})
    if not parts:
        return clean or ""
    if len(parts) == 1 and parts[0].get("type") == "text":
        # Keep markers for live LLM turns; stored display text is stripped separately.
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
        kind = str(att.get("kind") or "")
        mime = str(att.get("mime") or "image/jpeg")
        if not kind:
            kind = "document" if not mime.startswith("image/") else "image"
        out.append({
            "id": att_id,
            "mime": mime,
            "name": att.get("name") or "",
            "kind": kind,
            "url": chat_media.attachment_public_url(att_id, session_id),
        })
    return out
