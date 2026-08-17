# Re-export from core.database for backward compatibility
from core.database import *  # noqa: F401,F403
from core.database import (
    init_db, get_db, add_memory, get_memories, get_memories_by_category,
    search_memories, update_memory, deactivate_memory, delete_memory,
    bulk_delete_memories, clear_memories, delete_user_data, get_memory_stats,
    get_all_users, find_duplicate_memories, log_memory_action,
    add_conversation_message, get_conversation_history,
    get_conversation_sessions, get_session_messages,
    delete_conversation_session, bulk_delete_conversation_sessions,
    clear_conversation, CATEGORIES, DB_PATH,
    add_usage_stat, get_usage_stats, create_conversation_session,
)
