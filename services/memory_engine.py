"""
Smart Memory Engine — tiered retrieval, knowledge graph extraction,
signal detection, quality scoring, and single-pass LLM pipeline.

Architecture:
  Tier 0 (Identity): Core facts about the user — always injected (~100-150 tokens)
  Tier 1 (Relevant): Topic-matched memories for the current message
  Tier 2 (Graph):    Entity relationships from the knowledge graph

Extraction pipeline:
  1. Signal detection (zero-cost pre-filter)
  2. Single LLM call → memory ADD/UPDATE/DELETE + entity/relation extraction
  3. Background execution (non-blocking)
"""

import hashlib
import json
import logging
import re
import time
import asyncio
from typing import Optional

from config import load_config
from database import (
    add_memory, search_memories, get_memories, find_duplicate_memories,
    log_memory_action, get_memory_stats, deactivate_memory, update_memory,
    delete_memory, CATEGORIES,
)
from services.knowledge_graph import KnowledgeGraph

log = logging.getLogger("hassai.memory")


# ── Memory retrieval cache (TTL 60s) ──

_MEMORY_CACHE: dict = {}
_MEMORY_CACHE_TTL = 60.0
_MEMORY_CACHE_MAX = 200


def _memory_cache_key(user_id: str, query: str) -> str:
    q = (query or "")[:300].strip()
    h = hashlib.sha256(q.encode("utf-8")).hexdigest()[:16]
    return f"{user_id}:{h}"


def _memory_cache_get(key: str) -> Optional[list[dict]]:
    if key not in _MEMORY_CACHE:
        return None
    val, expiry = _MEMORY_CACHE[key]
    if time.time() > expiry:
        del _MEMORY_CACHE[key]
        return None
    return val


def _memory_cache_set(key: str, value: list[dict]) -> None:
    while len(_MEMORY_CACHE) >= _MEMORY_CACHE_MAX:
        oldest = min(_MEMORY_CACHE, key=lambda k: _MEMORY_CACHE[k][1])
        del _MEMORY_CACHE[oldest]
    _MEMORY_CACHE[key] = (value, time.time() + _MEMORY_CACHE_TTL)


# ── Prompts ──

EXTRACT_PIPELINE_PROMPT = """You are a memory management system. Analyze the conversation and decide what to remember.

You have access to EXISTING memories (numbered 0, 1, 2...). For each piece of information worth remembering, output ONE action per line:

MEMORY ACTIONS:
- ADD <category> <importance> <text> — save a NEW fact (not already in existing memories)
- UPDATE <id> <text> — update an existing memory with new info (use the numbered id)
- DELETE <id> — remove an outdated/wrong memory (use the numbered id)

ENTITY/RELATION ACTIONS (extract people, places, devices, and their relationships):
- ENTITY <type> <name> — register an entity (types: person, device, location, pet, concept)
- RELATION <subject> | <predicate> | <object> — register a relationship between entities

Rules:
- Extract ONLY concrete, useful facts about the user (not conversation meta like "user asked about X")
- Categories: personal_info, preferences, home_setup, facts, instructions, context
- Importance: 1-5 (5=critical personal info, 1=minor detail)
- Prefer UPDATE over ADD when info updates an existing fact
- Use DELETE for facts that are now contradicted
- Extract entities mentioned (family members, pets, devices, rooms, locations)
- Extract relationships (e.g., "Ana is wife" → RELATION Ana | is_wife_of | User)
- Max 5 memory actions + 5 entity actions + 5 relation actions per conversation
- If nothing worth remembering, output only: NONE

Existing memories:
{existing_memories}

Conversation:
{conversation}

Actions:"""


RETRIEVAL_PROMPT = """Given the user's message below, generate 5-10 search keywords that would help find relevant memories about this user. Think about what existing knowledge would be useful to answer this message.

User message: {message}

Respond with ONLY a JSON array of lowercase keywords (no markdown, no explanation):
["keyword1", "keyword2", "keyword3"]"""


CONSOLIDATE_PROMPT = """You are a memory consolidation system. Review these memories for the same user and:
1. Identify memories that should be merged (same topic, updated info)
2. Identify outdated memories that should be deactivated
3. Suggest consolidated versions

Memories:
{memories}

Respond with ONLY a JSON object (no markdown):
{{
  "keep": [list of memory IDs to keep as-is],
  "deactivate": [list of memory IDs to deactivate],
  "merge": [
    {{
      "source_ids": [ids being merged],
      "content": "merged content",
      "category": "category",
      "importance": 3,
      "keywords": "kw1,kw2"
    }}
  ]
}}"""


async def _llm_call(messages: list[dict], max_tokens: int = 1000) -> str:
    """Make a lightweight LLM call for memory operations."""
    from services.lmstudio import chat_completion
    try:
        result = await chat_completion(messages, stream=False)
        return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        log.error(f"LLM call failed: {e}")
        return ""


def _parse_json(text: str, fallback=None):
    """Parse JSON from LLM response, handling markdown code blocks."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        if fallback is not None:
            return fallback
        return []


# ── Signal detection (zero-cost pre-filters) ──

_TRIVIAL_PATTERNS = re.compile(
    r"^(ok|da|nu|yes|no|aha|mhm|salut|buna|hello|hi|hey|mulțumesc|mersi|thanks|"
    r"bine|ok|good|bye|pa|noapte buna|la revedere|ciao)$",
    re.IGNORECASE,
)


def _is_trivial_message(text: str) -> bool:
    """Check if message is too trivial to contain memorizable information."""
    clean = (text or "").strip()
    if len(clean) < 3:
        return True
    if _TRIVIAL_PATTERNS.match(clean):
        return True
    if len(clean.split()) <= 2:
        return True
    return False


def _has_memory_signal(user_text: str, assistant_text: str = "") -> bool:
    """Check if the conversation likely contains information worth extracting."""
    combined = f"{user_text} {assistant_text}".lower()

    # Personal info keywords
    personal_signals = [
        "name", "numele", "mă cheamă", "ma cheama", "am ", "sunt ", "lucrez",
        "prefer", "îmi place", "imi place", "nu-mi place", "nu imi place",
        "locuiesc", "live", "born", "născut", "nascut", "birthday", "ziua mea",
        "wife", "soția", "sotia", "husband", "soțul", "sotul", "child", "copil",
        "dog", "cat", "câine", "caine", "pisică", "pisica", "pet",
        "hobby", "like", "love", "hate", "urăsc", "urasc", "favorite",
        "job", "work", "muncesc", "slujba", "profesie",
        "home", "acasă", "acasa", "room", "camera", "device", "dispozitiv",
        "remember", "reține", "retine", "notează", "noteaza", "memorează", "memoreaza",
    ]
    if any(signal in combined for signal in personal_signals):
        return True

    # If assistant mentions remembering
    assistant_lower = (assistant_text or "").lower()
    memory_keywords = ["note", "remember", "memory", "retin", "notat", "memor"]
    if any(kw in assistant_lower for kw in memory_keywords):
        return True

    # If message is long enough, let the LLM decide
    if len(user_text.split()) > 6:
        return True

    return False


# ── Fact quality scoring ──

def _score_fact_quality(text: str) -> float:
    """Score a fact's quality (0.0 - 1.0). Reject if < 0.2."""
    if not text or len(text.strip()) < 5:
        return 0.0

    score = 0.5  # base score
    text_lower = text.lower().strip()

    # Too short
    if len(text_lower) < 10:
        score -= 0.3

    # Too vague
    vague_patterns = ["something", "ceva", "maybe", "poate", "nu știu", "nu stiu", "i think", "cred că"]
    if any(p in text_lower for p in vague_patterns):
        score -= 0.2

    # Contains concrete info (names, numbers, specifics)
    if re.search(r"\b[A-Z][a-z]+\b", text):  # proper nouns
        score += 0.2
    if re.search(r"\d+", text):  # numbers
        score += 0.1
    if len(text.split()) >= 4:  # reasonable length
        score += 0.1

    # Meta-comments about the conversation itself (strong penalty)
    meta_patterns = ["user asked", "user wanted", "conversation about", "we discussed",
                     "user said", "user mentioned", "the user"]
    if any(p in text_lower for p in meta_patterns):
        score -= 0.5

    return max(0.0, min(1.0, score))


# ── Stopwords for local keyword extraction ──

_STOPWORDS = frozenset({
    "a", "ai", "al", "ale", "am", "an", "and", "any", "are", "as", "at",
    "au", "be", "been", "but", "by", "ca", "can", "care", "ce", "ci",
    "could", "cu", "cum", "că", "da", "dar", "de", "did", "din", "do",
    "does", "dont", "down", "du", "dupa", "după", "e", "ea", "ei", "el",
    "ele", "en", "era", "este", "eu", "fi", "fie", "for", "from", "get",
    "got", "had", "has", "have", "he", "her", "here", "him", "his", "how",
    "i", "if", "ii", "il", "im", "in", "into", "is", "it", "its", "just",
    "la", "le", "li", "lor", "lui", "ma", "mai", "me", "meu", "mi",
    "mine", "mă", "my", "ne", "ni", "no", "nor", "not", "nu", "o",
    "of", "on", "one", "only", "or", "ori", "our", "out", "pe", "prin",
    "pt", "prea", "sa", "sau", "se", "she", "si", "so", "some", "sunt",
    "să", "ta", "te", "than", "that", "the", "their", "them", "then",
    "there", "these", "they", "this", "to", "too", "tu", "un", "una",
    "unde", "up", "upon", "us", "va", "very", "vom", "vor", "vă",
    "was", "we", "were", "what", "when", "where", "which", "who",
    "will", "with", "would", "you", "your", "și", "în", "îi", "îl",
})


def _extract_keywords_local(text: str) -> list[str]:
    """Fast local keyword extraction — no LLM call needed."""
    import re as _re
    words = _re.findall(r"[a-zA-ZăîâșțĂÎÂȘȚ]{3,}", text.lower())
    keywords = [w for w in words if w not in _STOPWORDS]
    # Deduplicate preserving order
    seen = set()
    result = []
    for w in keywords:
        if w not in seen:
            seen.add(w)
            result.append(w)
    return result[:15]


# ══════════════════════════════════════════════════
# TIERED RETRIEVAL — layered memory context for the LLM
# ══════════════════════════════════════════════════

async def retrieve_relevant_memories(user_id: str, message: str) -> list[dict]:
    """Tier 1: Find topic-relevant memories using local keyword extraction."""
    cfg = load_config()
    if not cfg["memory"].get("enabled"):
        return []

    # Check cache
    cache_key = _memory_cache_key(user_id, message)
    cached = _memory_cache_get(cache_key)
    if cached is not None:
        log.debug(f"Memory cache hit for user {user_id}")
        return cached

    # Fast local keyword extraction (no LLM call)
    all_keywords = _extract_keywords_local(message)

    # Search memories with these keywords
    memories = search_memories(user_id, all_keywords, limit=15)

    # Cache result
    _memory_cache_set(cache_key, memories)
    return memories


def _get_identity_memories(user_id: str) -> list[dict]:
    """Tier 0: Get core identity facts — highest importance memories that define the user."""
    memories = get_memories(user_id, limit=200)
    # Filter to importance >= 4 (critical personal info)
    identity = [m for m in memories if m.get("importance", 3) >= 4]
    # Also include all personal_info and instructions regardless of importance
    for m in memories:
        if m.get("category") in ("personal_info", "instructions") and m not in identity:
            identity.append(m)
    # Cap at 10 entries to keep T0 compact
    return identity[:10]


def _detect_entities_in_message(message: str) -> list[str]:
    """Detect potential entity names mentioned in a message for graph lookup."""
    # Look for capitalized words (names), quoted strings
    entities = []
    # Proper nouns (capitalized words not at sentence start)
    words = message.split()
    for i, word in enumerate(words):
        clean = re.sub(r"[^\w]", "", word)
        if (clean and clean[0].isupper() and len(clean) > 1
                and i > 0 and not words[i - 1].endswith((".", "!", "?"))):
            entities.append(clean)
    # Also check for common HA entity patterns (device names)
    for match in re.finditer(r"(?:becul|lampa|senzorul|camera|usa)\s+(\w+)", message, re.IGNORECASE):
        entities.append(match.group(1))
    return list(set(entities))


def build_memory_context(memories: list[dict], user_id: str = "",
                          message: str = "") -> str:
    """Build tiered memory context for LLM injection.

    Tier 0: Identity (core user facts, always present)
    Tier 1: Relevant memories (topic-matched from search)
    Tier 2: Knowledge graph (entity relationships)
    """
    if not memories and not user_id:
        return ""

    sections = []

    # ── Tier 0: Identity core ──
    if user_id:
        identity = _get_identity_memories(user_id)
        if identity:
            t0_lines = ["[T0 — User Identity]:"]
            seen_content = set()
            for m in identity:
                if m["content"] not in seen_content:
                    seen_content.add(m["content"])
                    t0_lines.append(f"  • {m['content']}")
            sections.append("\n".join(t0_lines))

    # ── Tier 1: Topic-relevant memories ──
    if memories:
        # Remove duplicates with T0
        t0_ids = {m["id"] for m in (_get_identity_memories(user_id) if user_id else [])}
        filtered = [m for m in memories if m.get("id") not in t0_ids]

        if filtered:
            by_category = {}
            for m in filtered:
                cat = m.get("category", "facts")
                by_category.setdefault(cat, []).append(m)

            category_labels = {
                "personal_info": "👤 Personal",
                "preferences": "🎨 Preferences",
                "home_setup": "🏠 Home & Devices",
                "facts": "📌 Facts",
                "instructions": "📋 Instructions",
                "context": "🔄 Context",
            }

            t1_lines = ["[T1 — Relevant Memories]:"]
            for cat in CATEGORIES:
                if cat in by_category:
                    t1_lines.append(f"\n{category_labels.get(cat, cat)}:")
                    for m in by_category[cat]:
                        imp = "⭐" * min(m.get("importance", 3), 5)
                        t1_lines.append(f"  [{imp}] {m['content']}")
            sections.append("\n".join(t1_lines))

    # ── Tier 2: Knowledge Graph context ──
    if user_id and message:
        try:
            kg = KnowledgeGraph(user_id)
            # Find entities mentioned in the message
            entity_names = _detect_entities_in_message(message)
            if entity_names:
                graph_ctx = kg.build_context(entity_names)
            else:
                # Fallback: get overall graph context (compact)
                graph_ctx = kg.build_context(max_facts=10)

            if graph_ctx:
                sections.append(f"[T2 — Knowledge Graph]:\n{graph_ctx}")
        except Exception as e:
            log.debug(f"Knowledge graph context failed: {e}")

    return "\n\n".join(sections) if sections else ""


# ══════════════════════════════════════════════════
# SINGLE-PASS MEMORY PIPELINE — extract + resolve in one LLM call
# ══════════════════════════════════════════════════

def _build_extraction_input(user_text: str, assistant_reply: str = "",
                             recent_messages: list[dict] = None) -> str:
    """Build the input text for the memory extraction prompt."""
    lines = []
    if recent_messages:
        for msg in recent_messages[-6:]:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ("user", "assistant") and content:
                lines.append(f"{role.upper()}: {content}")
    else:
        if user_text:
            lines.append(f"USER: {user_text}")
        if assistant_reply:
            lines.append(f"ASSISTANT: {assistant_reply}")
    return "\n".join(lines)


def _parse_pipeline_response(raw: str) -> list[dict]:
    """Parse the single-pass pipeline response into actions (memories + entities + relations)."""
    actions = []
    raw = raw.strip()
    if not raw or raw.upper() == "NONE":
        return []

    for line in raw.strip().split("\n"):
        line = line.strip()
        if not line or line.upper() == "NONE":
            continue

        if line.startswith("ADD "):
            # ADD <category> <importance> <text>
            parts = line[4:].split(None, 2)
            if len(parts) >= 3:
                category = parts[0] if parts[0] in CATEGORIES else "facts"
                try:
                    importance = int(parts[1])
                except (ValueError, IndexError):
                    importance = 3
                text = parts[2].strip()
                if text:
                    actions.append({"action": "ADD", "category": category,
                                   "importance": importance, "text": text})
        elif line.startswith("UPDATE "):
            # UPDATE <id> <text>
            parts = line[7:].split(None, 1)
            if len(parts) >= 2:
                try:
                    mem_id = int(parts[0])
                except ValueError:
                    continue
                text = parts[1].strip()
                if text:
                    actions.append({"action": "UPDATE", "id": mem_id, "text": text})
        elif line.startswith("DELETE "):
            # DELETE <id>
            parts = line[7:].strip()
            try:
                mem_id = int(parts)
                actions.append({"action": "DELETE", "id": mem_id})
            except ValueError:
                continue
        elif line.startswith("ENTITY "):
            # ENTITY <type> <name>
            parts = line[7:].split(None, 1)
            if len(parts) >= 2:
                entity_type = parts[0].strip().lower()
                name = parts[1].strip()
                if name:
                    actions.append({"action": "ENTITY", "entity_type": entity_type, "name": name})
        elif line.startswith("RELATION "):
            # RELATION subject | predicate | object
            parts = line[9:].split("|")
            if len(parts) >= 3:
                subject = parts[0].strip()
                predicate = parts[1].strip()
                obj = parts[2].strip()
                if subject and predicate and obj:
                    actions.append({"action": "RELATION", "subject": subject,
                                   "predicate": predicate, "object": obj})

    return actions[:15]  # max 15 total actions


async def extract_memories_from_conversation(user_id: str, messages: list[dict]):
    """Single-pass memory pipeline: signal detect → retrieve existing → LLM extract+resolve → execute."""
    cfg = load_config()
    if not cfg["memory"].get("enabled") or not cfg["memory"].get("auto_extract"):
        return

    # Get last user message
    user_text = ""
    assistant_text = ""
    for msg in reversed(messages):
        if msg.get("role") == "user" and not user_text:
            user_text = msg.get("content", "")
        elif msg.get("role") == "assistant" and not assistant_text:
            assistant_text = msg.get("content", "")
        if user_text and assistant_text:
            break

    # Pre-filter: skip trivial messages (zero cost)
    if _is_trivial_message(user_text):
        return

    # Signal detection: skip if no personal-info signals (zero cost)
    if not _has_memory_signal(user_text, assistant_text):
        return

    # Build conversation input
    input_text = _build_extraction_input(user_text, assistant_text, messages)
    if not input_text.strip():
        return

    try:
        # Retrieve existing memories relevant to this message
        existing = search_memories(user_id, 
            [w.lower() for w in user_text.split() if len(w) > 3][:10],
            limit=20)

        # Map existing IDs to sequential integers (prevent hallucination)
        id_mapping = {}
        mapped_existing = []
        for idx, mem in enumerate(existing):
            id_mapping[idx] = mem["id"]
            mapped_existing.append(f"  [{idx}] ({mem.get('category', 'facts')}) {mem['content']}")

        existing_str = "\n".join(mapped_existing) if mapped_existing else "(none)"

        # Single LLM call: extract + resolve
        response = await _llm_call([
            {"role": "system", "content": "You extract and manage user memories. Output ONLY action lines, nothing else."},
            {"role": "user", "content": EXTRACT_PIPELINE_PROMPT.format(
                existing_memories=existing_str,
                conversation=input_text[:1500],
            )},
        ], max_tokens=500)

        actions = _parse_pipeline_response(response)
        if not actions:
            return

        # Execute actions
        added = 0
        updated = 0
        deleted = 0
        entities_added = 0
        relations_added = 0

        kg = KnowledgeGraph(user_id)

        for action in actions:
            event = action["action"]
            text = action.get("text", "").strip()

            if event == "ADD" and text:
                # Quality check
                quality = _score_fact_quality(text)
                if quality < 0.2:
                    log.debug(f"Rejected low-quality fact (q={quality:.2f}): {text[:60]}")
                    continue

                # Check for duplicates
                dupes = find_duplicate_memories(user_id, text, threshold=0.6)
                if dupes:
                    # Update existing if new is more important
                    importance = action.get("importance", 3)
                    if dupes[0].get("importance", 3) < importance:
                        update_memory(dupes[0]["id"], content=text, importance=importance)
                        log_memory_action(user_id, "updated", f"Dedup-update: {text[:80]}")
                        updated += 1
                    continue

                # Check max memories limit
                stats = get_memory_stats(user_id)
                max_mem = cfg["memory"].get("max_memories_per_user", 500)
                if stats["total"] >= max_mem:
                    log.warning(f"Memory limit reached for {user_id}")
                    break

                category = action.get("category", "facts")
                importance = action.get("importance", 3)
                # Auto-generate keywords from text
                keywords = ",".join(w.lower() for w in text.split() if len(w) > 3)[:200]
                add_memory(user_id, text, category=category, keywords=keywords,
                          importance=importance, source="auto")
                log_memory_action(user_id, "extracted", text[:100])
                added += 1

            elif event == "UPDATE" and text:
                mem_idx = action.get("id")
                if mem_idx is not None and mem_idx in id_mapping:
                    real_id = id_mapping[mem_idx]
                    update_memory(real_id, content=text)
                    log_memory_action(user_id, "updated", f"ID={real_id}: {text[:80]}")
                    updated += 1

            elif event == "DELETE":
                mem_idx = action.get("id")
                if mem_idx is not None and mem_idx in id_mapping:
                    real_id = id_mapping[mem_idx]
                    deactivate_memory(real_id)
                    log_memory_action(user_id, "deleted", f"ID={real_id}")
                    deleted += 1

            elif event == "ENTITY":
                name = action.get("name", "").strip()
                entity_type = action.get("entity_type", "unknown")
                if name:
                    try:
                        kg.add_entity(name, entity_type)
                        entities_added += 1
                    except Exception as e:
                        log.debug(f"Entity add failed: {e}")

            elif event == "RELATION":
                subject = action.get("subject", "").strip()
                predicate = action.get("predicate", "").strip()
                obj = action.get("object", "").strip()
                if subject and predicate and obj:
                    try:
                        kg.add_relation(subject, predicate, obj, source="auto")
                        relations_added += 1
                    except Exception as e:
                        log.debug(f"Relation add failed: {e}")

        if added or updated or deleted or entities_added or relations_added:
            log.info(
                f"Memory pipeline for {user_id}: "
                f"+{added} ~{updated} -{deleted} mem, "
                f"+{entities_added} ent, +{relations_added} rel"
            )

    except Exception as e:
        log.error(f"Memory pipeline failed for {user_id}: {e}")


# ══════════════════════════════════════════════════
# CONSOLIDATION — merge and clean up memories
# ══════════════════════════════════════════════════

async def consolidate_memories(user_id: str):
    """Periodically consolidate memories: merge duplicates, remove outdated."""
    memories = get_memories(user_id, limit=100)
    if len(memories) < 10:
        return  # Not enough to consolidate

    mem_text = "\n".join(
        f"[ID={m['id']}] [{m['category']}] (importance={m['importance']}) {m['content']}"
        for m in memories
    )

    try:
        response = await _llm_call([
            {"role": "system", "content": "You consolidate memories. Respond with ONLY valid JSON."},
            {"role": "user", "content": CONSOLIDATE_PROMPT.format(memories=mem_text)},
        ], max_tokens=2000)

        plan = _parse_json(response, fallback={})
        if not isinstance(plan, dict):
            return

        # Deactivate memories
        for mid in plan.get("deactivate", []):
            if isinstance(mid, int):
                deactivate_memory(mid)
                log_memory_action(user_id, "consolidated_deactivate", f"ID={mid}")

        # Merge memories
        for merge in plan.get("merge", []):
            content = merge.get("content", "").strip()
            if not content:
                continue
            for sid in merge.get("source_ids", []):
                if isinstance(sid, int):
                    deactivate_memory(sid)
            add_memory(
                user_id, content,
                category=merge.get("category", "facts"),
                keywords=merge.get("keywords", ""),
                importance=merge.get("importance", 3),
                source="consolidated",
            )
            log_memory_action(user_id, "consolidated_merge", content[:100])

        log.info(f"Consolidation complete for {user_id}")

    except Exception as e:
        log.error(f"Memory consolidation failed for {user_id}: {e}")