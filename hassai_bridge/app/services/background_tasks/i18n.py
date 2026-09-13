"""EN/RO copy for background-task chat messages."""

from __future__ import annotations

from core.config import load_config


def lang_from_cfg(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    raw = str((cfg or {}).get("language") or "en").strip().lower()
    return "ro" if raw.startswith("ro") else "en"


def t(lang: str, key: str, **kwargs) -> str:
    table = _RO if lang == "ro" else _EN
    text = table.get(key) or _EN.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


_EN = {
    "fallback_title": "Background task",
    "task_word": "Task",
    "cancelled": "**{title}** — stopped.{extra}",
    "cancelled_extra": "\nPartial results were kept.",
    "failed": "**{title}** — failed\n{code}: {reason}",
    "blocked": (
        "**{title}** — blocked\n{reason}. "
        "Re-enable Home Assistant Entities in Settings (or Approve for this chat), "
        "then the task can continue."
    ),
    "created_monitor": (
        "**{title}** — scheduled\n"
        "Monitoring `{detail}` for ~{dur}s. Continues even if you close this chat."
    ),
    "created_wait": (
        "**{title}** — scheduled\n"
        "Waiting for `{entity_id}` = `{state}`. Continues even if you close this chat."
    ),
    "created_remind": (
        "**{title}** — reminder scheduled\n"
        "In ~{delay}s: {message}\nContinues even if you close this chat."
    ),
    "created_generic": "**{title}** — scheduled",
    "monitor_done": "**{title}** — completed",
    "monitor_watched": "Watched: {entities}",
    "monitor_observed": "Observed for {seconds}s ({count} state changes).",
    "monitor_unavail": "Unavailable intervals: {intervals} ({seconds}s).",
    "monitor_gaps": (
        "Coverage gaps (add-on offline / HA disconnect): {gaps}s total. "
        "Missing data is not the same as ‘all good’."
    ),
    "monitor_last": "Last states: {states}",
    "wait_matched": (
        "**{title}** — condition met\n"
        "{entity_id} is `{state}` (after {seconds}s)."
    ),
    "wait_timeout": (
        "**{title}** — timed out\n"
        "Waited {seconds}s for {entity_id}=`{state}`. Last seen: `{last}`."
    ),
    "remind_done": "**{title}** — reminder\n{message}",
    "notify_remind_prefix": "Reminder",
    "status_line": "**{title}** — {status}",
    "permission_required": "permission required",
    "unknown": "unknown",
    "entities_fallback": "entities",
}

_RO = {
    "fallback_title": "Task în fundal",
    "task_word": "Task",
    "cancelled": "**{title}** — oprit.{extra}",
    "cancelled_extra": "\nRezultatele parțiale au fost păstrate.",
    "failed": "**{title}** — eșuat\n{code}: {reason}",
    "blocked": (
        "**{title}** — blocat\n{reason}. "
        "Reactivează Entities în Setări (sau Aprobă în chat), "
        "apoi task-ul poate continua."
    ),
    "created_monitor": (
        "**{title}** — programat\n"
        "Monitorizez `{detail}` ~{dur}s. Continuă chiar dacă închizi chatul."
    ),
    "created_wait": (
        "**{title}** — programat\n"
        "Aștept `{entity_id}` = `{state}`. Continuă chiar dacă închizi chatul."
    ),
    "created_remind": (
        "**{title}** — reminder programat\n"
        "Peste ~{delay}s: {message}\nContinuă chiar dacă închizi chatul."
    ),
    "created_generic": "**{title}** — programat",
    "monitor_done": "**{title}** — finalizat",
    "monitor_watched": "Urmărit: {entities}",
    "monitor_observed": "Observat {seconds}s ({count} schimbări de stare).",
    "monitor_unavail": "Intervale unavailable: {intervals} ({seconds}s).",
    "monitor_gaps": (
        "Goluri de acoperire (add-on offline / deconectare HA): {gaps}s total. "
        "Lipsa datelor nu înseamnă că totul a fost în regulă."
    ),
    "monitor_last": "Ultimele stări: {states}",
    "wait_matched": (
        "**{title}** — condiție îndeplinită\n"
        "{entity_id} este `{state}` (după {seconds}s)."
    ),
    "wait_timeout": (
        "**{title}** — timp expirat\n"
        "Am așteptat {seconds}s pentru {entity_id}=`{state}`. Ultima stare: `{last}`."
    ),
    "remind_done": "**{title}** — reminder\n{message}",
    "notify_remind_prefix": "Reminder",
    "status_line": "**{title}** — {status}",
    "permission_required": "este nevoie de permisiune",
    "unknown": "necunoscut",
    "entities_fallback": "entități",
}
