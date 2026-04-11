"""
OpenAI-compatible /v1/chat/completions endpoint.
The HASSAI Bridge HA integration sends requests here. We:
1. Check for slash commands (/health, /settings, /help, etc.)
2. Retrieve relevant memories for the user
3. Forward augmented request to LMStudio
4. If LLM requests web search (<<SEARCH: query>>), search and re-prompt
5. Extract new memories from the conversation (background, non-blocking)
"""

import json
import asyncio
import logging
import re
import socket
import time
from datetime import date
from pathlib import Path
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import StreamingResponse, JSONResponse

from config import load_config
from core.config import VERSION
from database import (
    add_conversation_message,
    get_conversation_history,
    get_memory_stats,
)
from services import lmstudio, searxng
from services.memory_engine import (
    retrieve_relevant_memories,
    build_memory_context,
    extract_memories_from_conversation,
)
from services.web_scraper import search_and_fetch

log = logging.getLogger("hassai.chat")
router = APIRouter()

# ── Start time for /uptime command ──
_cmd_start_time = time.time()


# ══════════════════════════════════════════════════
# Slash commands — intercepted before LLM processing
# ══════════════════════════════════════════════════

def _get_local_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


async def _handle_command(cmd: str, user_id: str) -> str | None:
    """Handle slash commands. Returns response text or None if not a command."""
    cmd = cmd.strip()
    if not cmd.startswith("/"):
        return None

    parts = cmd.split(None, 1)
    command = parts[0].lower()
    # arg = parts[1].strip() if len(parts) > 1 else ""

    cfg = load_config()
    ip = _get_local_ip()
    port = 8899
    base = f"http://{ip}:{port}"

    if command == "/help":
        return (
            "📋 **Comenzi disponibile:**\n\n"
            "• `/health` — Status servicii (LMStudio, SearXNG, Memorie)\n"
            "• `/settings` — Link-uri de acces la panoul de control\n"
            "• `/info` — Informații sistem (versiune, uptime, statistici)\n"
            "• `/memory` — Statisticile memoriei tale\n"
            "• `/models` — Modelele disponibile pe LMStudio\n"
            "• `/version` — Versiunea curentă\n"
            "• `/restart` — Restart server HASSAI Bridge\n"
            "• `/help` — Această listă de comenzi"
        )

    elif command == "/health":
        lm_ok = await lmstudio.health_check()
        sx_ok = await searxng.health_check()
        lm_status = "✅ Conectat" if lm_ok else "❌ Indisponibil"
        sx_enabled = cfg["searxng"].get("enabled", False)
        if not sx_enabled:
            sx_status = "⚪ Dezactivat"
        elif sx_ok:
            sx_status = "✅ Conectat"
        else:
            sx_status = "❌ Indisponibil"
        mem_enabled = cfg["memory"].get("enabled", False)
        mem_status = "✅ Activ" if mem_enabled else "⚪ Dezactivat"
        return (
            "🏥 **Status Servicii:**\n\n"
            f"• **LMStudio:** {lm_status} — `{cfg['lmstudio']['base_url']}` (model: {cfg['lmstudio']['model']})\n"
            f"• **SearXNG:** {sx_status} — `{cfg['searxng']['base_url']}`\n"
            f"• **Memorie AI:** {mem_status}"
        )

    elif command == "/settings":
        return (
            "⚙️ **Panou de Control:**\n\n"
            f"• **Web UI:** {base}\n"
            f"• **API (OpenAI):** {base}/v1\n"
            f"• **Setări API:** {base}/api/settings/\n"
            f"• **Health Check:** {base}/api/settings/health"
        )

    elif command == "/info":
        uptime_sec = time.time() - _cmd_start_time
        d = int(uptime_sec // 86400)
        h = int((uptime_sec % 86400) // 3600)
        m = int((uptime_sec % 3600) // 60)
        uptime_str = f"{d}z {h}h {m}m" if d > 0 else f"{h}h {m}m" if h > 0 else f"{m}m"
        return (
            f"ℹ️ **HASSAI Bridge {VERSION}**\n\n"
            f"• **Uptime:** {uptime_str}\n"
            f"• **IP LAN:** {ip}\n"
            f"• **Port:** {port}\n"
            f"• **Model:** {cfg['lmstudio']['model']}\n"
            f"• **Max Tokens:** {cfg['lmstudio'].get('max_tokens', 2048)}\n"
            f"• **Temperatură:** {cfg['lmstudio'].get('temperature', 0.7)}"
        )

    elif command == "/memory":
        stats = get_memory_stats(user_id)
        lines = [f"🧠 **Memorii pentru {user_id}:**\n"]
        lines.append(f"• **Total:** {stats['total']}")
        for cat, count in stats.get("by_category", {}).items():
            lines.append(f"• **{cat}:** {count}")
        return "\n".join(lines)

    elif command == "/models":
        try:
            models = await lmstudio.list_models()
            if models:
                lines = ["🤖 **Modele disponibile:**\n"]
                for m in models:
                    mid = m.get("id", "unknown")
                    lines.append(f"• `{mid}`")
                return "\n".join(lines)
            else:
                return "🤖 Niciun model disponibil."
        except Exception:
            return "❌ Nu s-a putut contacta LMStudio pentru lista de modele."

    elif command == "/version":
        return f"🏠 HASSAI Bridge **{VERSION}**"

    elif command == "/restart":
        import subprocess
        import os
        # Touch a file to trigger uvicorn reload watcher
        _trigger = Path(__file__).parent.parent / ".restart_trigger"
        _trigger.write_text(str(time.time()))
        return "🔄 **Server-ul se restartează...**\n\nAșteaptă câteva secunde, apoi reîmprospătează pagina."

    else:
        return (
            f"❓ Comandă necunoscută: `{command}`\n\n"
            "Scrie `/help` pentru lista de comenzi disponibile."
        )


def _command_response_openai(content: str, model: str) -> dict:
    """Build an OpenAI-compatible response for a command result."""
    return {
        "id": f"cmd-{int(time.time())}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or "hassai-bridge",
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": content},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def _estimate_tokens(text: str) -> int:
    """Estimate token count: ~1.3 tokens per word (heuristic)."""
    return max(1, int(len(text.split()) * 1.3))


def _trim_messages(messages: list[dict], max_tokens: int) -> list[dict]:
    """Trim conversation to fit within token budget.

    Keeps system messages and trims oldest non-system messages first.
    """
    system_msgs = [m for m in messages if m.get("role") == "system"]
    other_msgs = [m for m in messages if m.get("role") != "system"]

    system_tokens = sum(_estimate_tokens(m.get("content", "")) for m in system_msgs)
    budget = max_tokens - system_tokens
    if budget <= 0:
        return system_msgs  # system messages alone exceed budget

    # Keep as many recent messages as fit
    kept = []
    used = 0
    for msg in reversed(other_msgs):
        cost = _estimate_tokens(msg.get("content", ""))
        if used + cost > budget:
            break
        kept.append(msg)
        used += cost

    kept.reverse()
    return system_msgs + kept

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

# ── SSE keepalive interval (seconds) to prevent client timeout during prompt processing ──
_KEEPALIVE_INTERVAL = 3


async def _stream_with_keepalive_sse(gen, interval: float = _KEEPALIVE_INTERVAL):
    """Wrap an async generator with periodic SSE keepalive comments.

    Prevents client disconnect during long prompt processing by sending
    SSE comments (`: keepalive\\n\\n`) which are ignored by spec-compliant clients.
    Uses asyncio.shield to prevent cancelling the upstream read on timeout.
    """
    gen_iter = gen.__aiter__()
    next_task = None
    while True:
        if next_task is None:
            next_task = asyncio.ensure_future(gen_iter.__anext__())
        try:
            chunk = await asyncio.wait_for(asyncio.shield(next_task), timeout=interval)
            next_task = None
            yield chunk
        except asyncio.TimeoutError:
            # Upstream read still in progress — send keepalive without cancelling it
            yield ": keepalive\n\n"
        except StopAsyncIteration:
            break


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

    # Try Bearer token first
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
    tools = body.get("tools")
    tool_choice = body.get("tool_choice")
    user_id = _extract_user_id(request, body)
    cfg = load_config()
    search_enabled = cfg["searxng"].get("enabled", False)

    # ── Slash command check ──
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "").strip()
            break

    cmd_result = await _handle_command(last_user_msg, user_id)
    if cmd_result is not None:
        add_conversation_message(user_id, "user", last_user_msg)
        add_conversation_message(user_id, "assistant", cmd_result)
        if stream:
            # Stream the command response as a single chunk
            chunk_data = json.dumps({
                "id": f"cmd-{int(time.time())}",
                "object": "chat.completion.chunk",
                "created": int(time.time()),
                "model": model or "hassai-bridge",
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": cmd_result}, "finish_reason": "stop"}],
            })
            async def cmd_stream():
                yield f"data: {chunk_data}\n\n"
                yield "data: [DONE]\n\n"
            return StreamingResponse(cmd_stream(), media_type="text/event-stream")
        return JSONResponse(content=_command_response_openai(cmd_result, model))

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
    history_limit = cfg.get("performance", {}).get("history_limit", 10)
    memories, history = await asyncio.gather(
        retrieve_relevant_memories(user_id, last_user_msg),
        asyncio.to_thread(get_conversation_history, user_id, history_limit),
    )

    mem_ctx = build_memory_context(memories, user_id=user_id, message=last_user_msg)
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

    # ── Trim to fit context window ──
    max_ctx = cfg["lmstudio"].get("max_tokens", 2048) * 3  # rough context budget
    augmented = _trim_messages(augmented, max_ctx)

    # ── First LLM call ──
    # For non-streaming: check if LLM requests search, then re-prompt with results
    if not stream:
        try:
            result = await lmstudio.chat_completion(augmented, model=model, tools=tools, tool_choice=tool_choice)
        except Exception as e:
            log.error(f"LMStudio request failed: {e}")
            return JSONResponse(
                status_code=502,
                content={"error": {"message": f"LMStudio error: {e}", "type": "upstream_error"}},
            )
        try:
            assistant_content = result["choices"][0]["message"]["content"]
        except (KeyError, IndexError):
            assistant_content = ""

        # If LLM returned tool_calls, forward immediately (no search/memory processing)
        if result.get("choices", [{}])[0].get("message", {}).get("tool_calls"):
            # Clear content when tool_calls present (avoid leaking reasoning text)
            result["choices"][0]["message"]["content"] = ""
            return JSONResponse(content=result)

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
    gen = lmstudio.chat_completion_stream(augmented, model=model, tools=tools, tool_choice=tool_choice)

    _SEARCH_BUFFER_CHARS = 120  # search markers appear in the first ~100 chars

    async def stream_wrapper():
        full_response = ""
        buffered_chunks = []
        buffer_text = ""
        search_checked = False

        async for chunk in _stream_with_keepalive_sse(gen):
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
                            gen2 = lmstudio.chat_completion_stream(augmented, model=model, tools=tools, tool_choice=tool_choice)
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
