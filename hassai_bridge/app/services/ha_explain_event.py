"""ha_explain_event — correlate history, logbook, and traces to explain a state change."""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from core.config import load_config
from services import ha_tool_access as hta

log = logging.getLogger("hassai.ha_explain_event")

TOOL_NAME = "ha_explain_event"

TOOL_SPEC = {
    "description": (
        "Explain why an entity changed state (e.g. light turned on). "
        "Gathers Home Assistant history (with context), logbook, and automation/script traces. "
        "Returns structured evidence and confidence. "
        "If cause cannot be proven, says unknown — never invents a physical switch press. "
        "Prefer this for 'de ce s-a aprins / who changed X' questions."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "entity_id": {
                "type": "string",
                "description": "Entity to explain (e.g. light.bedroom)",
            },
            "event": {
                "type": "string",
                "description": (
                    "Optional: turned_on | turned_off | state_changed | or a target state "
                    "(e.g. on, off, home). Default: last meaningful change."
                ),
            },
            "start_time": {
                "type": "string",
                "description": "Optional ISO start of search window",
            },
            "end_time": {
                "type": "string",
                "description": "Optional ISO end of search window",
            },
        },
        "required": ["entity_id"],
    },
}

_DEFAULT_LOOKBACK_HOURS = 24
_MAX_LOOKBACK_HOURS = 168


def _lang(cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    raw = str((cfg or {}).get("language") or "en").strip().lower()
    return "ro" if raw.startswith("ro") else "en"


def _t(lang: str, key: str, **kwargs) -> str:
    table = _RO if lang == "ro" else _EN
    text = table.get(key) or _EN.get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


_EN = {
    "no_entity": "entity_id is required",
    "no_history": "No history found for this entity in the search window.",
    "no_transition": "No matching state transition found in the search window.",
    "missing_context": "State change has no Home Assistant context id",
    "missing_traces_perm": "Automation traces skipped (ha:automations is OFF in Settings)",
    "missing_trace": "No matching automation/script trace found for this context",
    "missing_logbook": "Logbook had no clear actor for this change",
    "evidence_context_auto": "State change context matches automation run {item}",
    "evidence_context_script": "State change context matches script run {item}",
    "evidence_context_user": "State change context has user_id {user_id}",
    "evidence_logbook": "Logbook: {message}",
    "evidence_trace_action": "Trace confirms action involving {entity_id}",
    "evidence_time_near": "Automation {item} ran near the change time (no shared context)",
    "chain_sensor": "Related trigger/sensor activity around the change",
    "chain_auto": "Automation «{name}» ran",
    "chain_script": "Script «{name}» ran",
    "chain_user": "A Home Assistant user action is linked via context",
    "chain_action": "An action changed {entity_id} ({change})",
    "summary_auto": (
        "{entity_id} changed ({change}) via automation «{name}». Trace/context confirms the link."
    ),
    "summary_script": (
        "{entity_id} changed ({change}) via script «{name}». Trace/context confirms the link."
    ),
    "summary_user": "{entity_id} changed ({change}) linked to a Home Assistant user action.",
    "summary_possible": (
        "{entity_id} changed ({change}). Nearby automation activity was found, "
        "but shared context is missing — cause is only possible, not confirmed."
    ),
    "summary_unknown": (
        "I cannot determine why {entity_id} changed ({change}). "
        "There is not enough evidence (missing context/trace/logbook link)."
    ),
}

_RO = {
    "no_entity": "entity_id este obligatoriu",
    "no_history": "Nu există istoric pentru această entitate în fereastra căutată.",
    "no_transition": "Nu am găsit o tranziție de stare potrivită în fereastra căutată.",
    "missing_context": "Schimbarea de stare nu are context.id în Home Assistant",
    "missing_traces_perm": "Trace-urile de automatizări sunt omise (ha:automations e OFF în Setări)",
    "missing_trace": "Nu există trace de automatizare/script pentru acest context",
    "missing_logbook": "Logbook-ul nu indică clar un actor pentru această schimbare",
    "evidence_context_auto": "Contextul schimbării se leagă de execuția automatizării {item}",
    "evidence_context_script": "Contextul schimbării se leagă de execuția scriptului {item}",
    "evidence_context_user": "Contextul schimbării are user_id {user_id}",
    "evidence_logbook": "Logbook: {message}",
    "evidence_trace_action": "Trace-ul confirmă o acțiune asupra {entity_id}",
    "evidence_time_near": "Automatizarea {item} a rulat aproape de momentul schimbării (fără context comun)",
    "chain_sensor": "Activitate legată de trigger/senzor în jurul schimbării",
    "chain_auto": "Automatizarea «{name}» s-a declanșat",
    "chain_script": "Scriptul «{name}» a rulat",
    "chain_user": "O acțiune de utilizator Home Assistant e legată prin context",
    "chain_action": "O acțiune a schimbat {entity_id} ({change})",
    "summary_auto": (
        "{entity_id} s-a schimbat ({change}) din automatizarea «{name}». "
        "Contextul/trace-ul confirmă legătura."
    ),
    "summary_script": (
        "{entity_id} s-a schimbat ({change}) din scriptul «{name}». "
        "Contextul/trace-ul confirmă legătura."
    ),
    "summary_user": "{entity_id} s-a schimbat ({change}), legat de o acțiune de utilizator HA.",
    "summary_possible": (
        "{entity_id} s-a schimbat ({change}). Am găsit activitate de automatizare în apropiere, "
        "dar fără context comun — cauza e doar posibilă, nu confirmată."
    ),
    "summary_unknown": (
        "Nu pot determina de ce s-a schimbat {entity_id} ({change}). "
        "Nu există suficiente dovezi (lipsește context/trace/logbook)."
    ),
}


def _parse_dt(raw: str | None) -> datetime | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def _state_ts(row: dict) -> datetime | None:
    for key in ("last_changed", "last_updated", "timestamp"):
        dt = _parse_dt(row.get(key) if isinstance(row, dict) else None)
        if dt:
            return dt
    return None


def _ctx(row: dict) -> dict:
    c = row.get("context") if isinstance(row, dict) else None
    return c if isinstance(c, dict) else {}


def _wanted_transition(event: str | None) -> tuple[str | None, str | None]:
    """Return (from_state or None, to_state or None)."""
    ev = str(event or "").strip().lower()
    if not ev or ev in {"state_changed", "changed", "any"}:
        return None, None
    if ev in {"turned_on", "turn_on", "on"}:
        return "off", "on"
    if ev in {"turned_off", "turn_off", "off"}:
        return "on", "off"
    # bare target state
    return None, ev


def _find_transition(
    rows: list[dict],
    *,
    from_state: str | None,
    to_state: str | None,
    start: datetime | None,
    end: datetime | None,
) -> tuple[dict | None, dict | None]:
    """Return (prev_row, new_row) for the matching transition (prefer last)."""
    cleaned = [r for r in rows if isinstance(r, dict)]
    matches: list[tuple[dict | None, dict]] = []
    prev = None
    for row in cleaned:
        ts = _state_ts(row)
        if start and ts and ts < start:
            prev = row
            continue
        if end and ts and ts > end:
            break
        if prev is not None:
            old_s = str(prev.get("state") or "")
            new_s = str(row.get("state") or "")
            if old_s != new_s:
                ok = True
                if to_state is not None and new_s.lower() != to_state.lower():
                    ok = False
                if from_state is not None and old_s.lower() != from_state.lower():
                    ok = False
                if ok:
                    matches.append((prev, row))
        prev = row
    if not matches:
        return None, None
    return matches[-1]


def _window_around(when: datetime, *, pad_minutes: int = 10) -> tuple[datetime, datetime]:
    return when - timedelta(minutes=pad_minutes), when + timedelta(minutes=pad_minutes)


def _extract_history_rows(payload: Any, entity_id: str) -> list[dict]:
    if not isinstance(payload, list) or not payload:
        return []
    # HA returns [ [states...] ] for one entity, or multiple blocks
    for block in payload:
        if not isinstance(block, list) or not block:
            continue
        first = block[0] if isinstance(block[0], dict) else {}
        eid = str(first.get("entity_id") or "")
        if eid == entity_id or len(payload) == 1:
            return [r for r in block if isinstance(r, dict)]
    # fallback first block
    block = payload[0]
    return [r for r in block if isinstance(r, dict)] if isinstance(block, list) else []


def _logbook_hints(entries: list[dict], *, entity_id: str, when: datetime | None) -> list[dict]:
    out = []
    for row in entries:
        if not isinstance(row, dict):
            continue
        eid = str(row.get("entity_id") or "")
        msg = str(row.get("message") or row.get("name") or "")
        domain = str(row.get("domain") or "")
        ctx = row.get("context_id") or ((row.get("context") or {}) if isinstance(row.get("context"), dict) else {}).get("id")
        when_s = str(row.get("when") or "")
        near = True
        if when:
            wt = _parse_dt(when_s)
            if wt and abs((wt - when).total_seconds()) > 600:
                near = False
        if not near:
            continue
        if eid == entity_id or domain in {"automation", "script"} or "automation" in msg.lower() or "script" in msg.lower():
            out.append({
                "entity_id": eid,
                "message": msg,
                "domain": domain,
                "context_id": ctx,
                "when": when_s,
                "name": row.get("name") or row.get("context_event_type") or "",
            })
    return out[:40]


def _automation_id_from_text(text: str) -> str | None:
    m = re.search(r"\bautomation\.([a-z0-9_]+)\b", text or "", re.I)
    if m:
        return m.group(1)
    m = re.search(r"\bscript\.([a-z0-9_]+)\b", text or "", re.I)
    if m:
        return f"script:{m.group(1)}"
    return None


def _trace_mentions_entity(trace: Any, entity_id: str) -> bool:
    try:
        blob = json.dumps(trace, ensure_ascii=False, default=str)
    except Exception:
        blob = str(trace)
    return entity_id in blob


def _pick_trace(
    traces: Any,
    *,
    context_id: str,
    parent_id: str,
    around: datetime | None,
) -> dict | None:
    if isinstance(traces, dict):
        # sometimes {item_id: [runs]}
        candidates = []
        for _k, v in traces.items():
            if isinstance(v, list):
                candidates.extend([x for x in v if isinstance(x, dict)])
            elif isinstance(v, dict):
                candidates.append(v)
        rows = candidates
    elif isinstance(traces, list):
        rows = [t for t in traces if isinstance(t, dict)]
    else:
        rows = []
    for row in rows:
        tid = str(row.get("context_id") or (row.get("context") or {}).get("id") or "")
        if context_id and tid == context_id:
            return row
        if parent_id and tid == parent_id:
            return row
        # nested
        for key in ("context", "trigger"):
            c = row.get(key)
            if isinstance(c, dict):
                cid = str(c.get("id") or "")
                if context_id and cid == context_id:
                    return row
                if parent_id and cid == parent_id:
                    return row
    if around:
        best = None
        best_delta = 1e18
        for row in rows:
            ts = _parse_dt(str(row.get("timestamp") or row.get("start") or row.get("last_step") or ""))
            if not ts:
                continue
            d = abs((ts - around).total_seconds())
            if d < best_delta and d <= 120:
                best_delta = d
                best = row
        return best
    return None


async def _fetch_history(entity_id: str, start: datetime, end: datetime) -> list[dict]:
    from services import homeassistant as ha

    params = {
        "filter_entity_id": entity_id,
        "end_time": end.isoformat(),
        # full response so context is present
    }
    payload = await ha._core_query(f"/history/period/{start.isoformat()}", params)
    return _extract_history_rows(payload, entity_id)


async def _fetch_logbook(entity_id: str, start: datetime, end: datetime) -> list[dict]:
    from services import homeassistant as ha

    hours = max(1, int((end - start).total_seconds() // 3600) + 1)
    days = max(1, (hours + 23) // 24)
    params = {"period": days, "entity": entity_id}
    payload = await ha._core_query(f"/logbook/{start.isoformat()}", params)
    if not isinstance(payload, list):
        return []
    # filter to window
    out = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        wt = _parse_dt(str(row.get("when") or ""))
        if wt and (wt < start - timedelta(minutes=5) or wt > end + timedelta(minutes=5)):
            continue
        out.append(row)
    return out


async def _list_traces(domain: str, item_id: str | None = None) -> Any:
    from services import homeassistant as ha

    payload: dict[str, Any] = {"type": "trace/list", "domain": domain}
    if item_id:
        if item_id.startswith(f"{domain}."):
            item_id = item_id.split(".", 1)[1]
        payload["item_id"] = item_id
    return await ha._ws_call(payload)


async def _get_trace(domain: str, item_id: str, run_id: str) -> Any:
    from services import homeassistant as ha

    if item_id.startswith(f"{domain}."):
        item_id = item_id.split(".", 1)[1]
    return await ha._ws_call({
        "type": "trace/get",
        "domain": domain,
        "item_id": item_id,
        "run_id": run_id,
    })


def build_report(
    *,
    entity_id: str,
    prev: dict | None,
    cur: dict,
    logbook: list[dict],
    traces_allowed: bool,
    matched_trace: dict | None,
    full_trace: Any | None,
    time_near_auto: str | None,
    lang: str,
) -> dict:
    old_s = str((prev or {}).get("state") or "?")
    new_s = str(cur.get("state") or "?")
    change = f"{old_s} → {new_s}"
    when_dt = _state_ts(cur)
    when = when_dt.isoformat() if when_dt else str(cur.get("last_changed") or "")
    ctx = _ctx(cur)
    context_id = str(ctx.get("id") or "")
    parent_id = str(ctx.get("parent_id") or "")
    user_id = str(ctx.get("user_id") or "")

    evidence: list[str] = []
    missing: list[str] = []
    chain: list[str] = []
    cause_type = "unknown"
    confidence = "unknown"
    name = ""

    if not context_id:
        missing.append(_t(lang, "missing_context"))

    hints = _logbook_hints(logbook, entity_id=entity_id, when=when_dt)
    for h in hints[:5]:
        if h.get("message"):
            evidence.append(_t(lang, "evidence_logbook", message=h["message"]))

    auto_from_log = None
    for h in hints:
        aid = _automation_id_from_text(f"{h.get('entity_id')} {h.get('message')} {h.get('name')}")
        if aid:
            auto_from_log = aid
            break
        if h.get("domain") == "automation" and h.get("entity_id"):
            auto_from_log = str(h["entity_id"]).removeprefix("automation.")
            break
        if h.get("domain") == "script" and h.get("entity_id"):
            auto_from_log = f"script:{str(h['entity_id']).removeprefix('script.')}"
            break

    if user_id and not matched_trace:
        cause_type = "user"
        confidence = "confirmed" if context_id else "possible"
        evidence.append(_t(lang, "evidence_context_user", user_id=user_id))
        chain.append(_t(lang, "chain_user"))
        chain.append(_t(lang, "chain_action", entity_id=entity_id, change=change))

    if matched_trace:
        domain = "automation"
        item = str(
            matched_trace.get("item_id")
            or matched_trace.get("automation_id")
            or matched_trace.get("script_id")
            or auto_from_log
            or ""
        )
        if str(matched_trace.get("domain") or "").lower() == "script" or (
            auto_from_log and str(auto_from_log).startswith("script:")
        ):
            domain = "script"
            item = item.removeprefix("script:")
        name = item or "unknown"
        cause_type = domain
        confidence = "confirmed" if context_id else "possible"
        if domain == "automation":
            evidence.append(_t(lang, "evidence_context_auto", item=name))
            chain.append(_t(lang, "chain_auto", name=name))
        else:
            evidence.append(_t(lang, "evidence_context_script", item=name))
            chain.append(_t(lang, "chain_script", name=name))
        if full_trace is not None and _trace_mentions_entity(full_trace, entity_id):
            evidence.append(_t(lang, "evidence_trace_action", entity_id=entity_id))
        chain.append(_t(lang, "chain_action", entity_id=entity_id, change=change))
        # trigger hint from trace
        trigger = None
        if isinstance(full_trace, dict):
            trigger = full_trace.get("trigger") or (full_trace.get("trace") or {}).get("trigger")
        if isinstance(trigger, dict) and (trigger.get("entity_id") or trigger.get("description")):
            chain.insert(0, _t(lang, "chain_sensor"))
    elif time_near_auto and confidence == "unknown":
        cause_type = "automation" if not str(time_near_auto).startswith("script:") else "script"
        confidence = "possible"
        name = str(time_near_auto).removeprefix("script:")
        evidence.append(_t(lang, "evidence_time_near", item=name))
        chain.append(_t(lang, "chain_auto" if cause_type == "automation" else "chain_script", name=name))
        chain.append(_t(lang, "chain_action", entity_id=entity_id, change=change))

    if not traces_allowed:
        missing.append(_t(lang, "missing_traces_perm"))
    elif context_id and not matched_trace and cause_type in {"unknown", "user"}:
        missing.append(_t(lang, "missing_trace"))
    if not hints and not evidence:
        missing.append(_t(lang, "missing_logbook"))

    if confidence == "confirmed" and cause_type == "automation":
        summary = _t(lang, "summary_auto", entity_id=entity_id, change=change, name=name or "?")
    elif confidence == "confirmed" and cause_type == "script":
        summary = _t(lang, "summary_script", entity_id=entity_id, change=change, name=name or "?")
    elif confidence == "confirmed" and cause_type == "user":
        summary = _t(lang, "summary_user", entity_id=entity_id, change=change)
    elif confidence == "possible":
        summary = _t(lang, "summary_possible", entity_id=entity_id, change=change)
    else:
        summary = _t(lang, "summary_unknown", entity_id=entity_id, change=change)
        cause_type = "unknown"
        confidence = "unknown"

    return {
        "entity_id": entity_id,
        "change": change,
        "when": when,
        "cause_type": cause_type,
        "confidence": confidence,
        "chain": chain,
        "evidence": evidence,
        "missing_evidence": missing,
        "summary": summary,
        "context": {
            "id": context_id or None,
            "parent_id": parent_id or None,
            "user_id": user_id or None,
        },
    }


async def run_tool(args: dict, *, cfg: dict | None = None) -> str:
    cfg = cfg or load_config()
    lang = _lang(cfg)
    entity_id = str((args or {}).get("entity_id") or "").strip()
    if not entity_id or "." not in entity_id:
        return json.dumps({"ok": False, "error": _t(lang, "no_entity")}, ensure_ascii=False)

    end = _parse_dt(args.get("end_time")) or datetime.now(timezone.utc)
    start = _parse_dt(args.get("start_time"))
    if start is None:
        start = end - timedelta(hours=_DEFAULT_LOOKBACK_HOURS)
    # clamp lookback
    if (end - start) > timedelta(hours=_MAX_LOOKBACK_HOURS):
        start = end - timedelta(hours=_MAX_LOOKBACK_HOURS)

    from_state, to_state = _wanted_transition(args.get("event"))

    try:
        rows = await _fetch_history(entity_id, start, end)
    except Exception as exc:
        log.exception("history fetch failed")
        return json.dumps({"ok": False, "error": f"history failed: {exc}"}, ensure_ascii=False)

    if not rows:
        return json.dumps({
            "ok": True,
            "entity_id": entity_id,
            "change": "?",
            "cause_type": "unknown",
            "confidence": "unknown",
            "chain": [],
            "evidence": [],
            "missing_evidence": [_t(lang, "no_history")],
            "summary": _t(lang, "summary_unknown", entity_id=entity_id, change="?"),
        }, ensure_ascii=False)

    prev, cur = _find_transition(
        rows, from_state=from_state, to_state=to_state, start=start, end=end,
    )
    if not cur:
        # fallback: last state change of any kind
        prev, cur = _find_transition(rows, from_state=None, to_state=None, start=start, end=end)
    if not cur:
        return json.dumps({
            "ok": True,
            "entity_id": entity_id,
            "change": "?",
            "cause_type": "unknown",
            "confidence": "unknown",
            "chain": [],
            "evidence": [],
            "missing_evidence": [_t(lang, "no_transition")],
            "summary": _t(lang, "summary_unknown", entity_id=entity_id, change="?"),
        }, ensure_ascii=False)

    when = _state_ts(cur) or end
    w_start, w_end = _window_around(when)
    try:
        logbook = await _fetch_logbook(entity_id, w_start, w_end)
    except Exception:
        log.exception("logbook fetch failed")
        logbook = []

    ctx = _ctx(cur)
    context_id = str(ctx.get("id") or "")
    parent_id = str(ctx.get("parent_id") or "")

    traces_allowed = "automations" in hta.enabled_categories(cfg)
    matched_trace = None
    full_trace = None
    time_near_auto = None

    hints = _logbook_hints(logbook, entity_id=entity_id, when=when)
    prefer_item = None
    prefer_domain = "automation"
    for h in hints:
        aid = _automation_id_from_text(f"{h.get('entity_id')} {h.get('message')}")
        if aid and aid.startswith("script:"):
            prefer_domain = "script"
            prefer_item = aid.split(":", 1)[1]
            break
        if aid:
            prefer_item = aid
            break
        if h.get("domain") == "automation" and h.get("entity_id"):
            prefer_item = str(h["entity_id"]).removeprefix("automation.")
            break

    if traces_allowed:
        try:
            listed = await _list_traces(prefer_domain, prefer_item)
            matched_trace = _pick_trace(
                listed, context_id=context_id, parent_id=parent_id, around=when,
            )
            if matched_trace is None and prefer_domain == "automation":
                listed_s = await _list_traces("script", None)
                matched_trace = _pick_trace(
                    listed_s, context_id=context_id, parent_id=parent_id, around=when,
                )
                if matched_trace:
                    prefer_domain = "script"
            if matched_trace and not (context_id or parent_id):
                # time-near only
                item = matched_trace.get("item_id") or prefer_item
                if item:
                    time_near_auto = (
                        f"script:{item}" if prefer_domain == "script" else str(item)
                    )
            if matched_trace:
                item_id = str(
                    matched_trace.get("item_id")
                    or prefer_item
                    or ""
                )
                run_id = str(matched_trace.get("run_id") or matched_trace.get("id") or "")
                if item_id and run_id:
                    try:
                        full_trace = await _get_trace(prefer_domain, item_id, run_id)
                    except Exception:
                        log.debug("trace/get failed", exc_info=True)
                # If only time proximity (no shared context), downgrade later via build_report
                if matched_trace and not context_id and not parent_id:
                    time_near_auto = time_near_auto or (
                        f"script:{item_id}" if prefer_domain == "script" else item_id
                    )
                    # keep matched_trace only if context matched — else use time_near
                    tid = str(
                        matched_trace.get("context_id")
                        or ((matched_trace.get("context") or {}) if isinstance(matched_trace.get("context"), dict) else {}).get("id")
                        or ""
                    )
                    if tid and tid not in {context_id, parent_id}:
                        matched_trace = None
                    elif not tid:
                        matched_trace = None
        except Exception:
            log.exception("traces fetch failed")
            missing_traces_err = True
        else:
            missing_traces_err = False
    else:
        missing_traces_err = False

    report = build_report(
        entity_id=entity_id,
        prev=prev,
        cur=cur,
        logbook=logbook,
        traces_allowed=traces_allowed,
        matched_trace=matched_trace,
        full_trace=full_trace,
        time_near_auto=time_near_auto,
        lang=lang,
    )
    if missing_traces_err and _t(lang, "missing_trace") not in report["missing_evidence"]:
        report["missing_evidence"].append(_t(lang, "missing_trace"))
    report["ok"] = True
    return json.dumps(report, ensure_ascii=False, default=str)
