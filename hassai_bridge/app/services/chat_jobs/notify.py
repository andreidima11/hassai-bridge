"""Strict per-user HA Companion notify for chat jobs."""

from __future__ import annotations

import logging
from typing import Any

from core.config import load_config
from core.identity import get_profile
from services.background_tasks.notify_resolve import (
    normalize_notify_service,
    pick_notify_from_person,
    _notify_services_from_payload,
    _notify_services_from_states,
    _person_matches,
)

log = logging.getLogger("hassai.chat_jobs.notify")


async def resolve_private_notify(
    owner_id: str,
    *,
    cfg: dict | None = None,
    preferred: str = "",
    ha_id: str = "",
) -> str:
    """Resolve notify.* only when confidently tied to this user.

    Order:
      1. preferred / profile.notify_service (explicit)
      2. person.user_id == ha_id → device_tracker → notify.mobile_app_*
    Never falls back to "sole phone in the house".
    """
    cfg = cfg or load_config()
    owner_id = str(owner_id or "").strip()
    preferred_n = normalize_notify_service(str(preferred or ""))
    if preferred_n:
        return preferred_n

    prof = get_profile(owner_id) or {}
    profile_svc = normalize_notify_service(str(prof.get("notify_service") or ""))
    if profile_svc:
        return profile_svc

    ha_id = str(ha_id or prof.get("ha_id") or "").strip()
    display = str(prof.get("display_name") or owner_id).strip()
    if not ha_id:
        log.info("private notify: no ha_id for %s — skip", owner_id)
        return ""

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
        log.warning("private notify HA fetch failed for %s: %s", owner_id, exc)
        return ""

    available = _notify_services_from_payload(services_payload) | _notify_services_from_states(states)
    if not isinstance(states, list):
        states = []

    # Strict: only person rows whose user_id matches ha_id
    matched: list[dict] = []
    for st in states:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "")
        if not eid.startswith("person."):
            continue
        attrs = dict(st.get("attributes") or {})
        uid = str(attrs.get("user_id") or "").strip()
        if uid and uid == ha_id:
            attrs["_entity_id"] = eid
            matched.append(attrs)

    if not matched:
        # Soft person match only if exactly one person matches heuristics AND ha_id present
        soft: list[dict] = []
        for st in states:
            if not isinstance(st, dict):
                continue
            eid = str(st.get("entity_id") or "")
            if not eid.startswith("person."):
                continue
            attrs = dict(st.get("attributes") or {})
            attrs["_entity_id"] = eid
            if _person_matches(attrs, ha_id=ha_id, owner_id=owner_id, display=display):
                soft.append(attrs)
        if len(soft) == 1 and str(soft[0].get("user_id") or "") == ha_id:
            matched = soft

    for attrs in matched:
        picked = pick_notify_from_person(person_attrs=attrs, available=available)
        if picked:
            log.info(
                "private notify %s for %s via %s",
                picked,
                owner_id,
                attrs.get("_entity_id"),
            )
            return picked

    log.info(
        "private notify unresolved for %s (ha_id=%s, matched_persons=%s)",
        owner_id,
        ha_id or "—",
        len(matched),
    )
    return ""


async def send_private_notify(
    service: str,
    *,
    title: str,
    message: str,
    url: str = "",
    tag: str = "",
) -> bool:
    service = normalize_notify_service(service)
    if not service or "." not in service:
        return False
    domain, svc = service.split(".", 1)
    body: dict[str, Any] = {
        "title": str(title or "")[:80],
        "message": str(message or "")[:220],
    }
    data: dict[str, Any] = {}
    if url:
        data["url"] = url
        data["clickAction"] = url
    if tag:
        data["tag"] = tag
    if data:
        body["data"] = data
    try:
        from services import homeassistant as ha

        await ha._core("POST", f"/services/{domain}/{svc}", json_body=body)
        return True
    except Exception:
        log.exception("send_private_notify failed service=%s", service)
        return False


async def probe_private_notify(owner_id: str, *, cfg: dict | None = None) -> dict:
    """Settings helper: show mapping status without sending."""
    cfg = cfg or load_config()
    prof = get_profile(owner_id) or {}
    service = await resolve_private_notify(
        owner_id,
        cfg=cfg,
        preferred=str(prof.get("notify_service") or ""),
        ha_id=str(prof.get("ha_id") or ""),
    )
    return {
        "ok": bool(service),
        "owner_id": owner_id,
        "ha_id": str(prof.get("ha_id") or ""),
        "notify_service": service or "",
        "reason": "" if service else "no_private_target",
    }
