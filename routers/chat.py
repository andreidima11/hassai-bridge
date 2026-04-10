"""
OpenAI-compatible /v1/chat/completions endpoint.
Home Assistant sends requests here. We:
1. Retrieve relevant memories for the user
2. Forward augmented request to LMStudio
3. If LLM requests web search (<<SEARCH: query>>), search and re-prompt
4. Extract new memories from the conversation (background, non-blocking)
"""

import json
import asyncio
import logging
import re
from datetime import date
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config import load_config
from database import (
    add_conversation_message,
    get_conversation_history,
)
from services import lmstudio
from services.memory_engine import (
    retrieve_relevant_memories,
    build_memory_context,
    extract_memories_from_conversation,
)
from services.web_scraper import search_and_fetch

log = logging.getLogger("hassai.chat")
router = APIRouter()

# ══════════════════════════════════════════════════
# AI-driven search: the LLM decides when to search
# ══════════════════════════════════════════════════

_SEARCH_MARKER = re.compile(r"<<SEARCH:\s*(.+?)>>")


def _build_search_instruction(cfg: dict) -> str:
    """Build a system instruction telling the LLM about search capability."""
    cutoff = cfg.get("knowledge_cutoff", "2024-01")
    today = date.today().strftime("%Y-%m-%d")

    return (
        f"Today's date: {today}. "
        f"Your training data has a knowledge cutoff of {cutoff}. "
        "You have access to a live web search engine. "
        "If you believe the user's question requires information that may have "
        "changed after your cutoff, or if you are unsure about current facts "
        "(e.g., current leaders, live scores, today's weather, recent events, "
        "prices, new releases), respond with ONLY the marker <<SEARCH: your search query>> "
        "and nothing else. The system will fetch results and ask you again. "
        "If you can answer confidently from your training data, answer normally — "
        "do NOT use the search marker."
    )


_API_KEY_PATTERN = re.compile(r"^hab_[a-f0-9]{32,64}$")


def _validate_api_key(request: Request):
    """Validate API key from Bearer token or X-Assist-Key header."""
    cfg = load_config()
    expected_key = cfg.get("api_key", "")
    if not expected_key:
        return  # No key configured — allow all

    # Collect all valid keys: system key + per-user keys
    valid_keys = {expected_key}
    user_api_keys = cfg.get("users", {}).get("api_keys", {})
    valid_keys.update(user_api_keys.keys())

    # Try Bearer token first (what HA Ollama sends)
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token in valid_keys:
            return

    # Try X-Assist-Key header
    assist_key = request.headers.get("x-assist-key", "").strip()
    if assist_key and assist_key in valid_keys:
        return

    raise HTTPException(status_code=401, detail="Invalid API key")


def _extract_user_id(request: Request, body: dict) -> str:
    """Identify the HA user from the request.

    Priority:
    1. API key → username mapping (config users.api_keys)
    2. HA headers (X-HA-User-Id, X-HA-Username, etc.)
    3. body fields (user, user_id, username)
    4. Fallback to config users.default_user
    """
    cfg = load_config()
    users_cfg = cfg.get("users", {})
    api_key_map = users_cfg.get("api_keys", {})
    default_user = users_cfg.get("default_user", "").strip()

    # 1) Check if the API key maps to a specific user
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token in api_key_map:
            return api_key_map[token]

    assist_key = request.headers.get("x-assist-key", "").strip()
    if assist_key and assist_key in api_key_map:
        return api_key_map[assist_key]

    # 2) HA headers
    for header in ("X-HA-Username", "X-HA-User-Name", "X-HA-User-Id", "X-HA-User"):
        val = request.headers.get(header, "").strip()
        if val:
            return val

    # 3) Body fields
    for field in ("username", "user_name", "user_id", "user"):
        val = str(body.get(field, "") or "").strip()
        if val:
            return val

    # 4) Fallback to configured default user
    if default_user:
        return default_user

    return "default"


@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model")
    stream = body.get("stream", False)
    user_id = _extract_user_id(request, body)
    cfg = load_config()
    search_enabled = cfg["searxng"].get("enabled", False)

    # ── Build augmented message list ──
    augmented: list[dict] = []

    # 1) System prompt
    system_prompt = cfg.get("system_prompt", "")
    if system_prompt:
        augmented.append({"role": "system", "content": system_prompt})

    # 2) Search capability instruction (if SearXNG is enabled)
    if search_enabled:
        augmented.append({"role": "system", "content": _build_search_instruction(cfg)})

    # 3) Memory + history retrieval (parallel)
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    history_limit = cfg.get("performance", {}).get("history_limit", 10)
    memories, history = await asyncio.gather(
        retrieve_relevant_memories(user_id, last_user_msg),
        asyncio.to_thread(get_conversation_history, user_id, history_limit),
    )

    mem_ctx = build_memory_context(memories)
    if mem_ctx:
        augmented.append({"role": "system", "content": mem_ctx})

    # 4) Conversation history
    if history:
        augmented.extend(history)

    # 5) Current messages
    augmented.extend(messages)

    # ── Save user messages to history ──
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content and role in ("user", "assistant"):
            add_conversation_message(user_id, role, content)

    # ── First LLM call ──
    # For non-streaming: check if LLM requests search, then re-prompt with results
    if not stream:
        result = await lmstudio.chat_completion(augmented, model=model)
        try:
            assistant_content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            assistant_content = ""

        # Check if AI requested search
        if search_enabled and assistant_content:
            match = _SEARCH_MARKER.search(assistant_content)
            if match:
                query = match.group(1).strip()[:200]
                log.info(f"AI requested search: {query}")
                try:
                    search_ctx = await search_and_fetch(query)
                except Exception as e:
                    log.error(f"Search failed: {e}")
                    search_ctx = ""

                if search_ctx:
                    # Re-prompt with search results (second call)
                    augmented.append({
                        "role": "system",
                        "content": (
                            "[Web search results — use this to answer accurately. "
                            "Cite sources with [N]. Summarize clearly, do not paste raw text. "
                            "Do NOT use the <<SEARCH>> marker again.]:\n"
                            f"{search_ctx}"
                        ),
                    })
                    result = await lmstudio.chat_completion(augmented, model=model)
                    try:
                        assistant_content = result["choices"][0]["message"]["content"]
                    except (KeyError, IndexError):
                        pass

        # Save & extract memories
        if assistant_content:
            add_conversation_message(user_id, "assistant", assistant_content)
            all_msgs = messages + [{"role": "assistant", "content": assistant_content}]
            asyncio.create_task(_safe_extract(user_id, all_msgs))

        return JSONResponse(content=result)

    # ── Streaming path ──
    # Optimized: buffer only initial tokens to check for search marker,
    # then flush buffer and stream remaining tokens directly
    gen = lmstudio.chat_completion_stream(augmented, model=model)

    _SEARCH_BUFFER_CHARS = 120  # search markers appear in the first ~100 chars

    async def stream_wrapper():
        full_response = ""
        buffered_chunks = []
        buffer_text = ""
        search_checked = False

        async for chunk in gen:
            if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                try:
                    data = json.loads(chunk[6:])
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    token = delta.get("content", "")
                except (json.JSONDecodeError, IndexError, KeyError):
                    token = ""

                if not search_checked and search_enabled:
                    # Buffer phase: accumulate tokens to check for search marker
                    buffered_chunks.append(chunk)
                    buffer_text += token

                    if len(buffer_text) >= _SEARCH_BUFFER_CHARS or _SEARCH_MARKER.search(buffer_text):
                        search_checked = True
                        match = _SEARCH_MARKER.search(buffer_text)
                        if match:
                            # Search marker found — do search and re-stream
                            query = match.group(1).strip()[:200]
                            log.info(f"AI requested search (stream): {query}")
                            search_ctx = ""
                            try:
                                # Drain remaining tokens (LLM may still be generating)
                                async for _ in gen:
                                    pass
                                search_ctx = await search_and_fetch(query)
                            except Exception as e:
                                log.error(f"Search failed: {e}")

                            if search_ctx:
                                augmented.append({
                                    "role": "system",
                                    "content": (
                                        "[Web search results — use this to answer accurately. "
                                        "Cite sources with [N]. Summarize clearly, do not paste raw text. "
                                        "Do NOT use the <<SEARCH>> marker again.]:\n"
                                        f"{search_ctx}"
                                    ),
                                })
                            else:
                                augmented.append({
                                    "role": "system",
                                    "content": "Search is temporarily unavailable. Answer from your training data. Do NOT use <<SEARCH>> marker.",
                                })

                            # Re-stream with search results
                            gen2 = lmstudio.chat_completion_stream(augmented, model=model)
                            async for chunk2 in gen2:
                                yield chunk2
                                if chunk2.startswith("data: ") and chunk2.strip() != "data: [DONE]":
                                    try:
                                        d2 = json.loads(chunk2[6:])
                                        t2 = d2.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                        full_response += t2
                                    except (json.JSONDecodeError, IndexError, KeyError):
                                        pass
                            # Save & extract
                            if full_response:
                                add_conversation_message(user_id, "assistant", full_response)
                                all_msgs = messages + [{"role": "assistant", "content": full_response}]
                                asyncio.create_task(_safe_extract(user_id, all_msgs))
                            return

                        # No search marker — flush buffered chunks
                        for bc in buffered_chunks:
                            yield bc
                        full_response += buffer_text
                        buffered_chunks = []
                        buffer_text = ""
                else:
                    # Not in buffer phase or search disabled — stream directly
                    if not search_checked and not search_enabled:
                        search_checked = True
                    yield chunk
                    full_response += token
            else:
                # Non-data chunks (e.g. [DONE])
                if not search_checked:
                    search_checked = True
                    # Flush any remaining buffer
                    for bc in buffered_chunks:
                        yield bc
                    full_response += buffer_text
                yield chunk

        # If we never reached buffer limit (very short response), flush buffer
        if buffered_chunks:
            for bc in buffered_chunks:
                yield bc
            full_response += buffer_text

        if full_response:
            add_conversation_message(user_id, "assistant", full_response)
            all_msgs = messages + [{"role": "assistant", "content": full_response}]
            asyncio.create_task(_safe_extract(user_id, all_msgs))

    return StreamingResponse(stream_wrapper(), media_type="text/event-stream")


async def _safe_extract(user_id: str, messages: list[dict]):
    """Safely run memory extraction in background."""
    try:
        await extract_memories_from_conversation(user_id, messages)
    except Exception as e:
        log.error(f"Background memory extraction failed: {e}")


@router.get("/v1/models")
async def list_models():
    try:
        models = await lmstudio.list_models()
        return {"object": "list", "data": models}
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Could not reach LMStudio: {e}"},
        )


# ══════════════════════════════════════════════════
# Ollama-compatible API (for HA Ollama integration)
# ══════════════════════════════════════════════════

@router.get("/api/tags")
async def ollama_list_models(request: Request):
    """Ollama-compatible model list — used by HA Ollama integration during setup."""
    _validate_api_key(request)
    cfg = load_config()
    model_name = cfg["lmstudio"].get("model", "default")
    try:
        models = await lmstudio.list_models()
        ollama_models = []
        for m in models:
            mid = m.get("id", model_name)
            ollama_models.append({
                "name": mid,
                "model": mid,
                "modified_at": "2025-01-01T00:00:00Z",
                "size": 0,
                "digest": "",
                "details": {
                    "parent_model": "",
                    "format": "gguf",
                    "family": "llama",
                    "parameter_size": "",
                    "quantization_level": "",
                },
            })
        if not ollama_models:
            ollama_models.append({
                "name": model_name,
                "model": model_name,
                "modified_at": "2025-01-01T00:00:00Z",
                "size": 0,
                "digest": "",
                "details": {"parent_model": "", "format": "gguf", "family": "llama", "parameter_size": "", "quantization_level": ""},
            })
        return {"models": ollama_models}
    except Exception:
        # Even if LMStudio is down, return a default model so HA can complete setup
        return {"models": [{
            "name": model_name,
            "model": model_name,
            "modified_at": "2025-01-01T00:00:00Z",
            "size": 0,
            "digest": "",
            "details": {"parent_model": "", "format": "gguf", "family": "llama", "parameter_size": "", "quantization_level": ""},
        }]}


@router.post("/api/pull")
async def ollama_pull_model(request: Request):
    """Ollama-compatible model pull — stub that always succeeds (models are on LMStudio)."""
    _validate_api_key(request)
    body = await request.json()
    model_name = body.get("name", body.get("model", "default"))
    return JSONResponse(content={"status": "success"})



@router.post("/api/chat")
async def ollama_chat(request: Request):
    """Ollama-compatible chat endpoint — translates to internal processing pipeline."""
    _validate_api_key(request)
    body = await request.json()
    messages = body.get("messages", [])
    model = body.get("model")
    stream = body.get("stream", False)
    user_id = _extract_user_id(request, body)
    cfg = load_config()
    search_enabled = cfg["searxng"].get("enabled", False)

    # ── Build augmented messages (same logic as OpenAI endpoint) ──
    augmented: list[dict] = []

    system_prompt = cfg.get("system_prompt", "")
    if system_prompt:
        augmented.append({"role": "system", "content": system_prompt})

    if search_enabled:
        augmented.append({"role": "system", "content": _build_search_instruction(cfg)})

    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "")
            break

    history_limit = cfg.get("performance", {}).get("history_limit", 10)
    memories, history = await asyncio.gather(
        retrieve_relevant_memories(user_id, last_user_msg),
        asyncio.to_thread(get_conversation_history, user_id, history_limit),
    )

    mem_ctx = build_memory_context(memories)
    if mem_ctx:
        augmented.append({"role": "system", "content": mem_ctx})

    if history:
        augmented.extend(history)

    augmented.extend(messages)

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content and role in ("user", "assistant"):
            add_conversation_message(user_id, role, content)

    # ── Forward to LMStudio and convert response to Ollama format ──
    if stream:
        gen = lmstudio.chat_completion_stream(augmented, model=model)
        _model_name = model or cfg["lmstudio"]["model"]

        async def ollama_stream():
            full_response = ""
            buffer_text = ""
            buffer_tokens = []
            search_checked = False

            def _ollama_token(token):
                return json.dumps({
                    "model": _model_name,
                    "created_at": "2025-01-01T00:00:00Z",
                    "message": {"role": "assistant", "content": token},
                    "done": False,
                }) + "\n"

            async for chunk in gen:
                if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                    try:
                        data = json.loads(chunk[6:])
                        delta = data.get("choices", [{}])[0].get("delta", {})
                        token = delta.get("content", "")
                    except (json.JSONDecodeError, IndexError, KeyError):
                        token = ""

                    if not search_checked and search_enabled:
                        buffer_tokens.append(token)
                        buffer_text += token

                        if len(buffer_text) >= 120 or _SEARCH_MARKER.search(buffer_text):
                            search_checked = True
                            match = _SEARCH_MARKER.search(buffer_text)
                            if match:
                                query = match.group(1).strip()[:200]
                                log.info(f"AI requested search (ollama stream): {query}")
                                async for _ in gen:
                                    pass
                                search_ctx = ""
                                try:
                                    search_ctx = await search_and_fetch(query)
                                except Exception as e:
                                    log.error(f"Search failed: {e}")

                                if search_ctx:
                                    augmented.append({
                                        "role": "system",
                                        "content": (
                                            "[Web search results — use this to answer accurately. "
                                            "Cite sources with [N]. Summarize clearly, do not paste raw text. "
                                            "Do NOT use the <<SEARCH>> marker again.]:\n"
                                            f"{search_ctx}"
                                        ),
                                    })
                                else:
                                    augmented.append({
                                        "role": "system",
                                        "content": "Search is temporarily unavailable. Answer from your training data. Do NOT use <<SEARCH>> marker.",
                                    })

                                gen2 = lmstudio.chat_completion_stream(augmented, model=model)
                                async for chunk2 in gen2:
                                    if chunk2.startswith("data: ") and chunk2.strip() != "data: [DONE]":
                                        try:
                                            d2 = json.loads(chunk2[6:])
                                            t2 = d2.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                            full_response += t2
                                            yield _ollama_token(t2)
                                        except (json.JSONDecodeError, IndexError, KeyError):
                                            pass

                                yield json.dumps({
                                    "model": _model_name, "created_at": "2025-01-01T00:00:00Z",
                                    "message": {"role": "assistant", "content": ""}, "done": True,
                                    "total_duration": 0, "eval_count": 0,
                                }) + "\n"
                                if full_response:
                                    add_conversation_message(user_id, "assistant", full_response)
                                    all_msgs = messages + [{"role": "assistant", "content": full_response}]
                                    asyncio.create_task(_safe_extract(user_id, all_msgs))
                                return

                            # No marker — flush buffer
                            for bt in buffer_tokens:
                                if bt:
                                    yield _ollama_token(bt)
                            full_response += buffer_text
                            buffer_tokens = []
                            buffer_text = ""
                    else:
                        if not search_checked:
                            search_checked = True
                        if token:
                            yield _ollama_token(token)
                        full_response += token

            # Flush any remaining buffer
            if buffer_tokens:
                for bt in buffer_tokens:
                    if bt:
                        yield _ollama_token(bt)
                full_response += buffer_text

            # Final done message
            yield json.dumps({
                "model": _model_name,
                "created_at": "2025-01-01T00:00:00Z",
                "message": {"role": "assistant", "content": ""},
                "done": True,
                "total_duration": 0,
                "eval_count": 0,
            }) + "\n"
            if full_response:
                add_conversation_message(user_id, "assistant", full_response)
                all_msgs = messages + [{"role": "assistant", "content": full_response}]
                asyncio.create_task(_safe_extract(user_id, all_msgs))

        return StreamingResponse(ollama_stream(), media_type="application/x-ndjson")
    else:
        result = await lmstudio.chat_completion(augmented, model=model)

        try:
            assistant_content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            assistant_content = ""

        # Check if AI requested search
        if search_enabled and assistant_content:
            match = _SEARCH_MARKER.search(assistant_content)
            if match:
                query = match.group(1).strip()[:200]
                log.info(f"AI requested search (ollama): {query}")
                try:
                    search_ctx = await search_and_fetch(query)
                except Exception as e:
                    log.error(f"Search failed: {e}")
                    search_ctx = ""

                if search_ctx:
                    augmented.append({
                        "role": "system",
                        "content": (
                            "[Web search results — use this to answer accurately. "
                            "Cite sources with [N]. Summarize clearly, do not paste raw text. "
                            "Do NOT use the <<SEARCH>> marker again.]:\n"
                            f"{search_ctx}"
                        ),
                    })
                    result = await lmstudio.chat_completion(augmented, model=model)
                    try:
                        assistant_content = result["choices"][0]["message"]["content"]
                    except (KeyError, IndexError):
                        pass

        if assistant_content:
            add_conversation_message(user_id, "assistant", assistant_content)
            all_msgs = messages + [{"role": "assistant", "content": assistant_content}]
            asyncio.create_task(_safe_extract(user_id, all_msgs))

        # Ollama response format
        return JSONResponse(content={
            "model": model or cfg["lmstudio"]["model"],
            "created_at": "2025-01-01T00:00:00Z",
            "message": {"role": "assistant", "content": assistant_content},
            "done": True,
            "total_duration": 0,
            "eval_count": 0,
        })