"""Intent lexicon for the reflex path.

Deliberately small: a verb table that maps "aprinde / turn off / închide" to a
service intent, and a helper that strips that verb to leave the target phrase.
Everything that resembles *understanding* (which lamp, which room, what the
pronoun refers to) is the model's job, not a regex's.
"""

from __future__ import annotations

import re

from services.cognitive_kernel import (
    RISK_HIGH,
    RISK_LOW,
    GoalContract,
    Hypothesis,
)

# Verb → (intent, expected_state). Order matters: more specific first.
_VERBS: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (re.compile(r"^(?:toggle|comut[aă])\b", re.I), "toggle", ""),
    (re.compile(r"^(?:pause|pauz[aă])\b", re.I), "pause", "paused"),
    (re.compile(r"^(?:stop|opre[sș]te)\b", re.I), "turn_off", "off"),
    (re.compile(r"^(?:încuie|incuie|lock)\b", re.I), "lock", "locked"),
    (re.compile(r"^(?:descuie|unlock)\b", re.I), "unlock", "unlocked"),
    (re.compile(r"^(?:deschide|open)\b", re.I), "open", "open"),
    (re.compile(r"^(?:închide|inchide|close)\b", re.I), "close", "closed"),
    (
        re.compile(
            r"^(?:aprinde|porne[sș]te|activeaz[aă]|turn\s+on|switch\s+on|enable)\b",
            re.I,
        ),
        "turn_on",
        "on",
    ),
    (
        re.compile(
            r"^(?:stinge|dezactiveaz[aă]|turn\s+off|switch\s+off|disable)\b",
            re.I,
        ),
        "turn_off",
        "off",
    ),
)

# Filler between the verb and the name: "aprinde-mi te rog lampa" → "lampa".
_FILLER = re.compile(
    r"^(?:-?mi|te\s+rog|please|the|a|an|pe|la|din|în|in)\s+",
    re.I,
)
_TRAILING_PUNCT = re.compile(r"[\s.!?,;:]+$")

_INTENT_VERB_RO = {
    "turn_on": "aprinde", "turn_off": "stinge", "toggle": "comută",
    "open": "deschide", "close": "închide", "lock": "încuie", "unlock": "descuie",
    "pause": "pune pauză la",
}
_INTENT_VERB_EN = {
    "turn_on": "turn on", "turn_off": "turn off", "toggle": "toggle",
    "open": "open", "close": "close", "lock": "lock", "unlock": "unlock",
    "pause": "pause",
}


def parse_command(text: str) -> tuple[str, str, str]:
    """Return ``(intent, expected_state, target_phrase)`` or ``("", "", "")``.

    Only matches when the message *starts* with a known verb — "de ce s-a
    aprins lumina?" is a question, not a command.
    """
    t = re.sub(r"\s+", " ", str(text or "").strip())
    t = _TRAILING_PUNCT.sub("", t)
    if not t:
        return "", "", ""
    for pattern, intent, expected in _VERBS:
        m = pattern.match(t)
        if not m:
            continue
        rest = t[m.end():].strip()
        while True:
            stripped = _FILLER.sub("", rest).strip()
            if stripped == rest:
                break
            rest = stripped
        return intent, expected, rest
    return "", "", ""


def verb_for(intent: str, *, lang: str = "en") -> str:
    table = _INTENT_VERB_RO if lang == "ro" else _INTENT_VERB_EN
    return table.get(intent, intent.replace("_", " "))


def goal_from_hypothesis(hyp: Hypothesis, user_text: str) -> GoalContract:
    high_risk = hyp.intent in {"lock", "unlock"} or hyp.domain == "lock"
    goal = hyp.intent
    if hyp.targets:
        goal += " " + ", ".join(hyp.targets[:4])
    success = ""
    if hyp.expected_state and hyp.targets:
        success = f"entities {', '.join(hyp.targets[:4])} → state={hyp.expected_state}"
    return GoalContract(
        goal=goal or user_text[:120],
        success_criteria=success,
        risk_class=RISK_HIGH if high_risk else RISK_LOW,
        reversible=True,
        needs_approval=high_risk,
    )
