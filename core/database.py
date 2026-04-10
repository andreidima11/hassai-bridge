import sqlite3
import json
import time
from pathlib import Path
from contextlib import contextmanager

DB_PATH = Path(__file__).parent.parent / "data" / "hassai.db"

CATEGORIES = [
    "personal_info",
    "preferences",
    "home_setup",
    "facts",
    "instructions",
    "context",
]


def _get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def get_db():
    conn = _get_connection()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


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
                session_id TEXT NOT NULL DEFAULT ''
            )
        """)

        # Migrate: add session_id column if missing (for existing DBs)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(conversations)").fetchall()]
        if "session_id" not in cols:
            conn.execute("ALTER TABLE conversations ADD COLUMN session_id TEXT NOT NULL DEFAULT ''")

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


# ── Memory operations ──

def add_memory(user_id, content, category="facts", keywords="", importance=3, source="auto"):
    now = time.time()
    with get_db() as conn:
        cursor = conn.execute(
            """INSERT INTO memories
               (user_id, category, content, keywords, importance, created_at, last_accessed, access_count, source, active)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, 1)""",
            (user_id, category, content, keywords.lower(), min(max(importance, 1), 5), now, now, source),
        )
        return cursor.lastrowid


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
        keyword_clauses = " + ".join(
            ["(CASE WHEN keywords LIKE ? OR content LIKE ? THEN 1 ELSE 0 END)" for _ in query_keywords]
        )
        kw_params = []
        for kw in query_keywords:
            pattern = f"%{kw.lower()}%"
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

        ids = [r["id"] for r in rows if r["relevance"] > 0]
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


def deactivate_memory(memory_id):
    with get_db() as conn:
        conn.execute("UPDATE memories SET active = 0 WHERE id = ?", (memory_id,))


def delete_memory(memory_id):
    with get_db() as conn:
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))


def clear_memories(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))
        conn.execute("DELETE FROM memory_log WHERE user_id = ?", (user_id,))


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


def _get_or_create_session(conn, user_id: str) -> str:
    """Get current session ID or create a new one if gap elapsed."""
    row = conn.execute(
        "SELECT session_id, created_at FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
        (user_id,),
    ).fetchone()
    if row and row["session_id"] and (time.time() - row["created_at"]) < _SESSION_GAP_SECONDS:
        return row["session_id"]
    import uuid
    return uuid.uuid4().hex[:12]


def add_conversation_message(user_id, role, content, session_id=None):
    with get_db() as conn:
        if session_id is None:
            session_id = _get_or_create_session(conn, user_id)
        conn.execute(
            "INSERT INTO conversations (user_id, role, content, created_at, session_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, role, content, time.time(), session_id),
        )


def get_conversation_history(user_id, limit=20):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    return list(reversed([dict(r) for r in rows]))


def get_conversation_sessions(user_id, limit=20):
    """Get conversation sessions for a user with message counts."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT session_id,
                      MIN(created_at) as started_at,
                      MAX(created_at) as last_at,
                      COUNT(*) as message_count
               FROM conversations
               WHERE user_id = ? AND session_id != ''
               GROUP BY session_id
               ORDER BY MAX(created_at) DESC
               LIMIT ?""",
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_session_messages(user_id, session_id, limit=100):
    """Get all messages in a specific session."""
    with get_db() as conn:
        rows = conn.execute(
            """SELECT role, content, created_at
               FROM conversations
               WHERE user_id = ? AND session_id = ?
               ORDER BY created_at ASC
               LIMIT ?""",
            (user_id, session_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def delete_conversation_session(user_id, session_id):
    """Delete a specific conversation session."""
    with get_db() as conn:
        conn.execute(
            "DELETE FROM conversations WHERE user_id = ? AND session_id = ?",
            (user_id, session_id),
        )


def clear_conversation(user_id):
    with get_db() as conn:
        conn.execute("DELETE FROM conversations WHERE user_id = ?", (user_id,))