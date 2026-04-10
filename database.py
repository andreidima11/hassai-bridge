# Re-export from core.database for backward compatibility
from core.database import *  # noqa: F401,F403
from core.database import (
    init_db, get_db, add_memory, get_memories, get_memories_by_category,
    search_memories, update_memory, deactivate_memory, delete_memory,
    clear_memories, get_memory_stats, get_all_users, find_duplicate_memories,
    log_memory_action, add_conversation_message, get_conversation_history,
    clear_conversation, CATEGORIES, DB_PATH,
)
