"""Live tool playbook — tell the model what it can do *this turn*.

Built only from tools present in the current request so Dynamic / Auto subsets
stay honest. Prefer short routing rules over dumping the full catalog again.
"""

from __future__ import annotations

import re
from typing import Iterable

# Cause / actor questions → need entities (+ automations for traces).
_EXPLAIN_EVENT_RE = re.compile(
    r"(?:"
    r"\b(?:de\s+ce|why|who|cine|ce\s+a)\b.{0,40}\b(?:aprins|stins|pornit|oprit|schimb|"
    r"turn(?:ed)?\s*on|turn(?:ed)?\s*off|changed|triggered)\b|"
    r"\b(?:who|cine)\s+(?:turned|changed|triggered|aprins|stins)\b|"
    r"\b(?:explain|explic[aă]).{0,30}\b(?:why|de\s+ce|change|schimb|aprind)\b|"
    r"\bha_explain_event\b|"
    r"\b(?:cause|cauz[aă]|actor|context\.id)\b"
    r")",
    re.I | re.S,
)

# Ordered rules: (tool_name, playbook line). First matching tools win order.
_PLAYBOOK_RULES: tuple[tuple[str, str], ...] = (
    (
        "ha_explain_event",
        "Why / who / de ce s-a aprins|stins|schimbat X → call ha_explain_event first "
        "(history+logbook+traces). Never invent a wall switch or user press without evidence; "
        "if confidence is unknown, say you cannot determine the cause.",
    ),
    (
        "ha_get_logs",
        "Add-on / Zigbee2MQTT / Core logs → ha_get_logs "
        "(source=addon + slug=z2m|zigbee2mqtt, or source=core|supervisor|host).",
    ),
    (
        "ha_list_problems",
        "HA unhealthy / broken / errors → ha_list_problems, then ha_get_logs if needed.",
    ),
    (
        "background_tasks",
        "Watch / wait until a state changes after chat closes → background_tasks.",
    ),
    (
        "browser_interact",
        "Open or interact with a web page / Lovelace → browser_interact.",
    ),
    (
        "search_web",
        "Fresh facts / news / docs on the internet → search_web (then fetch_url if needed).",
    ),
    (
        "hassai_status",
        "What can you do / version / which tools are on → hassai_status "
        "(answer from tools you actually have, do not guess).",
    ),
    (
        "ha_get_state",
        "Is device X on/running now? → ha_list_entities → ha_get_state "
        "(not automations for live status).",
    ),
)


def looks_like_explain_event(user_text: str) -> bool:
    text = (user_text or "").strip()
    if not text:
        return False
    return bool(_EXPLAIN_EVENT_RE.search(text))


def explain_event_packs() -> set[str]:
    """Packs to prime so ha_explain_event + traces are available."""
    return {"entities", "automations"}


def build_tool_playbook(tool_names: Iterable[str] | None) -> str:
    """Short capability map for tools present this turn. Empty if nothing matches."""
    present = {str(n).strip() for n in (tool_names or []) if str(n).strip()}
    if not present:
        return ""
    lines: list[str] = []
    for name, rule in _PLAYBOOK_RULES:
        if name in present:
            lines.append(f"- {rule}")
    if not lines:
        return ""
    return (
        "Tool playbook (these tools are in your list THIS turn — use them; "
        "do not claim they are missing):\n"
        + "\n".join(lines)
    )
