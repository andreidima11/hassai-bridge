"""
Knowledge Graph — Temporal entity-relationship graph for HASSAI Bridge.

Tracks entities (people, devices, locations, concepts) and their relationships
with temporal validity. Built on SQLite — no external dependencies.

Architecture:
  - Entities: nodes with type + properties
  - Relations: typed edges with valid_from/valid_to for temporal queries
  - Queries: entity-centric traversal with optional time filtering

Usage:
    from services.knowledge_graph import KnowledgeGraph

    kg = KnowledgeGraph(user_id="andrei")
    kg.add_entity("Ana", "person", {"relation": "soție"})
    kg.add_relation("Ana", "lives_in", "Apartament")
    kg.add_relation("Apartament", "has_device", "Bec Living", valid_from="2025-01")

    facts = kg.query("Ana")
    timeline = kg.timeline("Apartament")
"""

import json
import logging
import time
from datetime import date
from pathlib import Path
from contextlib import contextmanager
import sqlite3

log = logging.getLogger("hassai.knowledge_graph")

DB_PATH = Path(__file__).parent.parent / "data" / "hassai.db"


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def _db():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_graph_tables():
    """Create knowledge graph tables if they don't exist."""
    with _db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS kg_entities (
                id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'unknown',
                properties TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (id, user_id)
            );

            CREATE TABLE IF NOT EXISTS kg_relations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                predicate TEXT NOT NULL,
                object_id TEXT NOT NULL,
                valid_from TEXT,
                valid_to TEXT,
                confidence REAL NOT NULL DEFAULT 1.0,
                source TEXT NOT NULL DEFAULT 'auto',
                created_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_kg_ent_user
                ON kg_entities(user_id);
            CREATE INDEX IF NOT EXISTS idx_kg_rel_user
                ON kg_relations(user_id);
            CREATE INDEX IF NOT EXISTS idx_kg_rel_subject
                ON kg_relations(user_id, subject_id);
            CREATE INDEX IF NOT EXISTS idx_kg_rel_object
                ON kg_relations(user_id, object_id);
            CREATE INDEX IF NOT EXISTS idx_kg_rel_pred
                ON kg_relations(user_id, predicate);
            CREATE INDEX IF NOT EXISTS idx_kg_rel_valid
                ON kg_relations(valid_from, valid_to);
        """)


def _entity_id(name: str) -> str:
    """Normalize name into a stable entity ID."""
    return name.lower().strip().replace(" ", "_").replace("'", "").replace("'", "")


class KnowledgeGraph:
    """Per-user knowledge graph with temporal entity-relationship tracking."""

    def __init__(self, user_id: str):
        self.user_id = user_id

    # ── Entity operations ──

    def add_entity(self, name: str, entity_type: str = "unknown",
                   properties: dict | None = None) -> str:
        eid = _entity_id(name)
        now = time.time()
        props = json.dumps(properties or {}, ensure_ascii=False)
        with _db() as conn:
            existing = conn.execute(
                "SELECT id FROM kg_entities WHERE id = ? AND user_id = ?",
                (eid, self.user_id),
            ).fetchone()
            if existing:
                # Merge properties
                old_props = conn.execute(
                    "SELECT properties FROM kg_entities WHERE id = ? AND user_id = ?",
                    (eid, self.user_id),
                ).fetchone()
                merged = json.loads(old_props["properties"]) if old_props else {}
                merged.update(properties or {})
                conn.execute(
                    "UPDATE kg_entities SET entity_type = ?, properties = ?, updated_at = ? "
                    "WHERE id = ? AND user_id = ?",
                    (entity_type, json.dumps(merged, ensure_ascii=False), now, eid, self.user_id),
                )
            else:
                conn.execute(
                    "INSERT INTO kg_entities (id, user_id, name, entity_type, properties, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (eid, self.user_id, name, entity_type, props, now, now),
                )
        return eid

    def get_entity(self, name: str) -> dict | None:
        eid = _entity_id(name)
        with _db() as conn:
            row = conn.execute(
                "SELECT * FROM kg_entities WHERE id = ? AND user_id = ?",
                (eid, self.user_id),
            ).fetchone()
        if row:
            result = dict(row)
            result["properties"] = json.loads(result["properties"])
            return result
        return None

    def list_entities(self, entity_type: str | None = None, limit: int = 100) -> list[dict]:
        with _db() as conn:
            if entity_type:
                rows = conn.execute(
                    "SELECT * FROM kg_entities WHERE user_id = ? AND entity_type = ? "
                    "ORDER BY updated_at DESC LIMIT ?",
                    (self.user_id, entity_type, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM kg_entities WHERE user_id = ? ORDER BY updated_at DESC LIMIT ?",
                    (self.user_id, limit),
                ).fetchall()
        results = []
        for r in rows:
            d = dict(r)
            d["properties"] = json.loads(d["properties"])
            results.append(d)
        return results

    def delete_entity(self, name: str):
        eid = _entity_id(name)
        with _db() as conn:
            conn.execute("DELETE FROM kg_entities WHERE id = ? AND user_id = ?", (eid, self.user_id))
            conn.execute(
                "DELETE FROM kg_relations WHERE user_id = ? AND (subject_id = ? OR object_id = ?)",
                (self.user_id, eid, eid),
            )

    # ── Relation operations ──

    def add_relation(self, subject: str, predicate: str, obj: str,
                     valid_from: str | None = None, valid_to: str | None = None,
                     confidence: float = 1.0, source: str = "auto") -> int:
        sub_id = _entity_id(subject)
        obj_id = _entity_id(obj)
        pred = predicate.lower().strip().replace(" ", "_")
        now = time.time()

        # Auto-create entities if they don't exist
        self.add_entity(subject)
        self.add_entity(obj)

        with _db() as conn:
            # Check for existing identical active relation
            existing = conn.execute(
                "SELECT id FROM kg_relations "
                "WHERE user_id = ? AND subject_id = ? AND predicate = ? AND object_id = ? AND valid_to IS NULL",
                (self.user_id, sub_id, pred, obj_id),
            ).fetchone()

            if existing:
                return existing["id"]

            cursor = conn.execute(
                "INSERT INTO kg_relations "
                "(user_id, subject_id, predicate, object_id, valid_from, valid_to, confidence, source, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (self.user_id, sub_id, pred, obj_id, valid_from, valid_to, confidence, source, now),
            )
            return cursor.lastrowid

    def invalidate(self, subject: str, predicate: str, obj: str,
                   ended: str | None = None):
        sub_id = _entity_id(subject)
        obj_id = _entity_id(obj)
        pred = predicate.lower().strip().replace(" ", "_")
        ended = ended or date.today().isoformat()
        with _db() as conn:
            conn.execute(
                "UPDATE kg_relations SET valid_to = ? "
                "WHERE user_id = ? AND subject_id = ? AND predicate = ? AND object_id = ? AND valid_to IS NULL",
                (ended, self.user_id, sub_id, pred, obj_id),
            )

    # ── Query operations ──

    def query(self, name: str, as_of: str | None = None,
              direction: str = "both") -> list[dict]:
        """Get all relationships for an entity.

        direction: "outgoing" (entity → ?), "incoming" (? → entity), "both"
        as_of: ISO date — only return facts valid at that time
        """
        eid = _entity_id(name)
        results = []

        with _db() as conn:
            if direction in ("outgoing", "both"):
                q = (
                    "SELECT r.*, e.name as object_name, e.entity_type as object_type "
                    "FROM kg_relations r JOIN kg_entities e ON r.object_id = e.id AND r.user_id = e.user_id "
                    "WHERE r.user_id = ? AND r.subject_id = ?"
                )
                params = [self.user_id, eid]
                if as_of:
                    q += " AND (r.valid_from IS NULL OR r.valid_from <= ?) AND (r.valid_to IS NULL OR r.valid_to >= ?)"
                    params.extend([as_of, as_of])
                for row in conn.execute(q, params).fetchall():
                    results.append({
                        "direction": "outgoing",
                        "subject": name,
                        "predicate": row["predicate"],
                        "object": row["object_name"],
                        "object_type": row["object_type"],
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "confidence": row["confidence"],
                        "current": row["valid_to"] is None,
                    })

            if direction in ("incoming", "both"):
                q = (
                    "SELECT r.*, e.name as subject_name, e.entity_type as subject_type "
                    "FROM kg_relations r JOIN kg_entities e ON r.subject_id = e.id AND r.user_id = e.user_id "
                    "WHERE r.user_id = ? AND r.object_id = ?"
                )
                params = [self.user_id, eid]
                if as_of:
                    q += " AND (r.valid_from IS NULL OR r.valid_from <= ?) AND (r.valid_to IS NULL OR r.valid_to >= ?)"
                    params.extend([as_of, as_of])
                for row in conn.execute(q, params).fetchall():
                    results.append({
                        "direction": "incoming",
                        "subject": row["subject_name"],
                        "subject_type": row["subject_type"],
                        "predicate": row["predicate"],
                        "object": name,
                        "valid_from": row["valid_from"],
                        "valid_to": row["valid_to"],
                        "confidence": row["confidence"],
                        "current": row["valid_to"] is None,
                    })

        return results

    def query_current(self, name: str) -> list[dict]:
        """Get only currently valid facts about an entity."""
        eid = _entity_id(name)
        results = []
        with _db() as conn:
            for row in conn.execute(
                "SELECT r.*, eo.name as object_name, es.name as subject_name "
                "FROM kg_relations r "
                "LEFT JOIN kg_entities eo ON r.object_id = eo.id AND r.user_id = eo.user_id "
                "LEFT JOIN kg_entities es ON r.subject_id = es.id AND r.user_id = es.user_id "
                "WHERE r.user_id = ? AND (r.subject_id = ? OR r.object_id = ?) AND r.valid_to IS NULL",
                (self.user_id, eid, eid),
            ).fetchall():
                if row["subject_id"] == eid:
                    results.append(f"{name} → {row['predicate']} → {row['object_name']}")
                else:
                    results.append(f"{row['subject_name']} → {row['predicate']} → {name}")
        return results

    def timeline(self, name: str | None = None, limit: int = 50) -> list[dict]:
        """Get facts in chronological order, optionally filtered by entity."""
        with _db() as conn:
            if name:
                eid = _entity_id(name)
                rows = conn.execute(
                    "SELECT r.*, es.name as sub_name, eo.name as obj_name "
                    "FROM kg_relations r "
                    "JOIN kg_entities es ON r.subject_id = es.id AND r.user_id = es.user_id "
                    "JOIN kg_entities eo ON r.object_id = eo.id AND r.user_id = eo.user_id "
                    "WHERE r.user_id = ? AND (r.subject_id = ? OR r.object_id = ?) "
                    "ORDER BY r.valid_from ASC NULLS LAST LIMIT ?",
                    (self.user_id, eid, eid, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT r.*, es.name as sub_name, eo.name as obj_name "
                    "FROM kg_relations r "
                    "JOIN kg_entities es ON r.subject_id = es.id AND r.user_id = es.user_id "
                    "JOIN kg_entities eo ON r.object_id = eo.id AND r.user_id = eo.user_id "
                    "WHERE r.user_id = ? "
                    "ORDER BY r.valid_from ASC NULLS LAST LIMIT ?",
                    (self.user_id, limit),
                ).fetchall()

        return [
            {
                "subject": r["sub_name"],
                "predicate": r["predicate"],
                "object": r["obj_name"],
                "valid_from": r["valid_from"],
                "valid_to": r["valid_to"],
                "current": r["valid_to"] is None,
            }
            for r in rows
        ]

    # ── Stats ──

    def stats(self) -> dict:
        with _db() as conn:
            entities = conn.execute(
                "SELECT COUNT(*) as c FROM kg_entities WHERE user_id = ?", (self.user_id,)
            ).fetchone()["c"]
            relations = conn.execute(
                "SELECT COUNT(*) as c FROM kg_relations WHERE user_id = ?", (self.user_id,)
            ).fetchone()["c"]
            current = conn.execute(
                "SELECT COUNT(*) as c FROM kg_relations WHERE user_id = ? AND valid_to IS NULL",
                (self.user_id,),
            ).fetchone()["c"]
            types = conn.execute(
                "SELECT entity_type, COUNT(*) as c FROM kg_entities WHERE user_id = ? GROUP BY entity_type",
                (self.user_id,),
            ).fetchall()
            predicates = conn.execute(
                "SELECT DISTINCT predicate FROM kg_relations WHERE user_id = ? ORDER BY predicate",
                (self.user_id,),
            ).fetchall()

        return {
            "entities": entities,
            "relations": relations,
            "current_facts": current,
            "expired_facts": relations - current,
            "entity_types": {r["entity_type"]: r["c"] for r in types},
            "relation_types": [r["predicate"] for r in predicates],
        }

    # ── Build context string for LLM injection ──

    def build_context(self, entity_names: list[str] | None = None, max_facts: int = 20) -> str:
        """Build a compact context string from the knowledge graph.

        If entity_names provided, returns facts about those entities.
        Otherwise returns all current facts (up to max_facts).
        """
        lines = []

        with _db() as conn:
            if entity_names:
                for name in entity_names[:5]:
                    eid = _entity_id(name)
                    entity = conn.execute(
                        "SELECT * FROM kg_entities WHERE id = ? AND user_id = ?",
                        (eid, self.user_id),
                    ).fetchone()
                    if entity:
                        props = json.loads(entity["properties"])
                        props_str = ", ".join(f"{k}: {v}" for k, v in props.items() if v) if props else ""
                        type_str = entity["entity_type"]
                        header = f"• {entity['name']} ({type_str})"
                        if props_str:
                            header += f" [{props_str}]"
                        lines.append(header)

                    # Outgoing relations
                    for row in conn.execute(
                        "SELECT r.predicate, eo.name as obj_name "
                        "FROM kg_relations r "
                        "JOIN kg_entities eo ON r.object_id = eo.id AND r.user_id = eo.user_id "
                        "WHERE r.user_id = ? AND r.subject_id = ? AND r.valid_to IS NULL "
                        "ORDER BY r.created_at DESC LIMIT ?",
                        (self.user_id, eid, max_facts),
                    ).fetchall():
                        lines.append(f"  → {row['predicate'].replace('_', ' ')} → {row['obj_name']}")

                    # Incoming relations
                    for row in conn.execute(
                        "SELECT r.predicate, es.name as sub_name "
                        "FROM kg_relations r "
                        "JOIN kg_entities es ON r.subject_id = es.id AND r.user_id = es.user_id "
                        "WHERE r.user_id = ? AND r.object_id = ? AND r.valid_to IS NULL "
                        "ORDER BY r.created_at DESC LIMIT ?",
                        (self.user_id, eid, max_facts),
                    ).fetchall():
                        lines.append(f"  ← {row['sub_name']} → {row['predicate'].replace('_', ' ')}")
            else:
                # All current facts, grouped by subject
                rows = conn.execute(
                    "SELECT r.*, es.name as sub_name, eo.name as obj_name "
                    "FROM kg_relations r "
                    "JOIN kg_entities es ON r.subject_id = es.id AND r.user_id = es.user_id "
                    "JOIN kg_entities eo ON r.object_id = eo.id AND r.user_id = eo.user_id "
                    "WHERE r.user_id = ? AND r.valid_to IS NULL "
                    "ORDER BY r.created_at DESC LIMIT ?",
                    (self.user_id, max_facts),
                ).fetchall()

                current_subject = None
                for row in rows:
                    if row["sub_name"] != current_subject:
                        current_subject = row["sub_name"]
                        lines.append(f"• {current_subject}:")
                    lines.append(f"  → {row['predicate'].replace('_', ' ')} → {row['obj_name']}")

        return "\n".join(lines) if lines else ""
