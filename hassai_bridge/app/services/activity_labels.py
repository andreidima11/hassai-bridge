"""Human-readable activity labels for the Thinking timeline.

``tool_detail`` = what the model is about to do (from args).
``tool_result_preview`` = short outcome after the tool returns.
"""

from __future__ import annotations

import json
import re
from typing import Any


def clip_detail(value: Any, n: int = 56) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= n:
        return text
    return text[: n - 1] + "…"


def _lang(raw: str | None) -> str:
    return "ro" if str(raw or "").strip().lower().startswith("ro") else "en"


_MSG = {
    "en": {
        "found": "{n} found",
        "rows": "{n} rows",
        "lines": "{n} lines · {tail}",
        "no_lines": "no matching lines",
        "results": "{n} results",
        "packs_loaded": "Loaded: {packs}",
        "packs_none": "No new packs",
        "done": "Done",
        "ok": "OK",
        "called": "Called {what}",
    },
    "ro": {
        "found": "{n} găsite",
        "rows": "{n} rânduri",
        "lines": "{n} linii · {tail}",
        "no_lines": "nicio linie potrivită",
        "results": "{n} rezultate",
        "packs_loaded": "Încărcat: {packs}",
        "packs_none": "Niciun pack nou",
        "done": "Gata",
        "ok": "OK",
        "called": "Apelat {what}",
    },
}


def _t(lang: str, key: str, **kwargs) -> str:
    table = _MSG.get(_lang(lang)) or _MSG["en"]
    text = table.get(key) or _MSG["en"].get(key) or key
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def tool_detail(name: str, args: dict | None) -> str:
    """Args preview for a running/done tool step."""
    args = args or {}
    if name == "activate_toolkits":
        packs = args.get("packs")
        if isinstance(packs, list):
            return clip_detail(", ".join(str(p) for p in packs[:6]))
        return ""
    if name == "search_web":
        return clip_detail(args.get("query"))
    if name == "fetch_url":
        return clip_detail(args.get("url") or args.get("focus") or "")
    if name == "stock_quote":
        return clip_detail(args.get("symbols") or args.get("symbol") or "")
    if name == "stock_history":
        bits = [
            args.get("symbol") or "",
            args.get("period") or "",
            args.get("interval") or "",
            args.get("start") or "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "anaf_firma":
        return clip_detail(args.get("cui") or args.get("cif") or "")
    if name == "anaf_bilant":
        bits = [args.get("cui") or args.get("cif") or "", args.get("an") or args.get("year") or ""]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "generate_image":
        return clip_detail(args.get("prompt"))
    if name == "browser_interact":
        bits = [args.get("action") or "", args.get("url") or args.get("selector") or ""]
        return clip_detail(" ".join(str(b) for b in bits if b))
    if name == "request_enable_tools":
        return clip_detail(args.get("group") or args.get("reason") or "")
    if name == "run_skill":
        return clip_detail(args.get("skill_name"))
    if name == "background_tasks":
        action = str(args.get("action") or args.get("kind") or "").strip()
        title = str(args.get("title") or "").strip()
        entity = str(args.get("entity_id") or "").strip()
        entities = args.get("entity_ids") if isinstance(args.get("entity_ids"), list) else []
        if not entity and entities:
            entity = ", ".join(str(e) for e in entities[:2])
        bits = [b for b in (action, title, entity) if b]
        return clip_detail(" · ".join(bits))
    if name in {"media_list", "media_read", "media_delete"}:
        return clip_detail(args.get("path") or args.get("search") or "")
    if name in {"ha_read_file", "ha_write_file", "ha_replace_in_file", "ha_list_files"}:
        return clip_detail(args.get("path") or args.get("search") or args.get("subdir") or "")
    if name == "ha_list_entities":
        bits = [
            args.get("search") or "",
            args.get("domain") or "",
            args.get("area_name") or args.get("area_id") or "",
            f"state={args.get('state_filter')}" if args.get("state_filter") else "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_get_state":
        return clip_detail(args.get("entity_id") or args.get("search") or "")
    if name == "ha_explain_event":
        bits = [
            args.get("entity_id") or "",
            args.get("event") or "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_get_logs":
        source = str(args.get("source") or "core").strip()
        slug = str(args.get("slug") or args.get("addon") or "").strip()
        search = str(args.get("search") or "").strip()
        bits = [source]
        if slug:
            bits.append(slug)
        if search:
            bits.append(f"“{search}”")
        return clip_detail(" · ".join(bits))
    if name == "ha_call_service":
        call = f"{args.get('domain') or ''}.{args.get('service') or ''}".strip(".")
        entity = str(args.get("entity_id") or "").strip()
        return clip_detail(" ".join(p for p in (call, entity) if p))
    if name == "ha_update_entity":
        bits = [
            args.get("entity_id") or "",
            args.get("name") or args.get("area_name") or args.get("area_id") or "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_set_state":
        return clip_detail(f"{args.get('entity_id') or ''} → {args.get('state') or ''}".strip())
    if name == "ha_get_entity_registry":
        return clip_detail(args.get("entity_id"))
    if name == "ha_get_device":
        return clip_detail(args.get("device_id"))
    if name == "ha_update_device":
        bits = [
            args.get("device_id") or "",
            args.get("area_name") or args.get("area_id") or args.get("name_by_user") or "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_create_area":
        return clip_detail(args.get("name"))
    if name == "ha_update_area":
        return clip_detail(f"{args.get('area_id') or ''} {args.get('name') or ''}".strip())
    if name == "ha_create_label":
        return clip_detail(args.get("name"))
    if name == "ha_update_label":
        return clip_detail(f"{args.get('label_id') or ''} {args.get('name') or ''}".strip())
    if name == "ha_get_history":
        ids = args.get("entity_ids") if isinstance(args.get("entity_ids"), list) else []
        preview = args.get("entity_id") or (", ".join(str(i) for i in ids[:2]) if ids else "")
        hours = args.get("hours")
        return clip_detail(f"{preview} {hours}h".strip() if hours else preview)
    if name == "ha_get_logbook":
        bits = [args.get("entity_id") or "", f"{args.get('hours')}h" if args.get("hours") else ""]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_get_entity_source":
        return clip_detail(args.get("entity_id") or args.get("search") or args.get("domain"))
    if name == "ha_expose_entity":
        ids = args.get("entity_ids") if isinstance(args.get("entity_ids"), list) else []
        preview = args.get("entity_id") or (", ".join(str(i) for i in ids[:2]) if ids else "")
        flag = "show" if args.get("should_expose") else "hide"
        return clip_detail(f"{flag} {preview}".strip())
    if name in {"ha_trigger_automation", "ha_run_script", "ha_activate_scene"}:
        return clip_detail(args.get("entity_id"))
    if name == "ha_get_automation":
        return clip_detail(args.get("entity_id") or args.get("search") or args.get("name"))
    if name in {"ha_delete_automation", "ha_delete_script", "ha_delete_scene"}:
        return clip_detail(args.get("entity_id") or args.get("search") or args.get("name"))
    if name == "ha_create_floor":
        return clip_detail(args.get("name"))
    if name == "ha_update_floor":
        return clip_detail(f"{args.get('floor_id') or ''} {args.get('name') or ''}".strip())
    if name == "ha_get_config_entry":
        return clip_detail(args.get("entry_id"))
    if name == "ha_reload_config_entry":
        return clip_detail(args.get("entry_id"))
    if name == "ha_get_statistics":
        sid = args.get("statistic_id") or args.get("entity_id") or ""
        return clip_detail(f"{sid} {args.get('period') or 'hour'}".strip())
    if name == "ha_upsert_card":
        card = args.get("card") if isinstance(args.get("card"), dict) else {}
        bits = [
            args.get("view_path") or args.get("view_title") or "",
            args.get("section_index") if args.get("section_index") is not None else "",
            card.get("type") or "",
            card.get("entity") or "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b != ""))
    if name == "ha_delete_card":
        bits = [
            args.get("view_path") or args.get("view_title") or "",
            args.get("card_path") or "",
            args.get("card_index") if args.get("card_index") is not None else "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b != ""))
    if name == "ha_upsert_view":
        return clip_detail(
            args.get("title") or args.get("view_path") or args.get("path") or args.get("view_title")
        )
    if name == "ha_create_dashboard":
        return clip_detail(f"{args.get('title') or ''} {args.get('url_path') or ''}".strip())
    if name == "ha_delete_view":
        return clip_detail(args.get("view_path") or args.get("view_title") or args.get("view_index"))
    if name == "ha_update_dashboard":
        return clip_detail(f"{args.get('url_path') or ''} {args.get('title') or ''}".strip())
    if name == "ha_delete_dashboard":
        return clip_detail(args.get("url_path"))
    if name == "ha_append_card_yaml":
        card = args.get("card") if isinstance(args.get("card"), dict) else {}
        bits = [
            args.get("dashboard_url") or args.get("url_path") or "Overview",
            args.get("view_path") or args.get("view_title") or "",
            card.get("type") or "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    if name == "ha_get_dashboard":
        bits = [
            args.get("url_path") or "Overview",
            args.get("view_path") or args.get("view_title") or "",
        ]
        return clip_detail(" · ".join(str(b) for b in bits if b))
    for key in (
        "entity_id",
        "path",
        "url_path",
        "view_path",
        "suggestion_id",
        "what",
        "source",
        "domain",
        "search",
    ):
        val = args.get(key)
        if val:
            extra = args.get("search") if key == "domain" else None
            return clip_detail(f"{val} {extra}".strip() if extra else val)
    return ""


_SHOWING_RE = re.compile(r"showing\s+\d+-\d+\s+of\s+(\d+)", re.I)
_HA_HEADER_RE = re.compile(r"^\[Home Assistant — [^\]]+\]\s*", re.I | re.M)
_OK_CALLED_RE = re.compile(r"^OK:\s*called\s+(.+)$", re.I)


def _first_line(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if clean:
            return clean
    return ""


def _strip_tool_wrappers(text: str) -> str:
    """Drop HA/tool wrapper lines so the preview shows the real outcome."""
    raw = _HA_HEADER_RE.sub("", str(text or "")).strip()
    return re.sub(r"\n{3,}", "\n\n", raw).strip()


def _try_json(text: str) -> Any | None:
    raw = text.strip()
    if not raw or raw[0] not in "{[":
        return None
    try:
        return json.loads(raw)
    except Exception:
        start = raw.find("{")
        if start < 0:
            return None
        try:
            return json.loads(raw[start:])
        except Exception:
            return None


def _friendly_json_preview(data: dict, *, lang: str, max_len: int) -> str:
    """Summarize a JSON tool payload without dumping raw braces."""
    activated = data.get("activated")
    if isinstance(activated, list):
        if activated:
            packs = ", ".join(str(p) for p in activated[:8])
            return clip_detail(_t(lang, "packs_loaded", packs=packs), max_len)
        return clip_detail(_t(lang, "packs_none"), max_len)
    change = str(data.get("change") or "").strip()
    conf = str(data.get("confidence") or "").strip()
    cause = str(data.get("cause_type") or "").strip()
    bits = [b for b in (change, cause, conf) if b]
    if bits:
        return clip_detail(" · ".join(bits), max_len)
    for key in ("summary", "message", "status", "title"):
        val = data.get(key)
        if isinstance(val, str) and val.strip() and not val.strip().startswith("{"):
            return clip_detail(val, max_len)
    # Skip long router hints — prefer Done over dumping them.
    return clip_detail(_t(lang, "done"), max_len)


def tool_result_preview(
    name: str,
    content: str | None,
    *,
    lang: str | None = None,
    max_len: int = 100,
) -> str:
    """Short outcome line for a completed tool step (never dumps raw JSON)."""
    lang = _lang(lang)
    text = _strip_tool_wrappers(content or "")
    if not text:
        return ""
    if text.lower().startswith("error"):
        return clip_detail(text, max_len)

    if name == "activate_toolkits":
        data = _try_json(text)
        if isinstance(data, dict):
            return _friendly_json_preview(data, lang=lang, max_len=max_len)
        return clip_detail(_t(lang, "done"), max_len)

    if name == "ha_explain_event":
        data = _try_json(text)
        if isinstance(data, dict):
            return _friendly_json_preview(data, lang=lang, max_len=max_len)

    if name in {"ha_list_entities", "ha_list_entity_registry", "ha_list_devices", "ha_list_areas"}:
        m = _SHOWING_RE.search(text)
        if m:
            return clip_detail(_t(lang, "found", n=m.group(1)), max_len)
        lines = [
            ln for ln in text.splitlines()
            if ln.strip() and not ln.strip().lower().startswith("showing")
        ]
        if lines:
            return clip_detail(_t(lang, "rows", n=len(lines)), max_len)

    if name == "ha_get_state":
        state_m = re.search(r"\bstate\s*[:=]\s*(\S+)", text, re.I)
        eid_m = re.search(r"\bentity_id\s*[:=]\s*(\S+)", text, re.I)
        if eid_m and state_m:
            return clip_detail(f"{eid_m.group(1)} = {state_m.group(1)}", max_len)
        return clip_detail(_first_line(text), max_len)

    if name == "ha_get_logs":
        lines = [ln for ln in text.splitlines() if ln.strip() and not ln.startswith("#")]
        if not lines:
            return clip_detail(_t(lang, "no_lines"), max_len)
        return clip_detail(
            _t(lang, "lines", n=len(lines), tail=_first_line(lines[-1])),
            max_len,
        )

    if name == "ha_call_service":
        for line in text.splitlines():
            clean = line.strip()
            if not clean:
                continue
            m = _OK_CALLED_RE.match(clean)
            if m:
                return clip_detail(_t(lang, "called", what=m.group(1).strip()), max_len)
            if clean.lower().startswith("ok") or "called" in clean.lower():
                return clip_detail(clean, max_len)
        return clip_detail(_first_line(text) or _t(lang, "ok"), max_len)

    if name == "search_web":
        m = re.search(r"(\d+)\s+result", text, re.I)
        if m:
            return clip_detail(_t(lang, "results", n=m.group(1)), max_len)
        return clip_detail(_first_line(text), max_len)

    if name == "background_tasks":
        data = _try_json(text)
        if isinstance(data, dict):
            tid = str(data.get("task_id") or data.get("id") or "").strip()
            status = str(data.get("status") or "").strip()
            title = str(data.get("title") or "").strip()
            bits = [b for b in (status or _t(lang, "ok"), title, tid) if b]
            return clip_detail(" · ".join(bits), max_len)
        return clip_detail(_first_line(text), max_len)

    # Never leak raw JSON into the timeline.
    data = _try_json(text)
    if isinstance(data, dict):
        return _friendly_json_preview(data, lang=lang, max_len=max_len)
    if text.lstrip().startswith(("{", "[")):
        return clip_detail(_t(lang, "done"), max_len)

    return clip_detail(_first_line(text), max_len)
