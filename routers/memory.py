from fastapi import APIRouter
from pydantic import BaseModel
from database import (
    get_memories, get_memories_by_category, add_memory, update_memory,
    delete_memory, deactivate_memory, clear_memories, get_all_users,
    get_memory_stats, CATEGORIES,
)
from services.memory_engine import consolidate_memories

router = APIRouter(prefix="/api/memory", tags=["memory"])


class MemoryCreate(BaseModel):
    user_id: str
    content: str
    category: str = "facts"
    keywords: str = ""
    importance: int = 3


class MemoryUpdate(BaseModel):
    content: str | None = None
    category: str | None = None
    keywords: str | None = None
    importance: int | None = None


@router.get("/categories")
async def list_categories():
    return {"categories": CATEGORIES}


@router.get("/users")
async def list_users():
    return {"users": get_all_users()}


@router.get("/stats/{user_id}")
async def user_stats(user_id: str):
    return get_memory_stats(user_id)


@router.get("/{user_id}")
async def list_memories(user_id: str, limit: int = 100, category: str | None = None):
    if category:
        memories = get_memories_by_category(user_id, category, limit=limit)
    else:
        memories = get_memories(user_id, limit=limit)
    return {"user_id": user_id, "memories": memories}


@router.post("/")
async def create_memory(data: MemoryCreate):
    mid = add_memory(data.user_id, data.content, category=data.category,
                     keywords=data.keywords, importance=data.importance, source="manual")
    return {"status": "ok", "id": mid}


@router.put("/{memory_id}")
async def edit_memory(memory_id: int, data: MemoryUpdate):
    update_memory(memory_id, content=data.content, category=data.category,
                  keywords=data.keywords, importance=data.importance)
    return {"status": "ok"}


@router.delete("/{memory_id}")
async def remove_memory(memory_id: int):
    delete_memory(memory_id)
    return {"status": "ok"}


@router.delete("/user/{user_id}")
async def clear_user_memories(user_id: str):
    clear_memories(user_id)
    return {"status": "ok"}


@router.post("/consolidate/{user_id}")
async def run_consolidation(user_id: str):
    await consolidate_memories(user_id)
    return {"status": "ok", "message": "Consolidation complete"}