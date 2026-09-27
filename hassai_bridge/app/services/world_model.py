"""Compact digital twin of the home — entities, areas, aliases, freshness.

Built from HA states + registry caches. The LLM sees only a relevant snippet,
never the full dump.
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

_INDEX_CACHE: dict[str, Any] = {"ts": 0.0, "entities": None, "areas": None}
_INDEX_TTL = 8.0

_DIACRITICS = str.maketrans({
    "ă": "a", "â": "a", "î": "i", "ș": "s", "ş": "s", "ț": "t", "ţ": "t",
    "Ă": "a", "Â": "a", "Î": "i", "Ș": "s", "Ş": "s", "Ț": "t", "Ţ": "t",
})


def fold(text: str) -> str:
    """Lowercase + strip diacritics for fuzzy matching."""
    raw = (text or "").translate(_DIACRITICS).lower()
    # Also NFD-strip any remaining combining marks
    raw = "".join(c for c in unicodedata.normalize("NFD", raw) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", raw).strip()


def tokenize(text: str) -> list[str]:
    return [t for t in re.split(r"[^\w]+", fold(text)) if len(t) >= 2]


@dataclass
class EntityNode:
    entity_id: str
    domain: str
    name: str
    area: str = ""
    area_id: str = ""
    state: str = ""
    device_name: str = ""
    tokens: list[str] = field(default_factory=list)
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


def invalidate() -> None:
    _INDEX_CACHE["ts"] = 0.0
    _INDEX_CACHE["entities"] = None
    _INDEX_CACHE["areas"] = None


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
        area = area_labels.get(area_id, "") if area_id else ""
        device_name = device_labels.get(device_id, "") if device_id else ""
        state_val = str(st.get("state") or "")
        available = state_val.lower() not in {"unavailable", "unknown", ""}
        tok_src = " ".join([eid, name, area, device_name, domain])
        tokens = tokenize(tok_src)
        out.append(EntityNode(
            entity_id=eid,
            domain=domain,
            name=name,
            area=area,
            area_id=area_id,
            state=state_val,
            device_name=device_name,
            tokens=tokens,
            available=available,
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
        _INDEX_CACHE["areas"] = area_labels
        _INDEX_CACHE["ts"] = now
        return nodes
    except Exception:
        log.debug("world_model load failed", exc_info=True)
        return list(cached or [])


def score_entity(node: EntityNode, query_tokens: list[str], *, area_hint: str = "") -> float:
    if not query_tokens:
        return 0.0
    name_f = fold(node.name)
    eid_f = fold(node.entity_id)
    area_f = fold(node.area)
    score = 0.0
    hits = 0
    for tok in query_tokens:
        if tok in name_f:
            score += 3.0
            hits += 1
        elif tok in eid_f:
            score += 2.0
            hits += 1
        elif tok in node.tokens:
            score += 1.5
            hits += 1
        elif tok in area_f:
            score += 1.0
            hits += 1
    if hits == 0:
        return 0.0
    coverage = hits / max(1, len(query_tokens))
    score *= 0.5 + 0.5 * coverage
    if area_hint:
        ah = fold(area_hint)
        if ah and ah in area_f:
            score += 2.5
        elif ah and area_f and ah not in area_f:
            score -= 1.0
    if not node.available:
        score *= 0.4
    # Prefer light over switch when both match equally and query says light
    if "light" in query_tokens or "lumin" in " ".join(query_tokens) or "bec" in query_tokens:
        if node.domain == "light":
            score += 0.3
    return score


def search(
    entities: list[EntityNode],
    query: str,
    *,
    domains: Iterable[str] | None = None,
    area: str = "",
    limit: int = 12,
    hard_area: bool = False,
) -> list[tuple[EntityNode, float]]:
    q_tokens = tokenize(query)
    allow = frozenset(domains) if domains else None
    area_f = fold(area) if area else ""
    ranked: list[tuple[EntityNode, float]] = []
    for node in entities:
        if allow and node.domain not in allow:
            continue
        if hard_area and area_f and area_f not in fold(node.area):
            continue
        s = score_entity(node, q_tokens, area_hint=area)
        if s > 0:
            ranked.append((node, s))
    ranked.sort(key=lambda x: (-x[1], x[0].entity_id))
    # Keep only near-top matches so a clear kitchen hit doesn't drag living along
    if ranked:
        top = ranked[0][1]
        margin = max(1.5, top * 0.25)
        ranked = [(n, s) for n, s in ranked if top - s <= margin]
    return ranked[: max(1, limit)]


def areas_summary(entities: list[EntityNode], *, limit: int = 24) -> list[str]:
    counts: dict[str, int] = {}
    for n in entities:
        if n.area:
            counts[n.area] = counts.get(n.area, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [f"{name} ({count})" for name, count in ranked[:limit]]


def snippet_for_query(
    entities: list[EntityNode],
    query: str,
    *,
    area: str = "",
    domains: Iterable[str] | None = None,
    limit: int = 10,
) -> str:
    """Compact house fragment for prompt injection."""
    hits = search(entities, query, domains=domains, area=area, limit=limit)
    if not hits and area:
        hits = search(entities, area, domains=domains, limit=limit)
    lines: list[str] = []
    if hits:
        lines.append("candidates:")
        for node, score in hits:
            lines.append(f"- {node.entity_id} | {node.name} | {node.area or '-'} | {node.state} | score={score:.1f}")
    areas = areas_summary(entities, limit=12)
    if areas:
        lines.append("areas: " + ", ".join(areas))
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
