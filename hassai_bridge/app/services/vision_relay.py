"""Vision relay: small VL model describes images; main model answers."""

from __future__ import annotations

from services import chat_content as cc

VISION_MODES = ("direct", "relay")

_VISION_RELAY_SYSTEM = (
    "You analyze images for another AI assistant. Describe only what you see: "
    "objects, visible text, colors, layout, numbers, and labels. Be factual and concise. "
    "Do not answer the user's question — only provide visual observations."
)


def normalize_vision_mode(value: str | None, default: str = "direct") -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in VISION_MODES else default


def last_user_image_message(messages: list[dict]) -> tuple[str, list | str | None]:
    """Return (user text, multimodal content) for the latest user turn with images."""
    for msg in reversed(messages or []):
        if msg.get("role") != "user":
            continue
        content = msg.get("content")
        if cc.has_images(content):
            return cc.content_text(content), content
    return "", None


def inject_vision_analysis(content, analysis: str) -> str:
    text = cc.content_text(content)
    analysis = (analysis or "").strip()
    if not analysis:
        return text or "[image]"
    if text and text not in ("(image)",):
        return f"{text}\n\n[Vision analysis]\n{analysis}".strip()
    return f"[Vision analysis]\n{analysis}".strip()


def apply_vision_relay(messages: list[dict], analysis: str) -> list[dict]:
    """Replace image attachments with text analysis in user messages."""
    out: list[dict] = []
    for msg in messages:
        row = dict(msg)
        if row.get("role") == "user" and cc.has_images(row.get("content")):
            row["content"] = inject_vision_analysis(row.get("content"), analysis)
        out.append(row)
    return out


def build_relay_vision_messages(*, user_text: str, image_content) -> list[dict]:
    parts: list[dict] = [{
        "type": "text",
        "text": (
            "Describe everything visible in the attached image(s) for another assistant. "
            "Include readable text verbatim when possible. Do not answer any question — "
            "observations only."
        ),
    }]
    if user_text.strip() and user_text.strip() != "(image)":
        parts.append({"type": "text", "text": f"User message (for context only, do not answer): {user_text.strip()}"})
    if isinstance(image_content, list):
        for part in image_content:
            if isinstance(part, dict) and part.get("type") == "image_url":
                parts.append(part)
    return [
        {"role": "system", "content": _VISION_RELAY_SYSTEM},
        {"role": "user", "content": parts},
    ]
