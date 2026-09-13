"""Resolve which HA notify.* service to use for a Bridge user."""

from __future__ import annotations

import logging
import re
from typing import Any

from core.config import load_config
from core.identity import get_profile
from services.background_tasks import manager

log = logging.getLogger("hassai.bg_notify")

_MOBILE_RE = re.compile(r"^mobile_app_.+", re.I)


def normalize_notify_service(raw: str) -> str:
    service = str(raw or "").strip()
    if not service:
        return ""
    if "." not in service:
        service = f"notify.{service}"
    return service


def _notify_mobile_services(services_payload: Any) -> set[str]:
    """Return full service ids like notify.mobile_app_pixel from GET /services."""
    out: set[str] = set()
    if not isinstance(services_payload, list):
        return out
    for block in services_payload:
        if not isinstance(block, dict):
            continue
        if str(block.get("domain") or "").lower() != "notify":
            continue
        services = block.get("services") or {}
        if not isinstance(services, dict):
            continue
        for name in services:
            key = str(name or "").strip()
            if _MOBILE_RE.match(key):
                out.add(f"notify.{key}")
    return out


def _tracker_to_notify(tracker: str) -> str:
    eid = str(tracker or "").strip()
    if not eid.startswith("device_tracker."):
        return ""
    suffix = eid.split(".", 1)[1].strip()
    if not suffix:
        return ""
    return f"notify.mobile_app_{suffix}"


def _person_matches(attrs: dict, *, ha_id: str, owner_id: str, display: str) -> bool:
    uid = str(attrs.get("user_id") or "").strip()
    if ha_id and uid and uid == ha_id:
        return True
    name = str(attrs.get("friendly_name") or "").strip().lower()
    entity_tail = ""
    # caller may pass entity_id via attrs["_entity_id"]
    eid = str(attrs.get("_entity_id") or "")
    if eid.startswith("person."):
        entity_tail = eid.split(".", 1)[1].replace("_", " ").lower()
    needles = [n for n in (display.lower(), owner_id.lower().replace("_", " "), owner_id.lower()) if n]
    for needle in needles:
        if len(needle) < 2:
            continue
        if needle in name or (entity_tail and needle in entity_tail):
            return True
        if name and name in needle:
            return True
    return False


def pick_notify_from_person(
    *,
    person_attrs: dict,
    mobile_services: set[str],
) -> str:
    trackers = person_attrs.get("device_trackers") or []
    if isinstance(trackers, str):
        trackers = [trackers]
    if not isinstance(trackers, list):
        return ""
    for tracker in trackers:
        candidate = _tracker_to_notify(str(tracker))
        if candidate and candidate in mobile_services:
            return candidate
        # Tracker exists but service list empty/unavailable — still try Companion naming.
        if candidate and not mobile_services:
            return candidate
    return ""


async def resolve_notify_service(owner_id: str, *, cfg: dict | None = None) -> str:
    """Settings override first; else person → device_tracker → notify.mobile_app_*."""
    cfg = cfg or load_config()
    bg = manager._bg_cfg(cfg)
    override = normalize_notify_service(str(bg.get("notify_service") or ""))
    if override:
        return override

    owner_id = str(owner_id or "").strip()
    if not owner_id:
        return ""

    prof = get_profile(owner_id) or {}
    ha_id = str(prof.get("ha_id") or "").strip()
    display = str(prof.get("display_name") or owner_id).strip()

    try:
        from services import homeassistant as ha

        if not ha.is_available():
            return ""
        states = await ha._core("GET", "/states")
        try:
            services_payload = await ha._core("GET", "/services")
        except Exception:
            services_payload = []
    except Exception as exc:
        log.debug("resolve_notify_service HA fetch failed: %s", exc)
        return ""

    mobile = _notify_mobile_services(services_payload)
    if not isinstance(states, list):
        return ""

    matched_attrs: list[dict] = []
    for st in states:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        if not eid.startswith("person."):
            continue
        attrs = dict(st.get("attributes") or {})
        attrs["_entity_id"] = eid
        if _person_matches(attrs, ha_id=ha_id, owner_id=owner_id, display=display):
            matched_attrs.append(attrs)

    for attrs in matched_attrs:
        picked = pick_notify_from_person(person_attrs=attrs, mobile_services=mobile)
        if picked:
            log.info(
                "resolved notify %s for user %s via %s",
                picked,
                owner_id,
                attrs.get("_entity_id"),
            )
            return picked

    # Single-phone homes: if we matched the person but naming drifted, and there is
    # exactly one mobile notify service, use it.
    if matched_attrs and len(mobile) == 1:
        only = next(iter(mobile))
        log.info("resolved sole mobile notify %s for user %s", only, owner_id)
        return only

    return ""
