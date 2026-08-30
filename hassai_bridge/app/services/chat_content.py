"""Helpers for OpenAI-style multimodal chat message content."""

from __future__ import annotations

import json
import re
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
    """True if any *user* message includes image_url parts (vision input).

    Assistant attachments (Frigate snaps, generated images) must not count —
    replaying them as vision content breaks providers like DeepSeek Vision
    ("Image in assistant message is not supported").
    """
    for msg in messages or []:
        if msg.get("role") != "user":
            continue
        if has_images(msg.get("content")):
            return True
    return False


def current_turn_has_images(messages: list[dict] | None) -> bool:
    """True only if the latest user turn includes images.

    Older photos in the transcript must not keep routing follow-ups to a Vision
    LLM (that burned API spend after a single snap). Non-vision providers still
    strip historical images via prepare_messages_for_request.
    """
    for msg in reversed(messages or []):
        if msg.get("role") != "user":
            continue
        return has_images(msg.get("content"))
    return False


def strip_non_user_images(messages: list[dict] | None) -> list[dict]:
    """Drop image_url parts from assistant/tool/system messages before LLM calls."""
    out: list[dict] = []
    for msg in messages or []:
        role = msg.get("role") or "user"
        content = msg.get("content")
        if role == "user" or not has_images(content):
            out.append(msg)
            continue
        text = content_text(content)
        cleaned = dict(msg)
        cleaned["content"] = text if text else "(image shown in chat)"
        out.append(cleaned)
    return out


def strip_all_images(messages: list[dict] | None) -> list[dict]:
    """Drop every image_url part, including from user turns.

    Text-only models reject image parts left in the history rather than ignoring
    them — DashScope answers with "Unexpected item type in content" — so a
    conversation that once had a photo must be flattened before it is replayed
    to a provider without vision.
    """
    out: list[dict] = []
    for msg in messages or []:
        content = msg.get("content")
        if not has_images(content):
            out.append(msg)
            continue
        text = content_text(content)
        cleaned = dict(msg)
        cleaned["content"] = text if text else "(image shown in chat)"
        out.append(cleaned)
    return out


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


def build_multimodal_content(
    text: str,
    attachments: list[dict] | None,
    *,
    user_id: str,
    include_images: bool = True,
) -> str | list[dict]:
    parts: list[dict] = []
    clean = chat_media.strip_document_blocks((text or "").strip())
    if clean and clean != "(image)" and clean != "(document)":
        parts.append({"type": "text", "text": clean})
    doc_chunks: list[str] = []
    image_names: list[str] = []
    for att in attachments or []:
        kind = str(att.get("kind") or "")
        mime = str(att.get("mime") or "")
        is_doc = kind == "document" or (mime and not mime.startswith("image/"))
        if is_doc:
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
        if not include_images:
            name = str(att.get("name") or "photo").strip() or "photo"
            image_names.append(name)
            continue
        url = chat_media.attachment_data_url(user_id, att)
        if url:
            parts.append({"type": "image_url", "image_url": {"url": url, "detail": "auto"}})
    if doc_chunks:
        parts.append({"type": "text", "text": "\n\n".join(doc_chunks)})
    if image_names and not include_images:
        note = "Photos shown in chat: " + ", ".join(image_names[:12])
        if clean:
            # Merge into existing text part
            for part in parts:
                if part.get("type") == "text":
                    part["text"] = f"{part['text']}\n\n[{note}]"
                    break
            else:
                parts.append({"type": "text", "text": f"[{note}]"})
        else:
            parts.append({"type": "text", "text": f"[{note}]"})
    if not parts:
        return clean or ""
    if len(parts) == 1 and parts[0].get("type") == "text":
        # Keep markers for live LLM turns; stored display text is stripped separately.
        return str(parts[0]["text"])
    return parts


# History replays a "[Photos shown in chat: …]" note on assistant turns that
# carried a photo, so the model knows the picture was already displayed. Models
# copy the formatting they see, so the note comes back in fresh replies — strip
# it from anything the user reads. The closing bracket is optional because a
# half-written echo is just as visible.
_PHOTO_NOTE_RE = re.compile(r"[ \t]*\n{0,2}[ \t]*\[Photos shown in chat:[^\]\n]*\]?", re.I)


def strip_photo_notes(text: str) -> str:
    """Drop the photo replay marker if a model echoed it into its own reply."""
    if not text or "photos shown in chat" not in text.lower():
        return text
    return _PHOTO_NOTE_RE.sub("", text).strip()


def row_to_messages(row: dict, *, user_id: str, replay_tools: bool = True) -> list[dict]:
    """Expand one stored row into the turns the model should see.

    An assistant turn that used tools becomes three parts: the call, the result,
    and the sentence the user read. Replaying only the sentence taught weaker
    models the wrong lesson — they saw "user asks for an action, assistant says
    it is done" with no tool anywhere, and copied that on the next command,
    claiming success without touching anything.
    """
    base = row_to_message(row, user_id=user_id)
    calls = row.get("tool_calls") if isinstance(row.get("tool_calls"), list) else []
    if not replay_tools or base.get("role") != "assistant" or not calls:
        return [base]

    tool_calls = []
    results = []
    for call in calls:
        if not isinstance(call, dict):
            continue
        name = str(call.get("name") or "").strip()
        if not name:
            continue
        call_id = str(call.get("id") or "") or f"h{len(tool_calls)}"
        tool_calls.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": str(call.get("arguments") or "{}")},
        })
        results.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": name,
            "content": str(call.get("result") or "(no output recorded)"),
        })
    if not tool_calls:
        return [base]

    out: list[dict] = [{"role": "assistant", "content": "", "tool_calls": tool_calls}]
    out.extend(results)
    if content_text(base.get("content")):
        out.append(base)
    return out


def drop_orphan_tool_messages(messages: list[dict] | None) -> list[dict]:
    """Keep tool calls and their results together after trimming.

    A ``tool`` turn without the assistant call it answers is rejected outright —
    DashScope replies "messages with role 'tool' must be a response to a
    preceding message with 'tool_calls'" — and the reverse is just as bad.
    """
    known: set[str] = set()
    kept: list[dict] = []
    for msg in messages or []:
        role = msg.get("role")
        if role == "assistant" and msg.get("tool_calls"):
            known.update(str(tc.get("id") or "") for tc in msg["tool_calls"])
            kept.append(msg)
            continue
        if role == "tool":
            if str(msg.get("tool_call_id") or "") in known:
                kept.append(msg)
            continue
        kept.append(msg)

    answered = {str(m.get("tool_call_id") or "") for m in kept if m.get("role") == "tool"}
    out: list[dict] = []
    for msg in kept:
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            live = [tc for tc in msg["tool_calls"] if str(tc.get("id") or "") in answered]
            if live:
                msg = {**msg, "tool_calls": live}
            elif content_text(msg.get("content")):
                msg = {k: v for k, v in msg.items() if k != "tool_calls"}
            else:
                continue
        out.append(msg)
    return out


def row_to_message(row: dict, *, user_id: str) -> dict:
    role = str(row.get("role") or "user")
    attachments = row.get("attachments") if isinstance(row.get("attachments"), list) else []
    # Assistant/tool photos (Frigate, Imagine) are UI-only — never vision inputs.
    include_images = role == "user"
    content = build_multimodal_content(
        row.get("content") or "",
        attachments,
        user_id=user_id,
        include_images=include_images,
    )
    msg: dict = {"role": role, "content": content}
    # DeepSeek thinking + tools: prior assistant CoT must be replayed.
    reasoning = row.get("reasoning_content")
    if reasoning and role == "assistant":
        msg["reasoning_content"] = str(reasoning)
    return msg


def _reasoning_key(text: str) -> str:
    return " ".join((text or "").split())[:400]


def backfill_reasoning(messages: list[dict], history_rows: list[dict] | None) -> list[dict]:
    """Attach stored CoT to client-sent assistant turns.

    Web/Assist clients replay the transcript without ``reasoning_content``, so
    the DB copy is the only source. DeepSeek needs it back on every assistant
    turn once a request carries tools.
    """
    lookup: dict[str, str] = {}
    for row in history_rows or []:
        if str(row.get("role") or "") != "assistant":
            continue
        reasoning = row.get("reasoning_content")
        if not reasoning:
            continue
        key = _reasoning_key(content_text(row.get("content")))
        if key:
            lookup[key] = str(reasoning)
    if not lookup:
        return messages

    out: list[dict] = []
    for msg in messages:
        if (
            not isinstance(msg, dict)
            or msg.get("role") != "assistant"
            or msg.get("reasoning_content")
        ):
            out.append(msg)
            continue
        stored = lookup.get(_reasoning_key(content_text(msg.get("content"))))
        if not stored:
            out.append(msg)
            continue
        row = dict(msg)
        row["reasoning_content"] = stored
        out.append(row)
    return out


def public_attachments(attachments: list[dict] | None, session_id: str = "") -> list[dict]:
    out: list[dict] = []
    for att in attachments or []:
        att_id = str(att.get("id") or "").strip()
        if not att_id:
            continue
        kind = str(att.get("kind") or "")
        mime = str(att.get("mime") or "image/jpeg")
        if not kind:
            if mime.startswith("image/"):
                kind = "image"
            elif mime.startswith("audio/"):
                kind = "audio"
            else:
                kind = "document"
        out.append({
            "id": att_id,
            "mime": mime,
            "name": att.get("name") or "",
            "kind": kind,
            "url": chat_media.attachment_public_url(att_id, session_id),
        })
    return out
