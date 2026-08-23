"""Long-term memory as explicit LLM tools.

Until now memory was only written by a background extraction pass, so "remember
this" was never guaranteed to land and nothing showed up in the activity strip.
These tools let the model read and write its own memory deterministically, and
they refuse to store live device state — that has to be read from Home
Assistant every time instead of being frozen into a fact.
"""

from __future__ import annotations

import logging
import re

from config import load_config
from database import (
    CATEGORIES,
    add_memory,
    deactivate_memory,
    find_duplicate_memories,
    get_memories,
    get_memories_by_category,
    get_memory,
    get_memory_stats,
    log_memory_action,
    search_memories,
    update_memory,
)

log = logging.getLogger("hassai.memory.tools")

TOOL_NAMES = frozenset({
    "memory_save",
    "memory_search",
    "memory_list",
    "memory_update",
    "memory_forget",
})

_MAX_CONTENT = 400


# ── Durable fact vs. live state ────────────────────

# Habitual / preference wording — "lights off at night" is a preference, not a
# reading, so these win over the state patterns below.
_HABITUAL = re.compile(
    r"\b(prefer[aăs]?|prefers|preferr?ed|îmi place|imi place|îi place|ii place|likes?|loves?|hates?|"
    r"urăsc|urasc|de obicei|usually|always|întotdeauna|intotdeauna|niciodată|niciodata|never|"
    r"în fiecare|in fiecare|every (day|night|morning|evening|week)|obișnuiește|obisnuieste|"
    r"vrea ca|wants? (me|you|us)|rutina|routine|regulă|regula|rule|standing instruction)\b",
    re.IGNORECASE,
)

# "as of now" markers — anything scoped to this moment is not a memory.
_NOW_MARKER = re.compile(
    r"\b(acum|momentan|în acest moment|in acest moment|chiar acum|currently|right now|"
    r"at the moment|as of now|just now|tocmai|azi|astăzi|astazi|today|tonight|"
    r"în seara asta|in seara asta|ieri|yesterday|mâine|maine|tomorrow|"
    r"la ora asta|this (morning|afternoon|evening|week))\b",
    re.IGNORECASE,
)

_DEVICE_WORD = (
    r"bec(ul|uri|urile)?|lumin[ai]|luminile|lamp[aă]|lampa|light|lights|lamp|"
    r"switch|întrerupător|intrerupator|priz[aă]|plug|socket|"
    r"u[sș][aă]|door|gate|poart[aă]|geam|fereastr[aă]|window|"
    r"senzor|sensor|termostat|thermostat|aer condi[țt]ionat|ac|hvac|"
    r"camer[aă]|camera|tv|televizor|boiler|centrala|centrală|pomp[aă]|pump|"
    r"alarm[aă]|alarm|sistem|robot|aspirator|vacuum"
)

_STATE_WORD = (
    r"on|off|open|opened|closed|locked|unlocked|running|idle|"
    r"aprins[aăeă]?|aprinse|stins[aăeă]?|stinse|pornit[aăeă]?|pornite|oprit[aăeă]?|oprite|"
    r"deschis[aăeă]?|deschise|închis[aăeă]?|inchis[aăeă]?|închise|inchise|"
    r"încuiat[aăeă]?|incuiat[aăeă]?|descuiat[aăeă]?"
)

_DEVICE_STATE = re.compile(
    rf"\b(?:{_DEVICE_WORD})\b[^.]{{0,40}}?\b(?:{_STATE_WORD})\b",
    re.IGNORECASE,
)

# "temperature is 21", "battery at 43%" — a reading, not a fact.
_READING = re.compile(
    r"\b(temperatur[aăi]|temperature|umiditat[ea]|humidity|bateri[ae]|battery|"
    r"consum(ul)?|consumption|power|puter[ea]|nivel(ul)?|level|presiun[ea]|pressure|"
    r"vitez[aă]|speed)\b"
    r"[^.]{0,20}?(\bis\b|\beste\b|\be\b|\bla\b|\bat\b|[:=])\s*-?\d",
    re.IGNORECASE,
)

_PRESENCE = re.compile(
    r"\b(is|isn't|is not|este|nu este|e|nu e)\s+(acas[aă]|home|away|plecat[aă]?|"
    r"la birou|at work|in bed|în pat|in pat|online|offline|prezent|present)\b",
    re.IGNORECASE,
)

_META = re.compile(
    r"\b(user (asked|wanted|said|mentioned|requested)|utilizatorul a (întrebat|intrebat|cerut|spus)|"
    r"we discussed|conversation about|în această conversație|in aceasta conversatie)\b",
    re.IGNORECASE,
)


def transient_reason(text: str) -> str:
    """Return why `text` looks like live state instead of a durable fact ('' if fine)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if _HABITUAL.search(raw):
        return ""
    if _NOW_MARKER.search(raw):
        return "it is scoped to right now"
    if _DEVICE_STATE.search(raw):
        return "it is a device state that changes on its own"
    if _READING.search(raw):
        return "it is a sensor reading"
    if _PRESENCE.search(raw):
        return "it is a presence state that changes on its own"
    return ""


def _meta_reason(text: str) -> str:
    return "it describes the conversation instead of a fact" if _META.search(text or "") else ""


# ── Tool specs ─────────────────────────────────────

_CATEGORY_DESC = (
    "personal_info (name, family, job, birthday), preferences (likes, style, language), "
    "home_setup (rooms, devices, naming conventions, network), facts (durable facts about "
    "the user's world), instructions (standing orders for how you should behave), "
    "context (long-running projects or situations)"
)

TOOL_SPECS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "memory_save",
            "description": (
                "Store one durable fact about this user in long-term memory. Call this "
                "immediately whenever the user asks you to remember/note something, and also "
                "on your own when you learn a lasting fact (names, family, pets, job, home "
                "layout, device naming, preferences, standing instructions). "
                "NEVER store live state such as a light being on, the current temperature, "
                "who is home right now, or today's weather — read those live with the Home "
                "Assistant tools instead. One fact per call, written as a standalone sentence "
                "that still makes sense months from now."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": (
                            "The fact, self-contained and in the user's language. "
                            "Good: 'Andrei's daughter is called Maria and was born in 2019'. "
                            "Bad: 'the kitchen light is on'."
                        ),
                    },
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "importance": {
                        "type": "integer",
                        "description": "1-5. 5 = core identity, 3 = normal, 1 = minor detail.",
                    },
                },
                "required": ["content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_search",
            "description": (
                "Search this user's long-term memory. Use it before saying you do not know "
                "something about the user, or to check what you already stored on a topic."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "What to look for."},
                    "limit": {"type": "integer", "description": "Max results (default 10, max 30)."},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_list",
            "description": (
                "List what you remember about this user, newest and most important first. "
                "Use it when the user asks what you know or remember about them."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "limit": {"type": "integer", "description": "Max entries (default 20, max 50)."},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_update",
            "description": (
                "Rewrite a stored memory when the fact changed (moved city, new car, new job). "
                "Get the id from memory_search or memory_list first."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memory_id": {"type": "integer"},
                    "content": {"type": "string"},
                    "category": {"type": "string", "enum": list(CATEGORIES)},
                    "importance": {"type": "integer"},
                },
                "required": ["memory_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_forget",
            "description": (
                "Forget a stored memory that is wrong or no longer true. Get the id from "
                "memory_search or memory_list first. Use memory_update instead when the fact "
                "merely changed."
            ),
            "parameters": {
                "type": "object",
                "properties": {"memory_id": {"type": "integer"}},
                "required": ["memory_id"],
            },
        },
    },
]


def is_enabled(cfg: dict | None = None) -> bool:
    if cfg is None:
        cfg = load_config()
    mem = cfg.get("memory") or {}
    if not mem.get("enabled", True):
        return False
    from services import bridge_tool_access as bta

    return bta.group_enabled("memory", cfg)


def build_tools(cfg: dict | None = None) -> list[dict]:
    return list(TOOL_SPECS) if is_enabled(cfg) else []


def system_hint(cfg: dict | None = None) -> str:
    if not is_enabled(cfg):
        return ""
    return (
        "[Memory] You have real long-term memory for this user, stored in the HASSAI Bridge "
        "database; what you already know is supplied in the [Identity] / [Memories] / [Graph] "
        "context block.\n"
        "- The user asks you to remember, note or not forget something → call memory_save right "
        "away. Never answer \"noted\" without calling it.\n"
        "- Save durable facts you pick up on your own too: names, family, pets, job, home layout, "
        "how they name rooms and devices, preferences, standing instructions.\n"
        "- Never save live state (a light being on, current temperature, who is home now, today's "
        "weather). That is state — read it with the Home Assistant tools every time it is asked.\n"
        "- Use memory_search before claiming you do not know something about the user, and "
        "memory_update / memory_forget when a stored fact changed or turned out wrong."
    )


def tool_detail(name: str, args: dict) -> str:
    args = args or {}
    if name in ("memory_save", "memory_update"):
        return str(args.get("content") or "")
    if name == "memory_search":
        return str(args.get("query") or "")
    if name == "memory_list":
        return str(args.get("category") or "")
    if name == "memory_forget":
        return str(args.get("memory_id") or "")
    return ""


# ── Handlers ───────────────────────────────────────

def _fmt(rows: list[dict]) -> str:
    return "\n".join(
        f"#{r['id']} [{r.get('category', 'facts')}, importance {r.get('importance', 3)}] {r['content']}"
        for r in rows
    )


def _coerce_importance(raw, default: int = 3) -> int:
    try:
        return max(1, min(5, int(raw)))
    except (TypeError, ValueError):
        return default


def _owned(memory_id: int, user_id: str) -> dict | None:
    row = get_memory(memory_id)
    if not row or row.get("user_id") != user_id:
        return None
    return row


def _save(user_id: str, args: dict, cfg: dict) -> str:
    content = " ".join(str(args.get("content") or "").split())[:_MAX_CONTENT]
    if len(content) < 5:
        return "Error: nothing to save — pass the fact in `content`."

    reason = transient_reason(content) or _meta_reason(content)
    if reason:
        return (
            f"Rejected: \"{content}\" was not stored because {reason}. "
            "Long-term memory is only for facts that stay true. Read live values with the "
            "Home Assistant tools instead, or rephrase this as a lasting fact "
            "(a preference, a routine, a naming convention) and call memory_save again."
        )

    category = str(args.get("category") or "").strip()
    if category not in CATEGORIES:
        category = "facts"
    importance = _coerce_importance(args.get("importance"))

    dupes = find_duplicate_memories(user_id, content, threshold=0.75)
    if dupes:
        existing = dupes[0]
        update_memory(existing["id"], content=content, category=category, importance=importance)
        log_memory_action(user_id, "updated", f"tool dedup #{existing['id']}: {content[:80]}")
        _invalidate(user_id)
        return f"Already knew that — refreshed memory #{existing['id']}: {content}"

    stats = get_memory_stats(user_id)
    max_mem = (cfg.get("memory") or {}).get("max_memories_per_user", 500)
    if stats["total"] >= max_mem:
        return (
            f"Error: memory is full ({stats['total']}/{max_mem}). Forget something with "
            "memory_forget, or raise the limit in Settings → Memory."
        )

    keywords = ",".join(w.lower() for w in content.split() if len(w) > 3)[:200]
    mem_id = add_memory(
        user_id, content, category=category, keywords=keywords,
        importance=importance, source="tool",
    )
    log_memory_action(user_id, "extracted", f"tool: {content[:100]}")
    _invalidate(user_id)
    log.info("Memory saved via tool for %s: #%s %s", user_id, mem_id, content[:80])
    return f"Remembered (#{mem_id}, {category}, importance {importance}): {content}"


def _search(user_id: str, args: dict) -> str:
    from services.memory_engine import _extract_keywords_local

    query = str(args.get("query") or "").strip()
    if not query:
        return "Error: empty query."
    try:
        limit = max(1, min(30, int(args.get("limit") or 10)))
    except (TypeError, ValueError):
        limit = 10
    rows = search_memories(user_id, _extract_keywords_local(query), limit=limit)
    if not rows:
        return f"No memories match '{query}'."
    return f"{len(rows)} memory match(es) for '{query}':\n{_fmt(rows)}"


def _list(user_id: str, args: dict) -> str:
    limit = 20
    try:
        limit = max(1, min(50, int(args.get("limit") or 20)))
    except (TypeError, ValueError):
        pass
    category = str(args.get("category") or "").strip()
    if category in CATEGORIES:
        rows = get_memories_by_category(user_id, category, limit=limit)
        label = f"in '{category}'"
    else:
        rows = get_memories(user_id, limit=limit)
        label = "stored"
    if not rows:
        return f"No memories {label} yet."
    stats = get_memory_stats(user_id)
    return f"{len(rows)} of {stats['total']} memories {label}:\n{_fmt(rows)}"


def _update(user_id: str, args: dict) -> str:
    try:
        memory_id = int(args.get("memory_id"))
    except (TypeError, ValueError):
        return "Error: memory_id must be a number from memory_search or memory_list."
    row = _owned(memory_id, user_id)
    if not row:
        return f"Error: memory #{memory_id} does not exist for this user."

    content = " ".join(str(args.get("content") or "").split())[:_MAX_CONTENT] or None
    if content:
        reason = transient_reason(content) or _meta_reason(content)
        if reason:
            return (
                f"Rejected: memory #{memory_id} was not changed because {reason}. "
                "Store lasting facts only."
            )
    category = str(args.get("category") or "").strip()
    category = category if category in CATEGORIES else None
    importance = _coerce_importance(args.get("importance"), default=0) or None
    if content is None and category is None and importance is None:
        return "Error: nothing to change — pass content, category or importance."

    keywords = ",".join(w.lower() for w in content.split() if len(w) > 3)[:200] if content else None
    update_memory(memory_id, content=content, category=category,
                  keywords=keywords, importance=importance)
    log_memory_action(user_id, "updated", f"tool #{memory_id}: {(content or row['content'])[:80]}")
    _invalidate(user_id)
    return f"Updated memory #{memory_id}: {content or row['content']}"


def _forget(user_id: str, args: dict) -> str:
    try:
        memory_id = int(args.get("memory_id"))
    except (TypeError, ValueError):
        return "Error: memory_id must be a number from memory_search or memory_list."
    row = _owned(memory_id, user_id)
    if not row:
        return f"Error: memory #{memory_id} does not exist for this user."
    deactivate_memory(memory_id)
    log_memory_action(user_id, "deleted", f"tool #{memory_id}: {row['content'][:80]}")
    _invalidate(user_id)
    return f"Forgot memory #{memory_id}: {row['content']}"


def _invalidate(user_id: str) -> None:
    try:
        from services.memory_engine import _memory_cache_invalidate

        _memory_cache_invalidate(user_id)
    except Exception:  # pragma: no cover - cache is best effort
        pass


def run_tool(name: str, args: dict, user_id: str, cfg: dict | None = None) -> str:
    if cfg is None:
        cfg = load_config()
    if not is_enabled(cfg):
        return "Error: memory tools are disabled in Settings → HASSAI Bridge tools."
    if not user_id:
        return "Error: no user context for memory."
    args = args or {}
    try:
        if name == "memory_save":
            return _save(user_id, args, cfg)
        if name == "memory_search":
            return _search(user_id, args)
        if name == "memory_list":
            return _list(user_id, args)
        if name == "memory_update":
            return _update(user_id, args)
        if name == "memory_forget":
            return _forget(user_id, args)
    except Exception as exc:  # pragma: no cover - defensive
        log.error("Memory tool %s failed: %s", name, exc)
        return f"Error: memory tool failed — {exc}"
    return f"Error: unknown memory tool '{name}'"
