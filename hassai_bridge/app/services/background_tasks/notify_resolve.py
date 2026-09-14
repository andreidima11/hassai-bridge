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
_SKIP_NOTIFY = frozenset({
    "notify",
    "persistent_notification",
    "send_message",
    "create",
    "dismiss",
})


def normalize_notify_service(raw: str) -> str:
    service = str(raw or "").strip()
    if not service:
        return ""
    if "." not in service:
        service = f"notify.{service}"
    return service


def _notify_services_from_payload(services_payload: Any) -> set[str]:
    """Return notify.* service ids from GET /services (phones + custom targets)."""
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
            if not key or key.lower() in _SKIP_NOTIFY:
                continue
            out.add(f"notify.{key}")
    return out


def _notify_services_from_states(states: Any) -> set[str]:
    """HA 2024+ may expose notify targets as notify.* entities."""
    out: set[str] = set()
    if not isinstance(states, list):
        return out
    for st in states:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "").strip()
        if not eid.startswith("notify."):
            continue
        tail = eid.split(".", 1)[1].lower()
        if tail in _SKIP_NOTIFY or "persistent" in tail:
            continue
        out.add(eid)
    return out


def _phone_like(services: set[str]) -> set[str]:
    """Prefer Companion / mobile-looking targets when falling back."""
    phones = {s for s in services if "mobile_app_" in s.lower()}
    return phones or services


def _tracker_suffix(tracker: str) -> str:
    eid = str(tracker or "").strip()
    if "." in eid:
        return eid.split(".", 1)[1].strip()
    return eid


def _candidates_for_suffix(suffix: str) -> list[str]:
    suffix = str(suffix or "").strip()
    if not suffix:
        return []
    # Common Companion + some custom notify names (e.g. notify.sm_s938b).
    return [
        f"notify.mobile_app_{suffix}",
        f"notify.{suffix}",
        f"notify.mobile_app_{suffix.lower()}",
        f"notify.{suffix.lower()}",
    ]


def _pick_matching(available: set[str], suffixes: list[str]) -> str:
    if not suffixes:
        return ""
    # Exact candidate hits first
    for suffix in suffixes:
        for cand in _candidates_for_suffix(suffix):
            if cand in available:
                return cand
    # Fuzzy: service name contains tracker suffix
    avail_l = {s: s for s in available}
    for suffix in suffixes:
        needle = suffix.lower()
        if len(needle) < 3:
            continue
        for full in available:
            tail = full.split(".", 1)[-1].lower()
            if needle in tail or tail.endswith(needle):
                return avail_l[full]
    return ""


def _person_matches(attrs: dict, *, ha_id: str, owner_id: str, display: str) -> bool:
    uid = str(attrs.get("user_id") or "").strip()
    if ha_id and uid and uid == ha_id:
        return True
    name = str(attrs.get("friendly_name") or "").strip().lower()
    entity_tail = ""
    eid = str(attrs.get("_entity_id") or "")
    if eid.startswith("person."):
        entity_tail = eid.split(".", 1)[1].replace("_", " ").lower()
    needles = [
        n for n in (
            display.lower(),
            owner_id.lower().replace("_", " "),
            owner_id.lower(),
        )
        if n and n not in ("default", "webui", "admin")
    ]
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
    available: set[str],
) -> str:
    trackers = person_attrs.get("device_trackers") or []
    if isinstance(trackers, str):
        trackers = [trackers]
    if not isinstance(trackers, list):
        return ""
    suffixes = [_tracker_suffix(str(t)) for t in trackers if str(t).strip()]
    picked = _pick_matching(available, suffixes)
    if picked:
        return picked
    # No service catalog (HA briefly unavailable) — still try Companion naming.
    if not available and suffixes:
        return f"notify.mobile_app_{suffixes[0]}"
    return ""


async def resolve_notify_service(
    owner_id: str,
    *,
    cfg: dict | None = None,
    preferred: str | None = None,
) -> str:
    """Settings override → preferred (task) → person/trackers → sole phone fallback."""
    cfg = cfg or load_config()
    bg = manager._bg_cfg(cfg)
    override = normalize_notify_service(str(bg.get("notify_service") or ""))
    if override:
        return override

    preferred_n = normalize_notify_service(str(preferred or ""))
    if preferred_n:
        return preferred_n

    owner_id = str(owner_id or "").strip()
    if not owner_id:
        return ""

    prof = get_profile(owner_id) or {}
    ha_id = str(prof.get("ha_id") or "").strip()
    display = str(prof.get("display_name") or owner_id).strip()

    try:
        from services import homeassistant as ha

        if not ha.is_available():
            log.warning("resolve_notify_service: HA unavailable for user %s", owner_id)
            return ""
        states = await ha._core("GET", "/states")
        try:
            services_payload = await ha._core("GET", "/services")
        except Exception:
            services_payload = []
    except Exception as exc:
        log.warning("resolve_notify_service HA fetch failed for %s: %s", owner_id, exc)
        return ""

    available = _notify_services_from_payload(services_payload) | _notify_services_from_states(states)
    if not isinstance(states, list):
        states = []

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
        picked = pick_notify_from_person(person_attrs=attrs, available=available)
        if picked:
            log.info(
                "resolved notify %s for user %s via %s",
                picked,
                owner_id,
                attrs.get("_entity_id"),
            )
            return picked

    phones = _phone_like(available)
    # Matched person but naming drifted — sole phone target.
    if matched_attrs and len(phones) == 1:
        only = next(iter(phones))
        log.info("resolved sole phone notify %s for matched user %s", only, owner_id)
        return only

    # Single-phone homes often have no person↔tracker link; still notify.
    if len(phones) == 1:
        only = next(iter(phones))
        log.info(
            "resolved sole phone notify %s for user %s (no person/tracker match; ha_id=%s)",
            only,
            owner_id,
            ha_id or "—",
        )
        return only

    log.warning(
        "resolve_notify_service: no notify for user %s (ha_id=%s, persons=%s, targets=%s)",
        owner_id,
        ha_id or "—",
        len(matched_attrs),
        sorted(phones)[:8],
    )
    return ""
