"""Server-side LLM pack router for Dynamic toolkits.

Replaces regex hot-path priming: one short JSON completion picks eligible packs
before the main chat turn. Failures / low confidence → empty packs (lean core).
"""

from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("hassai.pack_router")

CONFIDENCE_FLOOR = 0.4
MAX_TOKENS = 120
_JSON_RE = re.compile(r"\{[\s\S]*\}")
_EMPTY_USAGE = {"prompt": 0, "completion": 0, "total": 0}


def is_trivial_message(user_text: str) -> bool:
    text = " ".join(str(user_text or "").split())
    return len(text) <= 2


def build_router_messages(user_text: str, eligible: dict[str, str]) -> list[dict]:
    catalog = "\n".join(f"- {pid}: {desc}" for pid, desc in sorted(eligible.items()))
    if not catalog:
        catalog = "(none)"
    system = (
        "You route Home Assistant / HASSAI tool packs for one user message. "
        "Reply with ONLY compact JSON: "
        '{"packs":["id",...],"confidence":0.0}. '
        "packs must be a subset of the catalog ids. "
        "Use [] when the user only chats / needs no domain tools. "
        "confidence is 0..1 how sure you are."
    )
    user = (
        f"Catalog:\n{catalog}\n\n"
        f"User message:\n{(user_text or '').strip()[:2000]}\n\n"
        "JSON:"
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def parse_router_response(raw: str, eligible: dict[str, str]) -> dict:
    """Parse model output into {packs: set[str], confidence: float, reason: str}."""
    eligible_ids = set(eligible or ())
    text = (raw or "").strip()
    if not text:
        return {"packs": set(), "confidence": 0.0, "reason": "empty"}
    match = _JSON_RE.search(text)
    blob = match.group(0) if match else text
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return {"packs": set(), "confidence": 0.0, "reason": "bad_json"}
    if not isinstance(data, dict):
        return {"packs": set(), "confidence": 0.0, "reason": "not_object"}

    raw_packs = data.get("packs") if isinstance(data.get("packs"), list) else []
    packs = {str(p).strip() for p in raw_packs if str(p).strip() in eligible_ids}
    try:
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    if confidence < CONFIDENCE_FLOOR:
        return {
            "packs": set(),
            "confidence": confidence,
            "reason": "low_confidence",
            "raw_packs": sorted(packs),
        }
    return {"packs": packs, "confidence": confidence, "reason": "ok"}


def _message_text(result: dict) -> str:
    try:
        msg = (result.get("choices") or [{}])[0].get("message") or {}
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for p in content:
                if isinstance(p, dict) and p.get("type") == "text":
                    parts.append(str(p.get("text") or ""))
                elif isinstance(p, str):
                    parts.append(p)
            return "".join(parts)
    except Exception:
        pass
    return ""


def _usage_from_result(result: dict | None) -> dict:
    usage = (result or {}).get("usage") if isinstance(result, dict) else None
    if not isinstance(usage, dict):
        return dict(_EMPTY_USAGE)
    try:
        prompt = int(usage.get("prompt_tokens") or 0)
    except (TypeError, ValueError):
        prompt = 0
    try:
        completion = int(usage.get("completion_tokens") or 0)
    except (TypeError, ValueError):
        completion = 0
    try:
        total = int(usage.get("total_tokens") or (prompt + completion))
    except (TypeError, ValueError):
        total = prompt + completion
    return {
        "prompt": max(0, prompt),
        "completion": max(0, completion),
        "total": max(0, total),
    }


def _empty_decision(*, reason: str, confidence: float = 0.0) -> dict:
    return {
        "packs": set(),
        "confidence": confidence,
        "reason": reason,
        "usage": dict(_EMPTY_USAGE),
    }


async def route_packs(
    user_text: str,
    eligible: dict[str, str],
    *,
    provider: dict | None,
    model: str | None = None,
) -> dict:
    """Return {packs, confidence, reason, usage}. Never raises to the chat path."""
    if not eligible:
        return _empty_decision(reason="no_eligible", confidence=1.0)
    if is_trivial_message(user_text):
        return _empty_decision(reason="trivial", confidence=1.0)

    from services import providers

    messages = build_router_messages(user_text, eligible)
    try:
        # Prefer a short timeout for the router so chat isn't blocked long.
        router_provider = dict(provider or {}) if provider else None
        if router_provider is not None:
            try:
                t = float(router_provider.get("timeout") or 120)
            except (TypeError, ValueError):
                t = 120.0
            router_provider["timeout"] = min(t, 20.0)
            # Force deterministic routing.
            router_provider["temperature"] = 0

        result = await providers.chat_completion(
            messages,
            model=model,
            stream=False,
            tools=None,
            provider=router_provider,
            thinking={"mode": "off"} if router_provider else None,
            max_tokens=MAX_TOKENS,
        )
        raw = _message_text(result if isinstance(result, dict) else {})
        parsed = parse_router_response(raw, eligible)
        parsed["usage"] = _usage_from_result(result if isinstance(result, dict) else {})
        log.info(
            "Pack router → packs=%s confidence=%.2f reason=%s usage=%s",
            sorted(parsed.get("packs") or ()),
            float(parsed.get("confidence") or 0),
            parsed.get("reason"),
            parsed["usage"],
        )
        return parsed
    except Exception as e:
        log.warning("Pack router failed: %s", e)
        return _empty_decision(reason=f"error:{type(e).__name__}")
