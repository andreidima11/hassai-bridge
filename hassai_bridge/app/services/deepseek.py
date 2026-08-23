"""DeepSeek-specific thinking mode and request helpers."""

from __future__ import annotations

import re

THINKING_MODES = ("auto", "off", "high", "max")

_SIMPLE_RE = re.compile(
    r"^\s*(?:"
    r"salut|bun[aă]|hello|hi|hey|ce faci|what(?:'s| are) you doing|how are you|"
    r"mulțumesc|multumesc|mersi|thanks|thank you|ok|okay|da|nu|yes|no|"
    r"👋|🙂"
    r")\b[\s!?.,]*$",
    re.I,
)

_PLANNING_RE = re.compile(
    r"\b(?:"
    r"plan(?:u(?:im|l|a)?|ning)?|arhitect|architect|design|analiz|analyze|analyse|"
    r"compare|compar|implement|refactor|debug|troubleshoot|strateg|optimiz|"
    r"explain|explic[aă]|step[\s-]by[\s-]step|pas cu pas|cum constru|how to build|"
    r"how should we|hai sa planu|let'?s plan|scheme|structur|architectur|"
    r"pro(?:iect|ject)|roadmap|trade[\s-]off|decide|evaluat"
    r")\b",
    re.I,
)

_MAX_RE = re.compile(
    r"\b(?:"
    r"from scratch|de la zero|entire system|complete architecture|full refactor|"
    r"production[\s-]ready|comprehensive|g(?:â|a)nde(?:ș|s)te mult|think hard|"
    r"maximum effort|effort max"
    r")\b",
    re.I,
)

# Home / device / camera / add-on control. Short commands like "aprinde lumina"
# must not fall through to thinking=off — weaker DeepSeek models then skip tools
# and invent that they flipped the switch.
_CONTROL_RE = re.compile(
    r"(?:"
    # English verbs / intents
    r"\b(?:turn|switch|toggle|set|dim|brighten|open|close|lock|unlock|arm|disarm|"
    r"start|stop|pause|resume|run|trigger|activate|deactivate|enable|disable|"
    r"call|invoke|reboot|restart|reload|update|install|create|delete|remove|"
    r"add|rename|move|assign|expose|hide|play|mute|unmute|volume|"
    r"remember|forget|memorize)\b"
    r"|"
    # Romanian verbs / intents (diacritics optional)
    r"\b(?:aprinde|stinge|porne[sș]te|pornit[ie]?|opre[sș]te|oprit[ie]?|"
    r"deschide|închide|inchide|încuie|incuie|descuie|"
    r"seteaz[aă]|schimb[aă]|ajusteaz[aă]|cre[sș]te|scade|"
    r"activeaz[aă]|dezactiveaz[aă]|ruleaz[aă]|declan[sș]eaz[aă]|"
    r"reîncarc[aă]|reincarc[aă]|reporne[sș]te|actualizeaz[aă]|"
    r"creeaz[aă]|[sș]terge|sterge|adaug[aă]|redenume[sș]te|"
    r"memoreaz[aă]|memoreaza|re[tț]ine|retine|[tț]ine[\s-]minte|tine[\s-]minte|uit[aă])\b"
    r"|"
    # Nouns that almost always mean "do something with HA / cameras / the add-on"
    r"\b(?:light|lights|lamp|switch|switches|thermostat|climate|cover|blinds|"
    r"shutter|lock|scene|script|automation|entity|entities|dashboard|lovelace|"
    r"camera|cameras|frigate|snapshot|snap|detection|backup|add-?on|addon|"
    r"lumin[aăi]|lumini|bec(?:ul|uri)?|lamp[aă]|întrerup[aă]tor|intrerupator|"
    r"termostat|climatizare|jaluzele|rulou|u[sș][aă]|poart[aă]|yal[aă]|"
    r"scen[aă]|script|automatiza(?:re|rii)|entitat(?:e|i)|dashboard|"
    r"camer[aă]|camere|detec[tț]ie|backup|add-?on)\b"
    r"|"
    # Phrases that ask the model to act on HA / itself without a strong verb
    r"(?:ce (?:e|este) (?:pe|în|in) (?:camer|afara|afar[aă])|"
    r"what(?:'?s| is) (?:on|at) (?:the )?(?:camera|front|door|driveway)|"
    r"ultim(?:ul|a) (?:snap|snapshot|detec)|"
    r"last (?:snap|snapshot|detection)|"
    r"home assistant|hassai|has ?ai)\b"
    r")",
    re.I,
)


def is_deepseek_provider(provider: dict | None) -> bool:
    return isinstance(provider, dict) and provider.get("type") == "deepseek"


def normalize_thinking_mode(value: str | None, default: str = "auto") -> str:
    mode = str(value or default).strip().lower()
    return mode if mode in THINKING_MODES else default


def auto_thinking_decision(user_text: str, *, tools_active: bool = False) -> dict:
    """Heuristic: simple chat off, planning / HA control on.

    Short control phrases ("aprinde lumina", "turn on the lights") used to fall
    into the ``simple`` / ``default_off`` buckets and leave thinking disabled.
    Weaker DeepSeek models then skip tool calls and invent that they acted.
    """
    text = (user_text or "").strip()
    compact = re.sub(r"\s+", " ", text)
    lower = compact.lower()

    if not compact:
        return {"enabled": False, "effort": None, "reason": "empty"}

    if _MAX_RE.search(lower) or (len(_PLANNING_RE.findall(lower)) >= 2 and len(compact) > 120):
        return {"enabled": True, "effort": "max", "reason": "complex"}

    # Pure greetings/acks stay cheap — even if HA tools are loaded on every request.
    if _SIMPLE_RE.match(compact):
        return {"enabled": False, "effort": None, "reason": "simple"}

    # Device / HA / camera / memory intents need thinking so the model actually
    # calls tools instead of narrating a fake action. Check before the short-message
    # off path, otherwise "aprinde lumina" (14 chars) never gets here.
    if tools_active and _CONTROL_RE.search(lower):
        return {"enabled": True, "effort": "high", "reason": "control"}

    if len(compact) < 28 and not _PLANNING_RE.search(lower):
        return {"enabled": False, "effort": None, "reason": "simple"}

    if _PLANNING_RE.search(lower):
        return {"enabled": True, "effort": "high", "reason": "planning"}

    if tools_active and len(compact) > 80:
        return {"enabled": True, "effort": "high", "reason": "tools"}

    if len(compact) > 220:
        return {"enabled": True, "effort": "high", "reason": "long"}

    return {"enabled": False, "effort": None, "reason": "default_off"}


def resolve_thinking(
    provider: dict,
    *,
    override: str | None = None,
    user_text: str = "",
    tools_active: bool = False,
) -> dict | None:
    """Resolve DeepSeek thinking for one chat request. None if not DeepSeek."""
    if not is_deepseek_provider(provider):
        return None

    default_mode = normalize_thinking_mode(
        provider.get("thinking_mode") or provider.get("deepseek_thinking"),
    )
    mode = normalize_thinking_mode(override, default=default_mode)

    if mode == "off":
        return {"mode": "off", "enabled": False, "effort": None, "auto_reason": ""}

    if mode == "high":
        return {"mode": "high", "enabled": True, "effort": "high", "auto_reason": ""}

    if mode == "max":
        return {"mode": "max", "enabled": True, "effort": "max", "auto_reason": ""}

    auto = auto_thinking_decision(user_text, tools_active=tools_active)
    return {
        "mode": "auto",
        "enabled": auto["enabled"],
        "effort": auto["effort"],
        "auto_reason": auto["reason"],
    }


def apply_thinking_payload(payload: dict, thinking: dict | None) -> None:
    if not thinking:
        return
    if thinking.get("enabled"):
        payload["thinking"] = {"type": "enabled"}
        effort = thinking.get("effort") or "high"
        payload["reasoning_effort"] = effort
    else:
        payload["thinking"] = {"type": "disabled"}


def assistant_turn(message: dict) -> dict:
    """Preserve reasoning_content for DeepSeek tool / multi-turn loops.

    When the message includes tool_calls (or already has reasoning), always
    keep the ``reasoning_content`` key — DeepSeek returns HTTP 400 if it is
    omitted after thinking-mode tool turns.
    """
    out = dict(message)
    if "reasoning_content" in message or out.get("tool_calls"):
        out["reasoning_content"] = message.get("reasoning_content") or ""
    return out


def prepare_messages_for_tools(messages: list[dict] | None) -> list[dict]:
    """Ensure every assistant message carries reasoning_content when tools are used.

    DeepSeek docs (Thinking Mode → Tool Calls): when a request carries ``tools``,
    the reasoning_content of every intermediate assistant turn must be passed
    back — including turns that did not call a tool. Missing field → HTTP 400.
    Assistant turns with no recorded CoT use an empty string.
    """
    out: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, dict):
            out.append(msg)
            continue
        if msg.get("role") != "assistant":
            out.append(msg)
            continue
        row = dict(msg)
        reasoning = row.get("reasoning_content")
        row["reasoning_content"] = str(reasoning) if reasoning else ""
        out.append(row)
    return out


def strip_reasoning(messages: list[dict] | None) -> list[dict]:
    """Drop reasoning_content everywhere (fallback when pass-back is rejected)."""
    out: list[dict] = []
    for msg in messages or []:
        if not isinstance(msg, dict) or "reasoning_content" not in msg:
            out.append(msg)
            continue
        row = dict(msg)
        row.pop("reasoning_content", None)
        out.append(row)
    return out


def is_reasoning_passback_error(status_code: int, body: str | None) -> bool:
    """True for DeepSeek's 'reasoning_content must be passed back' HTTP 400."""
    if status_code != 400:
        return False
    text = (body or "").lower()
    return "reasoning_content" in text and (
        "passed back" in text or "thinking mode" in text
    )


def log_cache_usage(provider: dict | None, usage: dict | None, *, user_id: str = "") -> None:
    if not is_deepseek_provider(provider) or not isinstance(usage, dict):
        return
    hit = int(usage.get("prompt_cache_hit_tokens") or 0)
    miss = int(usage.get("prompt_cache_miss_tokens") or 0)
    if hit or miss:
        log_prefix = f"[{user_id}] " if user_id else ""
        from logging import getLogger

        getLogger("hassai.providers").info(
            "%sDeepSeek KV cache: hit=%s miss=%s",
            log_prefix,
            hit,
            miss,
        )
