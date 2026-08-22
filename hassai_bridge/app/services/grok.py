"""Grok (x.ai) reasoning, prompt cache, image generation, and request helpers."""

from __future__ import annotations

import base64
import re

from services import chat_media as cm
from services import deepseek as ds

THINKING_MODES = ds.THINKING_MODES
GROK_EFFORTS = ("low", "medium", "high", "xhigh")
_XHIGH_MODELS = re.compile(r"grok-4\.6|grok-4\.20-multi-agent", re.I)
# Only these families accept reasoning_effort / reasoningEffort (xAI docs).
# Dedicated reasoning builds (grok-4.20-*-reasoning) and grok-build reject it with HTTP 400.
_REASONING_EFFORT_MODELS = re.compile(
    r"^(grok-4\.6|grok-4\.5|grok-4\.20-multi-agent)(\b|$)",
    re.I,
)

# Official Imagine image models (https://docs.x.ai/developers/models)
IMAGE_MODELS = (
    "grok-imagine-image-2.0",
    "grok-imagine-image-quality",
    "grok-imagine-image",
)
DEFAULT_IMAGE_MODEL = "grok-imagine-image-2.0"


def is_grok_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "grok"


def normalize_thinking_mode(value: str | None, default: str = "auto") -> str:
    return ds.normalize_thinking_mode(value, default=default)


def supports_xhigh(model: str | None) -> bool:
    return bool(model and _XHIGH_MODELS.search(str(model)))


def supports_reasoning_effort(model: str | None) -> bool:
    """True when the chat Completions API accepts reasoning_effort for this model."""
    mid = str(model or "").strip()
    if not mid:
        return False
    # multi-agent is matched by the regex; bare grok-4.20 / *-reasoning / grok-build are not
    return bool(_REASONING_EFFORT_MODELS.search(mid))


def _grok_effort(mode: str, auto: dict, model: str) -> str:
    if mode == "off":
        return "low"
    if mode == "high":
        return "high"
    if mode == "max":
        return "xhigh" if supports_xhigh(model) else "high"
    if not auto.get("enabled"):
        return "low"
    effort = auto.get("effort")
    if effort == "max":
        return "xhigh" if supports_xhigh(model) else "high"
    if effort == "high":
        return "high"
    return "medium"


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    """Resolve Grok reasoning_effort for one chat request."""
    if not is_grok_provider(provider):
        return None

    default_mode = normalize_thinking_mode(provider.get("thinking_mode"))
    mode = normalize_thinking_mode(override, default=default_mode)
    model = str(provider.get("model") or "")
    auto = ds.auto_thinking_decision(user_text, tools_active=tools_active)
    effort = _grok_effort(mode, auto, model)

    return {
        "mode": mode,
        "enabled": True,
        "effort": effort,
        "auto_reason": auto.get("reason") if mode == "auto" else "",
    }


def apply_thinking_payload(payload: dict, thinking: dict | None, *, provider: dict | None = None, has_images: bool = False) -> None:
    model = ""
    if isinstance(provider, dict):
        model = str(provider.get("model") or payload.get("model") or "")
    elif isinstance(payload.get("model"), str):
        model = payload.get("model") or ""

    # Always drop params that conflict with Grok reasoning-style models
    payload.pop("temperature", None)
    payload.pop("presence_penalty", None)
    payload.pop("frequency_penalty", None)
    payload.pop("stop", None)

    if not supports_reasoning_effort(model):
        payload.pop("reasoning_effort", None)
        return

    if has_images:
        # Multimodal chat: keep reasoning low — high/xhigh + images can fail upstream.
        payload["reasoning_effort"] = "low"
        return
    if not thinking:
        payload.pop("reasoning_effort", None)
        return
    effort = thinking.get("effort") or "high"
    if effort not in GROK_EFFORTS:
        effort = "high"
    if effort == "xhigh" and not supports_xhigh(model):
        effort = "high"
    payload["reasoning_effort"] = effort


def assistant_turn(message: dict) -> dict:
    out = dict(message)
    if "reasoning_content" in message or out.get("tool_calls"):
        out["reasoning_content"] = message.get("reasoning_content") or ""
    return out


def cache_tokens_from_usage(usage: dict | None) -> tuple[int, int]:
    if not isinstance(usage, dict):
        return 0, 0
    prompt = int(usage.get("prompt_tokens") or 0)
    details = usage.get("prompt_tokens_details") or {}
    hit = int(details.get("cached_tokens") or 0)
    miss = max(0, prompt - hit) if prompt else 0
    return hit, miss


def log_cache_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not is_grok_provider(provider) or not isinstance(usage, dict):
        return
    hit, miss = cache_tokens_from_usage(usage)
    if hit or miss:
        log_prefix = f"[{user_id}] " if user_id else ""
        from logging import getLogger

        getLogger("hassai.providers").info(
            "%sGrok prompt cache: hit=%s miss=%s",
            log_prefix,
            hit,
            miss,
        )


def grok_conv_header(session_id: str | None) -> dict[str, str]:
    """Sticky routing header recommended by x.ai for prompt cache hits."""
    sid = str(session_id or "").strip()
    if not sid:
        return {}
    return {"x-grok-conv-id": sid[:128]}


def is_imagine_model(model: str | None) -> bool:
    return str(model or "").strip().lower().startswith("grok-imagine")


def is_chat_model(model: str | None) -> bool:
    """True for Grok language models (excludes Imagine / voice)."""
    mid = str(model or "").strip().lower()
    if not mid:
        return False
    if is_imagine_model(mid):
        return False
    if "voice" in mid or mid.startswith("grok-tts") or mid.startswith("grok-stt"):
        return False
    return True


def default_image_model(provider: dict | None) -> str:
    if isinstance(provider, dict):
        configured = str(provider.get("image_model") or "").strip()
        resolved = resolve_image_model(configured, fallback=DEFAULT_IMAGE_MODEL)
        if configured and resolved:
            return resolved
    return DEFAULT_IMAGE_MODEL


def resolve_image_model(requested: str | None, *, fallback: str | None = None) -> str:
    """Map LLM/tool/provider model ids to a valid Imagine image model.

    Models sometimes truncate enum values (e.g. grok-imagine-imag) or pass a
    chat model id — never send those to /v1/images/generations.
    """
    default = fallback or DEFAULT_IMAGE_MODEL
    if default not in IMAGE_MODELS:
        default = DEFAULT_IMAGE_MODEL
    raw = str(requested or "").strip()
    if not raw:
        return default
    lowered = raw.lower()
    for mid in IMAGE_MODELS:
        if lowered == mid.lower():
            return mid
    # Prefix match for truncated ids from tool calls
    matches = [mid for mid in IMAGE_MODELS if mid.lower().startswith(lowered)]
    if len(matches) == 1:
        return matches[0]
    if lowered.startswith("grok-imagine-image"):
        return default
    # Chat / video / unknown → ignore and use default
    return default


async def generate_image(
    provider: dict,
    prompt: str,
    *,
    model: str | None = None,
    n: int = 1,
    user_id: str = "",
    session_id: str | None = None,
) -> dict:
    """Generate images via x.ai /v1/images/generations.

    Returns {"text": str, "attachments": list[dict], "model": str}.
    """
    from logging import getLogger

    from services import provider_capabilities as pc
    from services import providers as prov
    from services.provider_errors import friendly_provider_error

    log = getLogger("hassai.providers")
    if not is_grok_provider(provider):
        raise ValueError("image generation requires a Grok provider")
    if not pc.supports_image_generation(provider):
        raise ValueError("image generation is not enabled for this provider")

    clean_prompt = " ".join(str(prompt or "").split())[:4000]
    if not clean_prompt:
        raise ValueError("empty image prompt")

    used_model = resolve_image_model(model, fallback=default_image_model(provider))
    count = max(1, min(4, int(n or 1)))

    url = prov._build_url(provider, "/v1/images/generations")
    headers = prov._build_headers(provider)
    payload = {
        "model": used_model,
        "prompt": clean_prompt,
        "n": count,
        "response_format": "url",
    }
    timeout = provider.get("timeout", 120)
    client = prov._get_client()
    resp = await client.post(url, json=payload, headers=headers, timeout=timeout)
    if resp.status_code >= 400:
        body = resp.text or ""
        log.error(
            "Grok image generation failed (%s) model=%s: %s",
            resp.status_code,
            used_model,
            body[:500],
        )
        raise ValueError(
            friendly_provider_error(
                resp.status_code,
                body,
                provider=provider,
                action="image generation",
            )
        )
    data = resp.json()

    attachments: list[dict] = []
    public_urls: list[str] = []
    for idx, item in enumerate(data.get("data") or []):
        if not isinstance(item, dict):
            continue
        raw: bytes | None = None
        mime = "image/png"
        if item.get("b64_json"):
            try:
                raw = base64.b64decode(str(item["b64_json"]), validate=True)
            except (ValueError, base64.binascii.Error):
                raw = None
        elif item.get("url"):
            image_url = str(item["url"]).strip()
            if image_url:
                try:
                    img_resp = await client.get(image_url, timeout=60)
                    img_resp.raise_for_status()
                    raw = img_resp.content
                    mime = str(img_resp.headers.get("content-type") or "image/png").split(";")[0].strip()
                except Exception as exc:
                    log.warning("Failed to download generated image %s: %s", idx + 1, exc)
                    public_urls.append(image_url)
                    continue
        if not raw:
            continue
        try:
            att = cm.persist_image_bytes(user_id, raw, mime, name=f"generated-{idx + 1}")
        except ValueError as exc:
            log.warning("Failed to persist generated image %s: %s", idx + 1, exc)
            continue
        attachments.append(att)
        public_urls.append(cm.attachment_public_url(att["id"], session_id or ""))

    if not attachments and not public_urls:
        raise ValueError("image generation returned no usable images")
    if not public_urls and attachments:
        for att in attachments:
            public_urls.append(cm.attachment_public_url(att["id"], session_id or ""))

    lines = [
        "[Generated image — show each image in your reply using markdown: ![description](url)]",
        f"Prompt: {clean_prompt}",
        f"Model: {used_model}",
    ]
    for i, image_url in enumerate(public_urls, start=1):
        lines.append(f"Image {i}: {image_url}")
    return {"text": "\n".join(lines), "attachments": attachments, "model": used_model}
