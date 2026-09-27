"""Compact digital twin of the home — entities, areas, aliases, freshness.

Built from HA states + registry caches. The LLM sees only a relevant snippet,
never the full dump.

Matching priority (name-first):
  1. friendly name (exact / token coverage, including numbers)
  2. area
  3. device name
  4. entity_id slug (weak fallback only)
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

# Generic filler words — domain hints, not distinctive name tokens.
GENERIC_TOKENS = frozenset({
    "lumina", "lumini", "lumin", "bec", "becuri", "lampa", "lampe", "lamp",
    "light", "lights", "led", "switch", "switches", "releu", "releu",
    "the", "a", "an", "din", "in", "la", "pe", "cu", "and", "or",
})


def fold(text: str) -> str:
    """Lowercase + strip diacritics for fuzzy matching."""
    raw = (text or "").translate(_DIACRITICS).lower()
    raw = "".join(c for c in unicodedata.normalize("NFD", raw) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", raw).strip()


def tokenize(text: str) -> list[str]:
    """Split into match tokens. Keeps digits (1, 2) and short alphanumerics (l1)."""
    out: list[str] = []
    for t in re.split(r"[^\w]+", fold(text)):
        if not t:
            continue
        if t.isdigit() or any(ch.isdigit() for ch in t) or len(t) >= 2:
            out.append(t)
    return out


def distinctive_tokens(tokens: list[str]) -> list[str]:
    """Tokens that actually discriminate entities (drop generic light words)."""
    return [t for t in tokens if t not in GENERIC_TOKENS]


@dataclass
class EntityNode:
    entity_id: str
    domain: str
    name: str
    area: str = ""
    area_id: str = ""
    state: str = ""
    device_name: str = ""
    tokens: list[str] = field(default_factory=list)  # legacy: name+area(+weak slug)
    name_tokens: list[str] = field(default_factory=list)
    area_tokens: list[str] = field(default_factory=list)
    device_tokens: list[str] = field(default_factory=list)
    slug_tokens: list[str] = field(default_factory=list)
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
        slug = eid.split(".", 1)[-1].replace("_", " ")
        name_tokens = tokenize(name)
        area_tokens = tokenize(area)
        device_tokens = tokenize(device_name)
        slug_tokens = tokenize(slug)
        # Legacy bag: name + area + device (NOT slug) so old callers stay sensible
        tokens = list(dict.fromkeys(name_tokens + area_tokens + device_tokens + [domain]))
        out.append(EntityNode(
            entity_id=eid,
            domain=domain,
            name=name,
            area=area,
            area_id=area_id,
            state=state_val,
            device_name=device_name,
            tokens=tokens,
            name_tokens=name_tokens,
            area_tokens=area_tokens,
            device_tokens=device_tokens,
            slug_tokens=slug_tokens,
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


def _token_in_list(tok: str, bag: list[str]) -> bool:
    if not tok:
        return False
    if tok in bag:
        return True
    # Allow "dormitor1" ≈ "dormitor"+"1" already tokenized separately
    return False


def score_entity(node: EntityNode, query_tokens: list[str], *, area_hint: str = "") -> float:
    """Name-first score. entity_id slug is a weak signal only."""
    if not query_tokens:
        return 0.0

    name_f = fold(node.name)
    name_toks = node.name_tokens or tokenize(node.name)
    area_toks = node.area_tokens or tokenize(node.area)
    device_toks = node.device_tokens or tokenize(node.device_name)
    slug_toks = node.slug_tokens or tokenize(node.entity_id.split(".", 1)[-1])

    # Exact / near-exact friendly name (all distinctive query tokens in name)
    dist = distinctive_tokens(query_tokens)
    name_hits = 0
    area_hits = 0
    device_hits = 0
    slug_hits = 0
    numeric_ok = True
    score = 0.0

    for tok in query_tokens:
        is_digit = tok.isdigit() or (len(tok) <= 3 and any(c.isdigit() for c in tok))
        if _token_in_list(tok, name_toks) or tok in name_f.split():
            score += 4.0 if not is_digit else 5.0
            name_hits += 1
        elif _token_in_list(tok, area_toks):
            score += 2.0
            area_hits += 1
        elif _token_in_list(tok, device_toks):
            score += 1.5
            device_hits += 1
        elif _token_in_list(tok, slug_toks):
            # Weak: technical id must not beat a real friendly-name match
            score += 0.4
            slug_hits += 1
        elif is_digit:
            # Query asked for a number that this entity doesn't carry → hard penalty
            numeric_ok = False
            score -= 3.0

    if name_hits == 0 and area_hits == 0 and device_hits == 0 and slug_hits == 0:
        return 0.0

    # Cap total slug contribution so releu_living_* can't outrank "Bec living"
    if slug_hits and name_hits == 0:
        score = min(score, 1.2 + 0.4 * max(0, slug_hits - 1))

    # Phrase / full-name bonuses
    q_phrase = " ".join(query_tokens)
    q_dist_phrase = " ".join(distinctive_tokens(query_tokens) or query_tokens)
    if q_phrase and q_phrase == name_f:
        score += 6.0
    elif q_dist_phrase and q_dist_phrase == name_f:
        score += 4.0
    elif q_phrase and q_phrase in name_f and len(q_phrase) >= 4:
        score += 3.0
    elif q_dist_phrase and q_dist_phrase in name_f and len(q_dist_phrase) >= 4:
        score += 2.0

    # Prefer entities whose friendly name covers every query token (incl. bec/lamp)
    all_in_name = all(
        _token_in_list(t, name_toks) or t in name_f.split()
        for t in query_tokens
    )
    if all_in_name and query_tokens:
        score += 3.0 + 0.5 * len(query_tokens)

    if dist:
        covered = sum(1 for t in dist if _token_in_list(t, name_toks) or t in name_f.split())
        coverage = covered / len(dist)
        score *= 0.55 + 0.45 * coverage
        if coverage >= 1.0 and name_hits >= len(dist):
            score += 2.0
    else:
        # Only generics in query — weak match
        score *= 0.5

    if area_hint:
        ah = fold(area_hint)
        area_f = fold(node.area)
        if ah and area_f:
            if ah == area_f or ah in area_f or area_f in ah:
                score += 2.5
            else:
                score -= 1.5

    if not numeric_ok:
        score *= 0.35

    if not node.available:
        score *= 0.4

    # Prefer light domain when query mentions light words
    if any(t in {"light", "lights", "lumina", "lumini", "bec", "lampa", "lamp"} for t in query_tokens):
        if node.domain == "light":
            score += 0.3

    return max(0.0, score)


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
        if hard_area and area_f:
            na = fold(node.area)
            if not na or (area_f not in na and na not in area_f):
                continue
        s = score_entity(node, q_tokens, area_hint=area)
        if s > 0:
            ranked.append((node, s))
    ranked.sort(key=lambda x: (-x[1], x[0].entity_id))
    if ranked:
        top = ranked[0][1]
        # Tighter margin: keep near-ties only
        margin = max(1.2, top * 0.22)
        ranked = [(n, s) for n, s in ranked if top - s <= margin]
    return ranked[: max(1, limit)]


def pick_targets(
    hits: list[tuple[EntityNode, float]],
    *,
    min_score: float = 3.5,
    gap_min: float = 1.5,
    ratio_max: float = 0.85,
) -> tuple[list[str], str]:
    """Decide unique vs ambiguous targets from ranked hits.

    Returns (entity_ids, mode) where mode is 'unique' | 'clarify' | 'weak'.
    """
    if not hits:
        return [], "weak"
    top_n, top_s = hits[0]
    if top_s < min_score:
        # Keep weak candidates for agent context but don't auto-act / false-clarify
        return [top_n.entity_id], "weak"

    close = [(n, s) for n, s in hits if top_s - s < gap_min]
    if len(close) == 1:
        return [top_n.entity_id], "unique"

    second_s = close[1][1] if len(close) > 1 else 0.0
    ratio = (second_s / top_s) if top_s > 0 else 1.0
    if top_s - second_s >= gap_min or ratio < ratio_max:
        return [top_n.entity_id], "unique"

    # Real ambiguity — only near peers
    return [n.entity_id for n, _ in close[:5]], "clarify"


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
            lines.append(
                f"- {node.entity_id} | {node.name} | {node.area or '-'} | {node.state} | score={score:.1f}"
            )
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
