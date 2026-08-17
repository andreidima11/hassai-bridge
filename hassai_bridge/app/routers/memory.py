from fastapi import APIRouter, Request, Depends
from pydantic import BaseModel
from database import (
    get_memories, get_memories_by_category, add_memory, update_memory,
    delete_memory, bulk_delete_memories, deactivate_memory, clear_memories,
    get_all_users, get_memory_stats, CATEGORIES,
)
from services.memory_engine import consolidate_memories
from services.providers import get_active_provider, get_secondary_provider
from services.knowledge_graph import KnowledgeGraph


def _require_admin_key(request: Request):
    """Import-free admin auth — delegates to main._require_admin_key at runtime."""
    from main import _require_admin_key as _auth
    return _auth(request)


router = APIRouter(
    prefix="/api/memory",
    tags=["memory"],
    dependencies=[Depends(_require_admin_key)],
)


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


class BulkDeleteMemories(BaseModel):
    ids: list[int]


@router.post("/bulk-delete")
async def bulk_remove_memories(data: BulkDeleteMemories):
    deleted = bulk_delete_memories(data.ids)
    return {"status": "ok", "deleted": deleted}


@router.delete("/user/{user_id}")
async def clear_user_memories(user_id: str):
    clear_memories(user_id)
    return {"status": "ok"}


@router.post("/consolidate/{user_id}")
async def run_consolidation(user_id: str):
    active = get_active_provider()
    secondary = get_secondary_provider(active)
    await consolidate_memories(user_id, provider=secondary)
    return {"status": "ok", "message": "Consolidation complete"}


# ══════════════════════════════════════════════════
# Knowledge Graph endpoints
# ══════════════════════════════════════════════════

class EntityCreate(BaseModel):
    name: str
    entity_type: str = "unknown"
    properties: dict | None = None


class RelationCreate(BaseModel):
    subject: str
    predicate: str
    object: str
    valid_from: str | None = None
    valid_to: str | None = None


class RelationInvalidate(BaseModel):
    subject: str
    predicate: str
    object: str
    ended: str | None = None


@router.get("/graph/{user_id}/stats")
async def graph_stats(user_id: str):
    kg = KnowledgeGraph(user_id)
    return kg.stats()


@router.get("/graph/{user_id}/entities")
async def graph_entities(user_id: str, entity_type: str | None = None, limit: int = 100):
    kg = KnowledgeGraph(user_id)
    return {"entities": kg.list_entities(entity_type=entity_type, limit=limit)}


@router.get("/graph/{user_id}/entity/{name}")
async def graph_entity_detail(user_id: str, name: str):
    kg = KnowledgeGraph(user_id)
    entity = kg.get_entity(name)
    if not entity:
        return {"error": "Entity not found"}
    relations = kg.query(name)
    return {"entity": entity, "relations": relations}


@router.post("/graph/{user_id}/entity")
async def graph_add_entity(user_id: str, data: EntityCreate):
    kg = KnowledgeGraph(user_id)
    eid = kg.add_entity(data.name, data.entity_type, data.properties)
    return {"status": "ok", "id": eid}


@router.delete("/graph/{user_id}/entity/{name}")
async def graph_delete_entity(user_id: str, name: str):
    kg = KnowledgeGraph(user_id)
    kg.delete_entity(name)
    return {"status": "ok"}


@router.get("/graph/{user_id}/relations")
async def graph_query_entity(user_id: str, name: str, as_of: str | None = None):
    kg = KnowledgeGraph(user_id)
    return {"relations": kg.query(name, as_of=as_of)}


@router.post("/graph/{user_id}/relation")
async def graph_add_relation(user_id: str, data: RelationCreate):
    kg = KnowledgeGraph(user_id)
    rid = kg.add_relation(data.subject, data.predicate, data.object,
                          valid_from=data.valid_from, valid_to=data.valid_to)
    return {"status": "ok", "id": rid}


@router.post("/graph/{user_id}/invalidate")
async def graph_invalidate_relation(user_id: str, data: RelationInvalidate):
    kg = KnowledgeGraph(user_id)
    kg.invalidate(data.subject, data.predicate, data.object, ended=data.ended)
    return {"status": "ok"}


@router.get("/graph/{user_id}/timeline")
async def graph_timeline(user_id: str, entity: str | None = None, limit: int = 50):
    kg = KnowledgeGraph(user_id)
    return {"timeline": kg.timeline(entity, limit=limit)}


@router.get("/graph/{user_id}/context")
async def graph_context(user_id: str, entities: str | None = None, max_facts: int = 20):
    """Get the knowledge graph context string (same format injected into LLM)."""
    kg = KnowledgeGraph(user_id)
    entity_list = [e.strip() for e in entities.split(",")] if entities else None
    ctx = kg.build_context(entity_names=entity_list, max_facts=max_facts)
    return {"context": ctx}