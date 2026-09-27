"""Intent Beam — keep 1–3 scored hypotheses instead of one brittle guess."""

from __future__ import annotations

import re
from typing import Iterable

from services.cognitive_kernel import (
    RISK_HIGH,
    RISK_LOW,
    RISK_MEDIUM,
    GoalContract,
    Hypothesis,
    LATENCY_DEEP,
    LATENCY_FAST,
    LATENCY_NORMAL,
)
from services import deepseek as ds
from services import tool_awareness as taw
from services import world_model as wm

_TURN_ON = re.compile(
    r"\b(?:aprinde|porne[sș]te|turn\s+on|switch\s+on|enable|activeaz[aă]|deschide)\b",
    re.I,
)
_TURN_OFF = re.compile(
    r"\b(?:stinge|opre[sș]te|turn\s+off|switch\s+off|disable|dezactiveaz[aă]|închide|inchide)\b",
    re.I,
)
_TOGGLE = re.compile(r"\b(?:toggle|comut[aă])\b", re.I)
_OPEN = re.compile(r"\b(?:open|deschide)\b", re.I)
_CLOSE = re.compile(r"\b(?:close|închide|inchide)\b", re.I)
_PAUSE = re.compile(r"\b(?:pause|pauz[aă]|opre[sș]te\s+(?:muzica|melodia|piesa))\b", re.I)
_STOP = re.compile(r"\b(?:stop|opre[sș]te\s+(?:tot|media|muzica)?)\b", re.I)
_STATUS = re.compile(
    r"\b(?:e\s+pornit|este\s+pornit|is\s+(?:it\s+)?on|status|stare|merge\s+\w+)\b",
    re.I,
)
_SET_TEMP = re.compile(
    r"(?:seteaz[aă]|set|pune).{0,20}?(\d{2})\s*°?\s*c?\b|\b(\d{2})\s*(?:grade|degrees)\b",
    re.I,
)
_ALL = re.compile(r"\b(?:toate|to[tț]i|all|every)\b", re.I)
_PRONOUN = re.compile(
    r"\b(?:aia|asta|acea|acel|la\s+fel|the\s+same|it|that\s+one|și\s+pe\s+aia)\b",
    re.I,
)
_AREA_PREP = re.compile(
    r"(?:\b(?:din|în|in|from|in\s+the|from\s+the)\s+)([a-zăâîșțşţ \-]{2,40})$",
    re.I,
)
_LOCK_WORDS = re.compile(r"\b(?:yal[aă]|lock|încuie|incuie|descuie|unlock)\b", re.I)
_COVER_WORDS = re.compile(
    r"\b(?:jaluzele|rulou|cover|blinds?|shutter|stor)\b",
    re.I,
)
_LIGHT_WORDS = re.compile(
    r"\b(?:lumin[aăi]|lumini|bec|lamp|light|lights|led|ambient)\b",
    re.I,
)
_MEDIA_WORDS = re.compile(
    r"\b(?:muzic[aă]|media|box[aă]|speaker|tv|televizor|spotify)\b",
    re.I,
)
_CLIMATE_WORDS = re.compile(
    r"\b(?:term|climat|ac\b|aer\s*cond|heat|cool|temperatur)\w*\b",
    re.I,
)


def _strip_noise(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())


def extract_area(text: str, known_areas: Iterable[str] | None = None) -> str:
    """Best-effort room/area extraction — longest valid match wins (Dormitor 1 > Dormitor)."""
    folded = wm.fold(text)
    known = list(known_areas or [])
    best = ""
    best_len = 0
    for area in known:
        af = wm.fold(area)
        if not af or af not in folded:
            continue
        # Require token boundary-ish: avoid matching "dorm" inside unrelated words via short stubs
        if len(af) >= best_len:
            best = area
            best_len = len(af)
    if best:
        return best
    m = _AREA_PREP.search(text.strip())
    if m:
        return m.group(1).strip(" .!?,")
    return ""


_VERB_STRIP = re.compile(
    r"^(?:aprinde|stinge|porne[sș]te|opre[sș]te|deschide|închide|inchide|"
    r"turn\s+on|turn\s+off|switch\s+on|switch\s+off|open|close|toggle|"
    r"enable|disable|activeaz[aă]|dezactiveaz[aă]|comut[aă]|seteaz[aă]|set)\s+",
    re.I,
)


def extract_target_phrase(text: str) -> str:
    """Strip action verbs; keep the rest (including generic light words that appear in names)."""
    t = _strip_noise(text)
    t = _VERB_STRIP.sub("", t).strip()
    # Drop leading prepositions leftover
    t = re.sub(r"^(?:din|în|in|la|pe|the|a|an)\s+", "", t, flags=re.I).strip()
    # Preserve original token order after fold/tokenize so numbers stay
    tokens = wm.tokenize(t)
    return " ".join(tokens) if tokens else wm.fold(t)


def looks_like_pronoun_followup(text: str) -> bool:
    return bool(_PRONOUN.search(text or ""))


def detect_correction(text: str) -> dict | None:
    """Detect 'nu X, Y' / 'not X, Y' style corrections."""
    t = _strip_noise(text)
    patterns = [
        re.compile(
            r"^(?:nu|not)\s+(.+?)[,;]?\s+(?:ci|ci\s+pe|ci\s+la|but|rather|the)\s+(.+)$",
            re.I,
        ),
        re.compile(
            r"^(?:m[aă]\s+refeream\s+la|i\s+meant|meant)\s+(.+)$",
            re.I,
        ),
        re.compile(
            r"^(?:nu\s+becul|wrong|nu\s+aia)[,:]?\s*(.+)$",
            re.I,
        ),
    ]
    for pat in patterns:
        m = pat.search(t)
        if not m:
            continue
        groups = m.groups()
        if len(groups) == 2:
            return {"kind": "replace", "reject": groups[0].strip(), "prefer": groups[1].strip()}
        if len(groups) == 1:
            return {"kind": "prefer", "prefer": groups[0].strip()}
    return None


def _base_action(text: str) -> tuple[str, str, str]:
    """Return (intent, service_hint, expected_state)."""
    if _TOGGLE.search(text):
        return "toggle", "toggle", ""
    if _PAUSE.search(text):
        return "pause", "media_pause", "paused"
    if _STATUS.search(text) and not (_TURN_ON.search(text) or _TURN_OFF.search(text)):
        return "status", "", ""
    if _SET_TEMP.search(text):
        return "set_temperature", "set_temperature", ""
    # open/close before generic turn_on — covers + locks
    if _CLOSE.search(text) and (_COVER_WORDS.search(text) or _LOCK_WORDS.search(text) or "living" in wm.fold(text)):
        if _LOCK_WORDS.search(text):
            return "lock", "lock", "locked"
        if _COVER_WORDS.search(text):
            return "close", "close_cover", "closed"
    if _OPEN.search(text) and (_COVER_WORDS.search(text) or _LOCK_WORDS.search(text)):
        if _LOCK_WORDS.search(text):
            return "unlock", "unlock", "unlocked"
        return "open", "open_cover", "open"
    if _TURN_OFF.search(text):
        return "turn_off", "turn_off", "off"
    if _TURN_ON.search(text):
        return "turn_on", "turn_on", "on"
    if _STOP.search(text):
        return "stop", "media_stop", "off"
    if _CLOSE.search(text):
        return "close", "turn_off", "off"
    if _OPEN.search(text):
        return "open", "turn_on", "on"
    return "", "", ""


def _domain_hints(text: str, intent: str) -> list[str]:
    hints: list[str] = []
    if _LIGHT_WORDS.search(text) or intent in {"turn_on", "turn_off", "toggle"}:
        hints.extend(["light", "switch"])
    if _COVER_WORDS.search(text) or intent in {"open", "close"}:
        hints.append("cover")
    if _LOCK_WORDS.search(text) or intent in {"lock", "unlock"}:
        hints.append("lock")
    if _MEDIA_WORDS.search(text) or intent in {"pause", "stop"}:
        hints.append("media_player")
    if _CLIMATE_WORDS.search(text) or intent == "set_temperature":
        hints.append("climate")
    # Deduplicate preserving order
    seen: set[str] = set()
    out: list[str] = []
    for d in hints:
        if d not in seen:
            seen.add(d)
            out.append(d)
    return out


def compile_hypotheses(
    user_text: str,
    *,
    entities: list[wm.EntityNode] | None = None,
    working_memory: dict | None = None,
    aliases: list[dict] | None = None,
    known_areas: Iterable[str] | None = None,
) -> list[Hypothesis]:
    """Build 1–3 scored intent hypotheses for a message."""
    text = _strip_noise(user_text)
    if not text:
        return []

    # Never beam automation/explain into control execution
    if ds.looks_like_automation_edit(text) or taw.looks_like_explain_event(text):
        return [Hypothesis(intent="complex", score=0.55, reason="automation_or_explain")]

    if detect_correction(text):
        return [Hypothesis(intent="correction", score=0.9, reason="user_correction")]

    intent, service, expected = _base_action(text)
    if not intent and not ds.looks_like_control(text):
        if len(text) < 40 and not ds.looks_like_planning(text):
            return [Hypothesis(intent="chat", score=0.8, reason="smalltalk_or_chat")]
        return [Hypothesis(intent="complex", score=0.5, reason="needs_agent")]

    if not intent:
        intent, service, expected = "control", "", ""

    area = extract_area(text, known_areas)
    wm_mem = working_memory or {}
    if not area and looks_like_pronoun_followup(text):
        area = str(wm_mem.get("last_area") or "")

    domains = _domain_hints(text, intent)
    # Ambiguous "închide livingul" → beam cover + lights
    beam_domains: list[list[str]] = []
    folded = wm.fold(text)
    if intent in {"close", "open", "turn_off"} and "living" in folded and not (
        _LIGHT_WORDS.search(text) or _COVER_WORDS.search(text) or _MEDIA_WORDS.search(text)
    ):
        beam_domains = [["cover"], ["light", "switch"], ["media_player"]]
    elif domains:
        beam_domains = [domains]
    else:
        beam_domains = [["light", "switch"]]

    # Alias boost
    alias_hits: list[str] = []
    for a in aliases or []:
        surface = wm.fold(str(a.get("surface") or ""))
        target = str(a.get("resolves_to") or "").strip()
        if surface and surface in folded and target:
            alias_hits.append(target)

    hypotheses: list[Hypothesis] = []
    entities = entities or []

    target_phrase = extract_target_phrase(text)

    for domain_set in beam_domains:
        # Search with normalized target first; fall back to full text
        query = target_phrase or text
        hits = wm.search(
            entities, query, domains=domain_set, area=area, limit=8,
            hard_area=False,
        )
        if not hits and query != text:
            hits = wm.search(entities, text, domains=domain_set, area=area, limit=8)

        if alias_hits:
            alias_nodes = [n for n in entities if n.entity_id in alias_hits and n.domain in domain_set]
            for n in alias_nodes:
                hits = [(n, 12.0)] + [(x, s) for x, s in hits if x.entity_id != n.entity_id]

        if looks_like_pronoun_followup(text) and wm_mem.get("last_entities"):
            last = [str(e) for e in wm_mem["last_entities"][:4]]
            pronoun_nodes = [n for n in entities if n.entity_id in last]
            if pronoun_nodes:
                hits = [(n, 11.0) for n in pronoun_nodes] + hits

        targets: list[str] = []
        pick_mode = "weak"
        if hits:
            targets, pick_mode = wm.pick_targets(hits, query=query)
            if pick_mode == "weak":
                targets = []
        top_score = hits[0][1] if hits else 0.0
        # Normalize roughly to 0..1
        score = min(0.98, 0.45 + top_score / 14.0)
        if pick_mode == "unique":
            score = max(score, 0.88)
        elif pick_mode == "clarify":
            score = min(score, 0.72)
        if not targets and intent not in {"chat", "complex", "correction"}:
            score = 0.35
        if _ALL.search(text) and area:
            area_hits = [
                n.entity_id for n, _ in wm.search(
                    entities, area, domains=domain_set, area=area, limit=20, hard_area=True,
                )
            ]
            if area_hits:
                targets = area_hits
                score = max(score, 0.85)
                pick_mode = "unique"

        hyp_intent = intent
        hyp_service = service
        if domain_set == ["cover"] and intent in {"close", "turn_off", "open", "turn_on"}:
            hyp_intent = "close" if intent in {"close", "turn_off"} else "open"
            hyp_service = "close_cover" if hyp_intent == "close" else "open_cover"
            expected_local = "closed" if hyp_intent == "close" else "open"
        elif domain_set == ["media_player"] and intent in {"close", "turn_off"}:
            hyp_intent = "turn_off"
            hyp_service = "turn_off"
            expected_local = "off"
        else:
            expected_local = expected

        hypotheses.append(Hypothesis(
            intent=hyp_intent,
            score=score,
            targets=targets,
            area=area or (hits[0][0].area if hits else ""),
            service=hyp_service,
            domain=domain_set[0] if domain_set else "",
            reason=f"domains={','.join(domain_set)};pick={pick_mode}",
            expected_state=expected_local,
        ))
    # Collapse identical target sets
    unique: list[Hypothesis] = []
    seen_keys: set[str] = set()
    for h in sorted(hypotheses, key=lambda x: -x.score):
        key = f"{h.intent}|{','.join(h.targets[:3])}|{h.domain}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        unique.append(h)
    return unique[:3]


def goal_from_hypothesis(hyp: Hypothesis, user_text: str) -> GoalContract:
    risk = RISK_LOW
    reversible = True
    needs_approval = False
    latency = LATENCY_FAST
    packs = ["entities", "control"]

    if hyp.intent in {"lock", "unlock"} or hyp.domain == "lock":
        risk = RISK_HIGH
        reversible = True
        needs_approval = True
        latency = LATENCY_NORMAL
    elif hyp.intent in {"complex", "correction"}:
        risk = RISK_MEDIUM
        latency = LATENCY_DEEP
        packs = []
    elif hyp.intent == "status":
        packs = ["entities"]
        latency = LATENCY_FAST

    goal = f"{hyp.intent}"
    if hyp.targets:
        goal += " " + ", ".join(hyp.targets[:4])
    elif hyp.area:
        goal += f" in {hyp.area}"

    success = ""
    if hyp.expected_state and hyp.targets:
        success = f"entities {', '.join(hyp.targets[:4])} → state={hyp.expected_state}"
    elif hyp.intent == "status":
        success = "report live state"

    return GoalContract(
        goal=goal or user_text[:120],
        success_criteria=success,
        risk_class=risk,
        latency_budget=latency,
        packs_hint=packs,
        reversible=reversible,
        needs_approval=needs_approval,
    )
