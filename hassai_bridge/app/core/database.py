import os
import sqlite3
import json
import time
import threading
from pathlib import Path
from contextlib import contextmanager

_DATA_DIR = Path(os.environ.get("HASSAI_DATA_DIR") or (Path(__file__).parent.parent / "data"))
DB_PATH = _DATA_DIR / "hassai.db"

CATEGORIES = [
    "personal_info",
    "preferences",
    "home_setup",
    "facts",
    "instructions",
    "context",
]

# Thread-local connection cache (#13)
_thread_local = threading.local()


def close_all_connections() -> None:
    """Close the current thread's cached SQLite connection (call before DB replace)."""
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
        try:
            delattr(_thread_local, "conn")
        except Exception:
            _thread_local.conn = None


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = getattr(_thread_local, "conn", None)
    if conn is not None:
        try:
            conn.execute("SELECT 1")  # verify still alive
            return conn
        except (sqlite3.ProgrammingError, sqlite3.OperationalError, sqlite3.DatabaseError):
            try:
                conn.close()
            except Exception:
                pass
            try:
                delattr(_thread_local, "conn")
            except Exception:
                _thread_local.conn = None
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    _thread_local.conn = conn
    return conn


@contextmanager
def get_db():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def init_db():
    with get_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'facts',
                content TEXT NOT NULL,
                keywords TEXT NOT NULL DEFAULT '',
                importance INTEGER NOT NULL DEFAULT 3,
                created_at REAL NOT NULL,
                last_accessed REAL NOT NULL,
                access_count INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'auto',
                active INTEGER NOT NULL DEFAULT 1
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_user ON memories(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_cat ON memories(user_id, category)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_mem_importance ON memories(user_id, importance DESC)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at REAL NOT NULL,
                session_id TEXT NOT NULL DEFAULT '',
                meta TEXT NOT NULL DEFAULT ''
            )
        """)

        # Migrate: add session_id column if missing (for existing DBs)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "session_id" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")
        if "meta" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN meta TEXT NOT NULL DEFAULT ''")

        conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_user ON conversations(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_session ON conversations(user_id, session_id)")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS memory_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                details TEXT DEFAULT '',
                created_at REAL NOT NULL
            )
        """)

        # ── Knowledge Graph tables ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS kg_entities (
                id TEXT NOT NULL,
                user_id TEXT NOT NULL,
                name TEXT NOT NULL,
                entity_type TEXT NOT NULL DEFAULT 'unknown',
                properties TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                PRIMARY KEY (id, user_id)
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_ent_user ON kg_entities(user_id)")

        conn.execute("""
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
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_user ON kg_relations(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_subject ON kg_relations(user_id, subject_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_object ON kg_relations(user_id, object_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_kg_rel_pred ON kg_relations(user_id, predicate)")

        # ── Migrate: add domain/topic columns to memories if missing ──
        mem_cols = [r[1] for r in conn.execute("PRAGMA table_info(memories)").fetchall()]
        if "domain" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN domain TEXT NOT NULL DEFAULT 'general'")
        if "topic" not in mem_cols:
            conn.execute("ALTER TABLE memories ADD COLUMN topic TEXT NOT NULL DEFAULT ''")

        # ── Usage statistics table ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS usage_stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                provider_name TEXT NOT NULL DEFAULT '',
                provider_type TEXT NOT NULL DEFAULT '',
                model TEXT NOT NULL DEFAULT '',
                tokens_prompt INTEGER NOT NULL DEFAULT 0,
                tokens_completion INTEGER NOT NULL DEFAULT 0,
                tokens_total INTEGER NOT NULL DEFAULT 0,
                response_time_ms INTEGER NOT NULL DEFAULT 0,
                stream INTEGER NOT NULL DEFAULT 0,
                search_used INTEGER NOT NULL DEFAULT 0,
                eco_mode INTEGER NOT NULL DEFAULT 0,
                secondary_used INTEGER NOT NULL DEFAULT 0,
                cache_hit_tokens INTEGER NOT NULL DEFAULT 0,
                cache_miss_tokens INTEGER NOT NULL DEFAULT 0,
                cost_usd REAL NOT NULL DEFAULT 0,
                route_reason TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_user ON usage_stats(user_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_provider ON usage_stats(provider_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_model ON usage_stats(model)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_time ON usage_stats(created_at)")

        # ── FTS5 virtual table for fast memory search (#14) ──
        try:
            conn.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content, keywords,
                    content='memories',
                    content_rowid='id'
                )
            """)
        except sqlite3.OperationalError:
            # FTS5 not available in this SQLite build — skip
            log_msg = "FTS5 not available in this SQLite build, using LIKE fallback"
            import logging
            logging.getLogger("hassai.db").warning(log_msg)

        # ── Schema version tracking ──
        conn.execute("""
            CREATE TABLE IF NOT EXISTS schema_version (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                version INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )
        """)
        from core.config import DB_SCHEMA_VERSION
        row = conn.execute("SELECT version FROM schema_version WHERE id = 1").fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO schema_version (id, version, updated_at) VALUES (1, ?, ?)",
                (DB_SCHEMA_VERSION, time.time()),
            )
        elif row["version"] < DB_SCHEMA_VERSION:
            # Migration v2 -> v3: add eco_mode and secondary_used columns
            if row["version"] < 3:
                try:
                    conn.execute("ALTER TABLE usage_stats ADD COLUMN eco_mode INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass  # column already exists
                try:
                    conn.execute("ALTER TABLE usage_stats ADD COLUMN secondary_used INTEGER NOT NULL DEFAULT 0")
                except sqlite3.OperationalError:
                    pass  # column already exists
            if row["version"] < 4:
                conv_cols = [r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
                if "meta" not in conv_cols:
                    conn.execute("ALTER TABLE conversations ADD COLUMN meta TEXT NOT NULL DEFAULT ''")
            if row["version"] < 5:
                for col in ("cache_hit_tokens", "cache_miss_tokens"):
                    try:
                        conn.execute(
                            f"ALTER TABLE usage_stats ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0"
                        )
                    except sqlite3.OperationalError:
                        pass
            if row["version"] < 6:
                for col, decl in (
                    ("cost_usd", "REAL NOT NULL DEFAULT 0"),
                    ("route_reason", "TEXT NOT NULL DEFAULT ''"),
                ):
                    try:
                        conn.execute(f"ALTER TABLE usage_stats ADD COLUMN {col} {decl}")
                    except sqlite3.OperationalError:
                        pass
            conn.execute(
                "UPDATE schema_version SET version = ?, updated_at = ? WHERE id = 1",
                (DB_SCHEMA_VERSION, time.time()),
            )


# ── FTS5 sync helpers (#2) ──

def _fts_sync(conn, memory_id: int):
    """Re-sync a single memory row into the FTS5 index."""
    try:
        row = conn.execute(
            "SELECT content, keywords FROM memories WHERE id = ?", (memory_id,)
        ).fetchone()
        if row:
            conn.execute("INSERT OR REPLACE INTO memories_fts(rowid, content, keywords) VALUES (?, ?, ?)",
                         (memory_id, row["content"], row["keywords"]))
    except sqlite3.OperationalError:
        pass  # FTS not available


def _fts_delete(conn, memory_id: int):
    """Remove a memory from the FTS5 index."""
    try:
        conn.execute("INSERT INTO memories_fts(memories_fts, rowid, content, keywords) VALUES('delete', ?, '', '')",
                     (memory_id,))
    except (sqlite3.OperationalError, sqlite3.DatabaseError):
        pass  # FTS not available or row not in index


def _escape_like(s: str) -> str:
    """Escape SQL LIKE special characters (#13)."""
    return s.replace("%", "\\%").replace("_", "\\_")


# ── Memory operations ──

def add_memory(user_id, content, category="facts", keywords="", importance=3,
               source="auto", domain="general", topic=""):
    now = time.time()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO memories
               (user_id, category, content, keywords, importance, created_at, last_accessed,
                access_count, source, active, domain, topic)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 1, ?, ?)""",
            (user_id, category, content, keywords.lower(), min(max(importance, 1), 5),
             now, now, source, domain, topic),
        )
        mem_id = cursor.lastrowid
        # Update FTS index (#14)
        try:
            conn.execute(
                "INSERT INTO memories_fts(rowid, content, keywords) VALUES (?, ?, ?)",
                (mem_id, content, keywords.lower()),
            )
        except sqlite3.OperationalError:
            pass  # FTS not available
        return mem_id


def get_memories(user_id, limit=50):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, category, content, keywords, importance, created_at,
                      last_accessed, access_count, source
               FROM memories WHERE user_id = ? AND active = 1
               ORDER BY importance DESC, last_accessed DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_memory(memory_id):
    """One memory row by id, including user_id so callers can check ownership."""
    with get_db() as conn:
        row = conn.execute(
            """SELECT id, user_id, category, content, keywords, importance, created_at,
                      last_accessed, access_count, source, active
               FROM memories WHERE id = ?""",
            (memory_id,),
        ).fetchone()
    return dict(row) if row else None


def get_memories_by_category(user_id, category, limit=20):
    with get_db() as conn:
        rows = conn.execute(
            """SELECT id, category, content, keywords, importance, created_at,
                      last_accessed, access_count, source
               FROM memories WHERE user_id = ? AND category = ? AND active = 1
               ORDER BY importance DESC, last_accessed DESC LIMIT ?""",
            (user_id, category, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def search_memories(user_id, query_keywords, limit=15):
    if not query_keywords:
        return get_memories(user_id, limit)

    with get_db() as conn:
        # Try FTS5 first (#14)
        try:
            # Sanitize keywords: strip FTS special chars (#12)
            safe_kws = [kw.replace('"', '').replace("'", "").strip() for kw in query_keywords if kw]
            safe_kws = [kw for kw in safe_kws if kw]
            fts_query = " OR ".join(f'"{kw}"' for kw in safe_kws) if safe_kws else ""
            if fts_query:
                fts_rows = conn.execute(
                    """SELECT rowid FROM memories_fts WHERE memories_fts MATCH ?""",
                    (fts_query,),
                ).fetchall()
                fts_ids = [r["rowid"] for r in fts_rows]
                if fts_ids:
                    placeholders = ",".join("?" * len(fts_ids))
                    rows = conn.execute(
                        f"""SELECT id, category, content, keywords, importance, created_at,
                                   last_accessed, access_count, source,
                                   (importance * 0.3
                                    + MIN(access_count, 10) * 0.05
                                    + MAX(0, 1.0 - (? - last_accessed) / 2592000.0) * 0.2
                                   ) as decay_score
                            FROM memories
                            WHERE user_id = ? AND active = 1 AND id IN ({placeholders})
                            ORDER BY decay_score DESC LIMIT ?""",
                        [time.time(), user_id] + fts_ids + [limit],
                    ).fetchall()
                    ids = [r["id"] for r in rows]
                    if ids:
                        ph = ",".join("?" * len(ids))
                        conn.execute(
                            f"UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id IN ({ph})",
                            [time.time()] + ids,
                        )
                    return [dict(r) for r in rows]
        except sqlite3.OperationalError:
            pass  # FTS not available, fall back to LIKE

        # Fallback: LIKE-based search (with escaped wildcards #13)
        keyword_clauses = " + ".join(
            ["(CASE WHEN keywords LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' THEN 1 ELSE 0 END)" for _ in query_keywords]
        )
        kw_params = []
        for kw in query_keywords:
            pattern = f"%{_escape_like(kw.lower())}%"
            kw_params.extend([pattern, pattern])

        # Parameters: keyword_clauses (relevance) + keyword_clauses (decay) + time + user_id + limit
        all_params = kw_params + kw_params + [time.time(), user_id, limit]

        # Memory decay: score combines keyword relevance + importance + recency + access frequency
        rows = conn.execute(
            f"""SELECT id, category, content, keywords, importance, created_at,
                       last_accessed, access_count, source,
                       ({keyword_clauses}) as relevance,
                       (importance * 0.3
                        + ({keyword_clauses}) * 0.4
                        + MIN(access_count, 10) * 0.05
                        + MAX(0, 1.0 - (? - last_accessed) / 2592000.0) * 0.2
                       ) as decay_score
                FROM memories WHERE user_id = ? AND active = 1
                ORDER BY decay_score DESC, relevance DESC LIMIT ?""",
            all_params,
        ).fetchall()

        ids = [r["id"] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE id IN ({placeholders})",
                [time.time()] + ids,
            )

    return [dict(r) for r in rows]


def update_memory(memory_id, content=None, category=None, keywords=None, importance=None):
    with get_db() as conn:
        fields, params = [], []
        if content is not None:
            fields.append("content = ?")
            params.append(content)
        if category is not None:
            fields.append("category = ?")
            params.append(category)
        if keywords is not None:
            fields.append("keywords = ?")
            params.append(keywords.lower())
        if importance is not None:
            fields.append("importance = ?")
            params.append(min(max(importance, 1), 5))
        if fields:
            params.append(memory_id)
            conn.execute(f"UPDATE memories SET {', '.join(fields)} WHERE id = ?", params)
            # Sync FTS5 index (#2)
            _fts_sync(conn, memory_id)


def deactivate_memory(memory_id):
    with get_db() as conn:
        conn.execute("UPDATE memories SET active = 0 WHERE id = ?", (memory_id,))
        _fts_delete(conn, memory_id)


def delete_memory(memory_id):
    with get_db() as conn:
        _fts_delete(conn, memory_id)
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))


def bulk_delete_memories(memory_ids: list[int]):
    """Delete multiple memories by ID list."""
    if not memory_ids:
        return 0
    with get_db() as conn:
        for mid in memory_ids:
            _fts_delete(conn, mid)
        placeholders = ",".join("?" * len(memory_ids))
        cur = conn.execute(f"DELETE FROM memories WHERE id IN ({placeholders})", memory_ids)
        return cur.rowcount


def clear_memories(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memory_log WHERE user_id = ?", (user_id,))


def delete_user_data(user_id: str) -> dict:
    """Cascade-delete all data for a user across all tables. Returns counts."""
    counts = {}
    with get_db() as conn:
        for table in ("memories", "conversations", "memory_log", "kg_entities", "kg_relations", "usage_stats"):
            cursor = conn.execute(f"DELETE FROM {table} WHERE user_id = ?", (user_id,))
            counts[table] = cursor.rowcount
        # Rebuild FTS index after bulk memory deletion
        try:
            conn.execute("DELETE FROM memories_fts")
            conn.execute(
                "INSERT INTO memories_fts(rowid, content, keywords) "
                "SELECT id, content, keywords FROM memories WHERE active = 1"
            )
        except sqlite3.OperationalError:
            pass
    return counts


def get_memory_stats(user_id):
    with get_db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE user_id = ? AND active = 1", (user_id,)
        ).fetchone()["c"]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) as c FROM memories WHERE user_id = ? AND active = 1 GROUP BY category",
            (user_id,),
        ).fetchall()
    return {"total": total, "by_category": {r["category"]: r["c"] for r in by_cat}}


def get_all_users():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT DISTINCT user_id FROM memories WHERE active = 1 ORDER BY user_id"
        ).fetchall()
        rows2 = conn.execute(
            "SELECT DISTINCT user_id FROM conversations ORDER BY user_id"
        ).fetchall()
    users = sorted(set(r["user_id"] for r in rows) | set(r["user_id"] for r in rows2))
    return users


def find_duplicate_memories(user_id, content, threshold=0.7):
    existing = get_memories(user_id, limit=200)
    content_words = set(content.lower().split())
    if not content_words:
        return []
    duplicates = []
    for mem in existing:
        mem_words = set(mem["content"].lower().split())
        if not mem_words:
            continue
        overlap = len(content_words & mem_words) / max(len(content_words | mem_words), 1)
        if overlap >= threshold:
            duplicates.append(mem)
    return duplicates


def log_memory_action(user_id, action, details=""):
    with get_db() as conn:
        conn.execute(
            "INSERT INTO memory_log (user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            (user_id, action, details, time.time()),
        )


# ── Conversation operations ──

# Session gap: if last message from user was > 30 min ago, start new session
_SESSION_GAP_SECONDS = 1800


def create_conversation_session() -> str:
    import uuid
    return uuid.uuid4().hex[:12]


def _get_or_create_session(conn, user_id: str) -> str:
    """Get current session ID or create a new one if gap elapsed."""
    row = conn.execute(
        "SELECT session_id, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if row and row["session_id"] and (time.time() - row["created_at"]) < _SESSION_GAP_SECONDS:
        return row["session_id"]
    return create_conversation_session()


def add_conversation_message(user_id, role, content, session_id=None, meta=None):
    meta_json = ""
    if meta:
        meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
        if len(meta_json) > 48_000:
            activity = list((meta.get("activity") or [])[:80])
            meta_json = json.dumps({"activity": activity}, ensure_ascii=False, separators=(",", ":"))
    with get_db() as conn:
        if session_id is None:
            session_id = _get_or_create_session(conn, user_id)
        conn.execute(
            "INSERT INTO conversations (user_id, role, content, created_at, session_id, meta) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, role, content, time.time(), session_id, meta_json),
        )


def get_conversation_history(user_id, limit=20, session_id: str | None = None):
    with get_db() as conn:
        if session_id:
            rows = conn.execute(
                """SELECT role, content, meta FROM conversations
                   WHERE user_id = ? AND session_id = ?
                   ORDER BY created_at DESC LIMIT ?""",
                (user_id, session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT role, content, meta FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
    out = []
    for r in reversed(rows):
        item = {"role": r["role"], "content": r["content"]}
        meta = _parse_message_meta(r["meta"])
        attachments = meta.get("attachments")
        if isinstance(attachments, list) and attachments:
            item["attachments"] = attachments
        tool_calls = meta.get("tool_calls")
        if isinstance(tool_calls, list) and tool_calls:
            item["tool_calls"] = tool_calls
        reasoning = meta.get("reasoning_content")
        if not reasoning:
            for ev in reversed(meta.get("activity") or []):
                if isinstance(ev, dict) and ev.get("name") == "think" and ev.get("detail"):
                    reasoning = ev.get("detail")
                    break
        if reasoning:
            item["reasoning_content"] = reasoning
        out.append(item)
    return out


def get_conversation_sessions(user_id, limit=20):
    """Get conversation sessions for a user with message counts."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT c.session_id as session_id,
                      MIN(c.created_at) as started_at,
                      MAX(c.created_at) as last_at,
                      COUNT(*) as message_count,
                      (SELECT content FROM conversations c2
                       WHERE c2.user_id = c.user_id
                         AND c2.session_id = c.session_id
                         AND c2.role = 'user'
                       ORDER BY c2.created_at ASC LIMIT 1) as title
               FROM conversations c
               WHERE c.user_id = ? AND c.session_id != ''
               GROUP BY c.session_id
               ORDER BY MAX(c.created_at) DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _parse_message_meta(raw) -> dict:
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def get_session_messages(user_id, session_id, limit=100):
    """Get all messages in a specific session."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at, meta
               FROM conversations
               WHERE user_id = ? AND session_id = ?
               ORDER BY created_at ASC
               LIMIT ?""",
            (user_id, session_id, limit),
        ).fetchall()
    out = []
    for r in rows:
        item = dict(r)
        meta = _parse_message_meta(item.pop("meta", ""))
        item["activity"] = meta.get("activity") if isinstance(meta.get("activity"), list) else []
        attachments = meta.get("attachments")
        if isinstance(attachments, list) and attachments:
            item["attachments"] = attachments
        model = str(meta.get("model") or "").strip()
        if model:
            item["model"] = model
        provider = str(meta.get("provider") or "").strip()
        if provider:
            item["provider"] = provider
        out.append(item)
    return out


def delete_conversation_session(user_id, session_id):
    """Delete a specific conversation session."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM conversations WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        )


def bulk_delete_conversation_sessions(user_id: str, session_ids: list[str]):
    """Delete multiple conversation sessions by session_id list."""
    if not session_ids:
        return 0
    with get_db() as conn:
        placeholders = ",".join("?" * len(session_ids))
        cur = conn.execute(
            f"DELETE FROM conversations WHERE user_id = ? AND session_id IN ({placeholders})",
            [user_id] + session_ids,
        )
        return cur.rowcount


def clear_conversation(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))


# ── Usage statistics operations ──

def add_usage_stat(user_id, provider_id, provider_name="", provider_type="",
                   model="", tokens_prompt=0, tokens_completion=0, tokens_total=0,
                   response_time_ms=0, stream=False, search_used=False,
                   eco_mode=False, secondary_used=False,
                   cache_hit_tokens=0, cache_miss_tokens=0,
                   cost_usd=0.0, route_reason=""):
    with get_db() as conn:
        conn.execute(
            """INSERT INTO usage_stats
               (user_id, provider_id, provider_name, provider_type, model,
                tokens_prompt, tokens_completion, tokens_total,
                response_time_ms, stream, search_used, eco_mode, secondary_used,
                cache_hit_tokens, cache_miss_tokens, cost_usd, route_reason, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, provider_id, provider_name, provider_type, model,
             tokens_prompt, tokens_completion, tokens_total,
             response_time_ms, 1 if stream else 0, 1 if search_used else 0,
             1 if eco_mode else 0, 1 if secondary_used else 0,
             cache_hit_tokens, cache_miss_tokens,
             float(cost_usd or 0.0), str(route_reason or ""),
             time.time()),
        )


def get_usage_stats(days=30):
    """Get comprehensive usage statistics."""
    cutoff = time.time() - (days * 86400)
    with get_db() as conn:
        # Total requests
        total = conn.execute(
            "SELECT COUNT(*) as c FROM usage_stats WHERE created_at >= ?", (cutoff,)
        ).fetchone()["c"]

        # Total tokens
        tokens = conn.execute(
            """SELECT COALESCE(SUM(tokens_prompt),0) as prompt,
                      COALESCE(SUM(tokens_completion),0) as completion,
                      COALESCE(SUM(tokens_total),0) as total
               FROM usage_stats WHERE created_at >= ?""", (cutoff,)
        ).fetchone()

        # Estimated spend — only as good as the price table behind it.
        cost_total = conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) as c FROM usage_stats WHERE created_at >= ?",
            (cutoff,)
        ).fetchone()["c"]

        # Per-provider stats
        by_provider = conn.execute(
            """SELECT provider_id, provider_name, provider_type,
                      COUNT(*) as requests,
                      COALESCE(SUM(tokens_total),0) as tokens,
                      COALESCE(SUM(cost_usd),0) as cost_usd,
                      CAST(AVG(response_time_ms) AS INTEGER) as avg_response_ms
               FROM usage_stats WHERE created_at >= ?
               GROUP BY provider_id
               ORDER BY requests DESC""", (cutoff,)
        ).fetchall()

        # Per-model stats
        by_model = conn.execute(
            """SELECT model, provider_name, provider_type,
                      COUNT(*) as requests,
                      COALESCE(SUM(tokens_total),0) as tokens,
                      CAST(AVG(response_time_ms) AS INTEGER) as avg_response_ms,
                      COALESCE(SUM(cache_hit_tokens),0) as cache_hit_tokens,
                      COALESCE(SUM(cache_miss_tokens),0) as cache_miss_tokens
               FROM usage_stats WHERE created_at >= ?
               GROUP BY model
               ORDER BY requests DESC""", (cutoff,)
        ).fetchall()

        # Per-user stats
        by_user = conn.execute(
            """SELECT user_id,
                      COUNT(*) as requests,
                      COALESCE(SUM(tokens_total),0) as tokens
               FROM usage_stats WHERE created_at >= ?
               GROUP BY user_id
               ORDER BY requests DESC""", (cutoff,)
        ).fetchall()

        # Daily activity (last N days)
        daily = conn.execute(
            """SELECT DATE(created_at, 'unixepoch') as day,
                      COUNT(*) as requests,
                      COALESCE(SUM(tokens_total),0) as tokens
               FROM usage_stats WHERE created_at >= ?
               GROUP BY day
               ORDER BY day ASC""", (cutoff,)
        ).fetchall()

        # Search usage
        search_count = conn.execute(
            "SELECT COUNT(*) as c FROM usage_stats WHERE created_at >= ? AND search_used = 1",
            (cutoff,)
        ).fetchone()["c"]

        # Stream vs non-stream
        stream_count = conn.execute(
            "SELECT COUNT(*) as c FROM usage_stats WHERE created_at >= ? AND stream = 1",
            (cutoff,)
        ).fetchone()["c"]

        # Eco mode usage
        eco_count = conn.execute(
            "SELECT COUNT(*) as c FROM usage_stats WHERE created_at >= ? AND eco_mode = 1",
            (cutoff,)
        ).fetchone()["c"]

        eco_tokens = conn.execute(
            """SELECT COALESCE(SUM(tokens_completion),0) as completion
               FROM usage_stats WHERE created_at >= ? AND eco_mode = 1""",
            (cutoff,)
        ).fetchone()["completion"]

        non_eco_avg = conn.execute(
            """SELECT CAST(AVG(tokens_completion) AS INTEGER) as avg_comp
               FROM usage_stats WHERE created_at >= ? AND eco_mode = 0 AND tokens_completion > 0""",
            (cutoff,)
        ).fetchone()["avg_comp"] or 0

        eco_avg = conn.execute(
            """SELECT CAST(AVG(tokens_completion) AS INTEGER) as avg_comp
               FROM usage_stats WHERE created_at >= ? AND eco_mode = 1 AND tokens_completion > 0""",
            (cutoff,)
        ).fetchone()["avg_comp"] or 0

        # Eco mode savings estimate: difference between average non-eco and eco completion tokens × eco requests
        eco_saved_tokens = max(0, (non_eco_avg - eco_avg) * eco_count) if eco_count and non_eco_avg else 0

        # Secondary provider usage
        secondary_count = conn.execute(
            "SELECT COUNT(*) as c FROM usage_stats WHERE created_at >= ? AND secondary_used = 1",
            (cutoff,)
        ).fetchone()["c"]

        secondary_tokens = conn.execute(
            """SELECT COALESCE(SUM(tokens_total),0) as total
               FROM usage_stats WHERE created_at >= ? AND secondary_used = 1""",
            (cutoff,)
        ).fetchone()["total"]

        cache_row = conn.execute(
            """SELECT COALESCE(SUM(cache_hit_tokens),0) as hit,
                      COALESCE(SUM(cache_miss_tokens),0) as miss
               FROM usage_stats WHERE created_at >= ?""",
            (cutoff,),
        ).fetchone()

    return {
        "period_days": days,
        "total_requests": total,
        "tokens": {
            "prompt": tokens["prompt"],
            "completion": tokens["completion"],
            "total": tokens["total"],
        },
        "cost_usd": round(float(cost_total or 0.0), 4),
        "by_provider": [dict(r) for r in by_provider],
        "by_model": [dict(r) for r in by_model],
        "by_user": [dict(r) for r in by_user],
        "daily": [dict(r) for r in daily],
        "search_requests": search_count,
        "stream_requests": stream_count,
        "non_stream_requests": total - stream_count,
        "eco_mode": {
            "requests": eco_count,
            "completion_tokens": eco_tokens,
            "saved_tokens": eco_saved_tokens,
            "avg_completion_eco": eco_avg,
            "avg_completion_normal": non_eco_avg,
        },
        "secondary": {
            "requests": secondary_count,
            "tokens": secondary_tokens,
        },
        "kv_cache": {
            "hit_tokens": cache_row["hit"],
            "miss_tokens": cache_row["miss"],
        },
    }


def cleanup_old_conversations(days: int = 90) -> int:
    """Delete conversation messages older than N days (#11). Returns count deleted."""
    cutoff = time.time() - (days * 86400)
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM conversations WHERE created_at < ?", (cutoff,)
        )
        deleted = cursor.rowcount
    return deleted


def rebuild_fts_index():
    """Rebuild FTS5 index from the memories table. Call after bulk operations."""
    with get_db() as conn:
        try:
            conn.execute("DELETE FROM memories_fts")
            conn.execute(
                "INSERT INTO memories_fts(rowid, content, keywords) "
                "SELECT id, content, keywords FROM memories WHERE active = 1"
            )
        except sqlite3.OperationalError:
            pass  # FTS not available