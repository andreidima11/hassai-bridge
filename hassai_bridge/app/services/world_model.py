"""Compact digital twin of the home — controllable entities, areas, states.

Built from HA states + registry caches. Two consumers:

* the reflex: ``find_exact`` — an entity is a reflex target only when the
  user's phrase *is* its friendly name (or a learned alias). No scoring.
* the agent: ``index_block`` — the house index injected into context so the
  model resolves names itself, the way it did before any reflex existed.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

log = logging.getLogger("hassai.world_model")

CONTROL_DOMAINS = frozenset({
    "light", "switch", "cover", "lock", "climate", "media_player",
    "scene", "script", "fan", "input_boolean", "vacuum",
})

# Order used when the index must be trimmed: things people command by name first.
_DOMAIN_PRIORITY = (
    "light", "switch", "cover", "lock", "climate", "media_player",
    "fan", "vacuum", "input_boolean", "scene", "script",
)

_INDEX_CACHE: dict[str, Any] = {"ts": 0.0, "entities": None}
_INDEX_TTL = 8.0

_DIACRITICS = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "a", "Â": "a", "Î": "i", "Ș": "s", "Ş": "s", "Ț": "t", "Ţ": "t",
})

# Prepositions accepted between a name and its area: "lampa pat din dormitor 1".
_AREA_JOINERS = ("", "din ", "in ", "de la ", "from ", "in the ")


def fold(text: str) -> str:
    """Lowercase, strip diacritics and collapse whitespace."""
    raw = (text or "").translate(_DIACRITICS).lower()
    raw = "".join(c for c in unicodedata.normalize("NFD", raw) if unicodedata.category(c) != "Mn")
    raw = re.sub(r"[^\w\s]", " ", raw)
    return re.sub(r"\s+", " ", raw).strip()


def tokenize(text: str) -> list[str]:
    """Word tokens of the folded text (digits kept)."""
    return [t for t in fold(text).split(" ") if t]


@dataclass
class EntityNode:
    entity_id: str
    domain: str
    name: str
    area: str = ""
    area_id: str = ""
    state: str = ""
    device_name: str = ""
    available: bool = True
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    def label(self) -> str:
        bits = [self.name or self.entity_id]
        if self.area:
            bits.append(f"@{self.area}")
        bits.append(f"[{self.state or '?'}]")
        return " ".join(bits)

    def surfaces(self) -> set[str]:
        """Folded phrases that unambiguously denote this entity."""
        name = fold(self.name)
        out = {name} if name else set()
        area = fold(self.area)
        if name and area:
            for joiner in _AREA_JOINERS:
                out.add(f"{name} {joiner}{area}")
        return out


def build_from_rows(
    states: list[dict],
    *,
    registry: dict[str, dict] | None = None,
    area_labels: dict[str, str] | None = None,
    device_labels: dict[str, str] | None = None,
    domains: Iterable[str] | None = None,
    now: float | None = None,
) -> list[EntityNode]:
    """Pure builder — testable without live HA."""
    registry = registry or {}
    area_labels = area_labels or {}
    device_labels = device_labels or {}
    allow = frozenset(domains) if domains else CONTROL_DOMAINS
    now = now if now is not None else time.time()
    out: list[EntityNode] = []

    for st in states or []:
        if not isinstance(st, dict):
            continue
        eid = str(st.get("entity_id") or "").strip()
        if not eid or "." not in eid:
            continue
        domain = eid.split(".", 1)[0].lower()
        if domain not in allow:
            continue
        attrs = st.get("attributes") or {}
        reg = registry.get(eid) or {}
        if reg.get("disabled_by") or reg.get("hidden_by"):
            continue
        area_id = str(reg.get("area_id") or "").strip()
        device_id = str(reg.get("device_id") or "").strip()
        name = (
            str(reg.get("name") or "").strip()
            or str(attrs.get("friendly_name") or "").strip()
            or eid
        )
        state_val = str(st.get("state") or "")
        out.append(EntityNode(
            entity_id=eid,
            domain=domain,
            name=name,
            area=area_labels.get(area_id, "") if area_id else "",
            area_id=area_id,
            state=state_val,
            device_name=device_labels.get(device_id, "") if device_id else "",
            available=state_val.lower() not in {"unavailable", "unknown", ""},
            updated_at=now,
        ))
    return out


async def load_entities(*, force: bool = False) -> list[EntityNode]:
    """Load / refresh the in-memory house index from HA caches."""
    now = time.time()
    cached = _INDEX_CACHE.get("entities")
    if (
        not force
        and cached is not None
        and (now - float(_INDEX_CACHE.get("ts") or 0)) < _INDEX_TTL
    ):
        return cached

    from services import homeassistant as ha
    from services import entity_tools as et

    if not ha.is_available():
        return list(cached or [])

    try:
        states = await ha._fetch_states_cached()
        entities, areas, devices, _labels, *_rest = await ha._fetch_registry_bundle()
        area_labels, _ = et.index_areas(areas if isinstance(areas, list) else [])
        device_labels, _ = et.index_devices(devices if isinstance(devices, list) else [])
        reg = et.registry_by_entity_id(entities if isinstance(entities, list) else [])
        nodes = build_from_rows(
            states if isinstance(states, list) else [],
            registry=reg,
            area_labels=area_labels,
            device_labels=device_labels,
            now=now,
        )
        _INDEX_CACHE["entities"] = nodes
        _INDEX_CACHE["ts"] = now
        return nodes
    except Exception:
        log.debug("world_model load failed", exc_info=True)
        return list(cached or [])


def find_exact(
    entities: list[EntityNode],
    phrase: str,
    *,
    domains: Iterable[str] | None = None,
) -> list[EntityNode]:
    """Entities whose friendly name (optionally + area) equals ``phrase``.

    Returns every exact match so the caller can tell unique from ambiguous.
    """
    needle = fold(phrase)
    if not needle:
        return []
    allow = frozenset(domains) if domains else None
    return [
        n for n in entities
        if (allow is None or n.domain in allow) and needle in n.surfaces()
    ]


def by_id(entities: list[EntityNode], entity_id: str) -> EntityNode | None:
    eid = str(entity_id or "").strip().lower()
    return next((n for n in entities if n.entity_id == eid), None)


def areas_summary(entities: list[EntityNode], *, limit: int = 24) -> list[str]:
    counts: dict[str, int] = {}
    for n in entities:
        if n.area:
            counts[n.area] = counts.get(n.area, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f"{name} ({count})" for name, count in ranked[:limit]]


def index_block(
    entities: list[EntityNode],
    *,
    domains: Iterable[str] | None = None,
    limit: int = 100,
) -> str:
    """House index for the agent: one line per controllable entity.

    Grouped by area, ordered by domain priority when trimmed. The model does
    the name resolution; nothing here guesses which entity the user meant.
    """
    allow = frozenset(domains) if domains else None
    rows = [n for n in entities if allow is None or n.domain in allow]
    if not rows:
        return ""
    total = len(rows)
    if total > limit:
        prio = {d: i for i, d in enumerate(_DOMAIN_PRIORITY)}
        rows.sort(key=lambda n: (prio.get(n.domain, len(prio)), n.area, n.name))
        rows = rows[:limit]
    rows.sort(key=lambda n: (n.area or "~", n.domain, n.name))

    lines = ["entities (entity_id | name | area | state):"]
    for n in rows:
        state = n.state if n.available else "unavailable"
        lines.append(f"- {n.entity_id} | {n.name} | {n.area or '-'} | {state}")
    if total > len(rows):
        lines.append(
            f"(+{total - len(rows)} more — use ha_list_entities search=<name> for the rest)"
        )
    return "\n".join(lines)


def apply_state_event(entity_id: str, new_state: str) -> None:
    """Incremental update from HA state_changed events."""
    nodes = _INDEX_CACHE.get("entities")
    if not nodes:
        return
    eid = str(entity_id or "").strip()
    for node in nodes:
        if node.entity_id == eid:
            node.state = str(new_state or "")
            node.available = node.state.lower() not in {"unavailable", "unknown", ""}
            node.updated_at = time.time()
            break
