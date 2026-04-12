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
    add_usage_stat,
)
from services import providers
from services.providers import get_active_provider
from services import searxng
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
    # arg = parts[1].strip() if len(parts) > 1 else ""  # used by /setmodel

    cfg = load_config()
    ip = _get_local_ip()
    port = 8899
    base = f"http://{ip}:{port}"

    if command == "/help":
        return (
            "📋 **Available commands:**\n\n"
            "• `/health` — Service status (LLM Provider, Web Search, Memory)\n"
            "• `/settings` — Access links to the control panel\n"
            "• `/info` — System info (version, uptime, stats)\n"
            "• `/memory` — Your memory statistics\n"
            "• `/models` — Available models on the active provider\n"
            "• `/setmodel [name|#]` — Change model on the active provider\n"
            "• `/setprovider [name|#]` — Switch active AI provider\n"
            "• `/version` — Current version\n"
            "• `/restart` — Restart HASSAI Bridge server\n"
            "• `/help` — This command list"
        )

    elif command == "/health":
        active = get_active_provider()
        lm_ok = await providers.health_check(active)
        sx_ok = await searxng.health_check()
        lm_status = "✅ Connected" if lm_ok else "❌ Unavailable"
        sx_enabled = cfg["searxng"].get("enabled", False)
        if not sx_enabled:
            sx_status = "⚪ Disabled"
        elif sx_ok:
            sx_status = "✅ Connected"
        else:
            sx_status = "❌ Unavailable"
        mem_enabled = cfg["memory"].get("enabled", False)
        mem_status = "✅ Active" if mem_enabled else "⚪ Disabled"
        return (
            "🏥 **Service Status:**\n\n"
            f"• **AI Provider:** {lm_status} — `{active.get('name', '?')}` ({active.get('type', '?')}) model: {active.get('model', '?')}\n"
            f"• **Web Search:** {sx_status} — `{cfg['searxng']['base_url']}`\n"
            f"• **AI Memory:** {mem_status}"
        )

    elif command == "/settings":
        return (
            "⚙️ **Control Panel:**\n\n"
            f"• **Web UI:** {base}\n"
            f"• **API (OpenAI):** {base}/v1\n"
            f"• **Settings API:** {base}/api/settings/\n"
            f"• **Health Check:** {base}/api/settings/health"
        )

    elif command == "/info":
        uptime_sec = time.time() - _cmd_start_time
        d = int(uptime_sec // 86400)
        h = int((uptime_sec % 86400) // 3600)
        m = int((uptime_sec % 3600) // 60)
        uptime_str = f"{d}d {h}h {m}m" if d > 0 else f"{h}h {m}m" if h > 0 else f"{m}m"
        active = get_active_provider()
        return (
            f"ℹ️ **HASSAI Bridge {VERSION}**\n\n"
            f"• **Uptime:** {uptime_str}\n"
            f"• **LAN IP:** {ip}\n"
            f"• **Port:** {port}\n"
            f"• **Provider:** {active.get('name', '?')} ({active.get('type', '?')})\n"
            f"• **Model:** {active.get('model', '?')}\n"
            f"• **Max Tokens:** {active.get('max_tokens', 2048)}\n"
            f"• **Temperature:** {active.get('temperature', 0.7)}"
        )

    elif command == "/memory":
        stats = get_memory_stats(user_id)
        lines = [f"🧠 **Memories for {user_id}:**\n"]
        lines.append(f"• **Total:** {stats['total']}")
        for cat, count in stats.get("by_category", {}).items():
            lines.append(f"• **{cat}:** {count}")
        return "\n".join(lines)

    elif command == "/models":
        try:
            active = get_active_provider()
            models = await providers.list_models(active)
            if models:
                lines = [f"🤖 **Available models ({active.get('name', '?')}):**\n"]
                current_model = active.get("model", "")
                for i, m in enumerate(models, 1):
                    mid = m.get("id", "unknown")
                    marker = " ✅" if mid == current_model else ""
                    lines.append(f"**{i}.** `{mid}`{marker}")
                lines.append(f"\nUse `/setmodel <name|#>` to switch.")
                return "\n".join(lines)
            else:
                return "🤖 No models available on the active provider."
        except Exception:
            return "❌ Could not reach the active provider for model list."

    elif command == "/version":
        return f"🏠 HASSAI Bridge **{VERSION}**"

    elif command == "/restart":
        import subprocess
        import os
        # Touch a file to trigger uvicorn reload watcher
        _trigger = Path(__file__).parent.parent / ".restart_trigger"
        _trigger.write_text(str(time.time()))
        return "🔄 **Server is restarting...**\n\nWait a few seconds, then refresh the page."

    elif command == "/setprovider":
        from config import save_config
        arg = parts[1].strip() if len(parts) > 1 else ""
        all_providers = cfg.get("providers", [])
        if not arg:
            # List available providers
            if not all_providers:
                return "❌ No providers configured. Add one from the Web UI > Settings."
            lines = ["🔄 **Available providers:**\n"]
            active_id = cfg.get("active_provider", "")
            for i, p in enumerate(all_providers, 1):
                marker = " ✅" if p["id"] == active_id else ""
                lines.append(f"**{i}.** `{p.get('name', '?')}` — {p.get('type', '?')} model: {p.get('model', '?')}{marker}")
            lines.append(f"\nUse `/setprovider <name|#>` to switch.")
            return "\n".join(lines)
        # Try numeric index first
        match = None
        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(all_providers):
                match = all_providers[idx]
        if not match:
            # Find provider by id (or partial match)
            for p in all_providers:
                if p["id"] == arg or p["id"].startswith(arg):
                    match = p
                    break
        if not match:
            # Try matching by name
            for p in all_providers:
                if arg.lower() in p.get("name", "").lower():
                    match = p
                    break
        if not match:
            return f"❌ Provider `{arg}` not found. Use `/setprovider` to see available providers."
        cfg["active_provider"] = match["id"]
        save_config(cfg)
        return f"✅ Switched to **{match.get('name', match['id'])}** ({match.get('type', '?')}) — model: `{match.get('model', '?')}`"

    elif command == "/setmodel":
        from config import save_config
        arg = parts[1].strip() if len(parts) > 1 else ""
        active = get_active_provider()
        if not arg:
            # List models on active provider
            try:
                models = await providers.list_models(active)
            except Exception:
                return "❌ Could not reach the active provider for model list."
            if not models:
                return "🤖 No models available on the active provider."
            lines = [f"🤖 **Models on {active.get('name', '?')}:**\n"]
            current_model = active.get("model", "")
            for i, m in enumerate(models, 1):
                mid = m.get("id", "unknown")
                marker = " ✅" if mid == current_model else ""
                lines.append(f"**{i}.** `{mid}`{marker}")
            lines.append(f"\nUse `/setmodel <name|#>` to switch.")
            return "\n".join(lines)
        # Try numeric index — need to fetch models
        chosen = None
        if arg.isdigit():
            try:
                models = await providers.list_models(active)
                idx = int(arg) - 1
                if 0 <= idx < len(models):
                    chosen = models[idx].get("id")
            except Exception:
                return "❌ Could not reach the active provider for model list."
            if chosen is None:
                return f"❌ Model #{arg} not found. Use `/setmodel` to see available models."
        else:
            chosen = arg
        # Update model on the active provider in config
        all_providers = cfg.get("providers", [])
        for p in all_providers:
            if p["id"] == active["id"]:
                p["model"] = chosen
                break
        cfg["providers"] = all_providers
        save_config(cfg)
        return f"✅ Model changed to `{chosen}` on **{active.get('name', active['id'])}**"

    else:
        return (
            f"❓ Unknown command: `{command}`\n\n"
            "Type `/help` for available commands."
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
    """Estimate token count using word-based heuristic.

    ~1.3 tokens per word for English, ~1.5 for non-Latin (Romanian diacritics, CJK).
    """
    words = text.split()
    if not words:
        return 1
    # Non-ASCII heavy text tends to tokenize into more tokens
    non_ascii_ratio = sum(1 for c in text if ord(c) > 127) / max(len(text), 1)
    multiplier = 1.5 if non_ascii_ratio > 0.1 else 1.3
    return max(1, int(len(words) * multiplier))


def _sanitize_message_roles(messages: list[dict]) -> list[dict]:
    """Fix message list to respect role alternation rules expected by chat templates.

    1. Ensure the first non-system message is a user message (drop leading assistants)
    2. Merge consecutive messages with the same role
    3. Drop empty content messages (except tool_calls)
    """
    system_msgs = []
    other_msgs = []

    for m in messages:
        if m.get("role") == "system":
            system_msgs.append(m)
        else:
            other_msgs.append(m)

    if not other_msgs:
        return system_msgs

    # Drop leading assistant messages (before the first user message)
    while other_msgs and other_msgs[0].get("role") != "user":
        other_msgs.pop(0)

    if not other_msgs:
        return system_msgs

    # Merge consecutive same-role messages and drop empty ones
    cleaned = []
    for m in other_msgs:
        content = (m.get("content") or "").strip()
        role = m.get("role", "user")

        # Keep tool_calls messages even if content is empty
        if not content and not m.get("tool_calls") and role != "tool":
            continue

        if cleaned and cleaned[-1].get("role") == role and role != "tool":
            # Merge with previous message of same role
            prev_content = (cleaned[-1].get("content") or "").strip()
            if content and prev_content:
                cleaned[-1]["content"] = prev_content + "\n" + content
            elif content:
                cleaned[-1]["content"] = content
        else:
            cleaned.append(dict(m))

    return system_msgs + cleaned


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
# AI-driven search via function-calling (tool_calls)
# Like hass_memory/brain/toolbox.py — reliable, no marker parsing.
# ══════════════════════════════════════════════════

_SEARCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": (
            "Search the web for current/time-sensitive information: today's news, "
            "live weather, current prices, recent events, things after your knowledge cutoff. "
            "Do NOT search for facts you already know from training data (definitions, history, "
            "science, geography, famous people, how things work, programming, math). "
            "Reformulate into a short keyword-focused query (3-7 words). "
            "One search should usually be enough."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Optimized search query: short, keyword-focused, English preferred for technical topics.",
                }
            },
            "required": ["query"],
        },
    },
}

# For stripping old <<SEARCH:...>> markers from conversation history (legacy cleanup)
_SEARCH_MARKER_STRIP = re.compile(r"<<SEARCH:[^>\n]*(?:>>)?")


def _strip_search_markers(text: str) -> str:
    """Remove any <<SEARCH:...>> markers from text (legacy cleanup)."""
    return _SEARCH_MARKER_STRIP.sub("", text).strip()


def _build_search_instruction(cfg: dict) -> str:
    """Short context hint about the knowledge cutoff and search availability."""
    cutoff = cfg.get("knowledge_cutoff", "2024-01")
    today = date.today().strftime("%Y-%m-%d")
    return (
        f"Today's date: {today}. "
        f"Your training data has a knowledge cutoff of {cutoff}. "
        "You have a search_web tool available for current information. "
        "Use it when the user asks about anything that may have changed after your cutoff "
        "(news, prices, weather, events, current leaders, scores, etc.). "
        "Do NOT say 'I don't have access to search' or 'I cannot browse the internet'. "
        "If you can answer confidently from your training data, answer normally."
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

    # Build effective tools list: client tools + search_web if enabled
    all_tools = list(tools or []) if tools else []
    if search_enabled:
        all_tools.append(_SEARCH_WEB_TOOL)
    effective_tools = all_tools if all_tools else None

    # ── Slash command check ──
    last_user_msg = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_msg = msg.get("content", "").strip()
            break

    # ── Message size validation (#16) ──
    total_size = sum(len(m.get("content", "")) for m in messages)
    if total_size > 512_000:  # 500KB max
        return JSONResponse(
            status_code=413,
            content={"error": {"message": "Message content too large (max 500KB)", "type": "invalid_request_error"}},
        )
    for msg in messages:
        if len(msg.get("content", "")) > 100_000:  # 100KB per message
            return JSONResponse(
                status_code=413,
                content={"error": {"message": "Single message too large (max 100KB)", "type": "invalid_request_error"}},
            )

    cmd_result = await _handle_command(last_user_msg, user_id)
    if cmd_result is not None:
        # Slash commands: save only user msg, not polluting history with /health etc. (#18)
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

    # 1) System prompt (per-provider overrides global)
    active = get_active_provider()
    system_prompt = (active.get("system_prompt") or "").strip() or cfg.get("system_prompt", "")
    if system_prompt:
        augmented.append({"role": "system", "content": system_prompt})

    # 2) Memory + history retrieval (parallel)
    history_limit = cfg.get("performance", {}).get("history_limit", 10)
    memories, history = await asyncio.gather(
        retrieve_relevant_memories(user_id, last_user_msg),
        asyncio.to_thread(get_conversation_history, user_id, history_limit),
    )

    mem_ctx = build_memory_context(memories, user_id=user_id, message=last_user_msg)
    if mem_ctx:
        augmented.append({"role": "system", "content": mem_ctx})

    # 3) Search instruction AFTER memories (#4) — so LLM sees full context before deciding to search
    if search_enabled:
        augmented.append({"role": "system", "content": _build_search_instruction(cfg)})

    # 4) Conversation history — only add DB history if incoming messages
    #    don't already contain a conversation (HA sends full history)
    incoming_roles = {m.get("role") for m in messages}
    has_incoming_history = "assistant" in incoming_roles and "user" in incoming_roles
    if history and not has_incoming_history:
        augmented.extend(history)

    # 5) Current messages
    augmented.extend(messages)

    # ── Save user messages to history ──
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if content and role in ("user", "assistant"):
            add_conversation_message(user_id, role, content)

    # ── Strip any <<SEARCH markers that leaked into stored assistant messages ──
    for m in augmented:
        c = m.get("content", "")
        if c and m.get("role") == "assistant" and "<<SEARCH" in c:
            cleaned = _strip_search_markers(c).strip()
            m["content"] = cleaned if cleaned else "(search attempted)"

    # ── Sanitize role order + trim to fit context window ──
    augmented = _sanitize_message_roles(augmented)
    max_ctx = active.get("max_tokens", 2048) * 3  # rough context budget
    augmented = _trim_messages(augmented, max_ctx)

    # ── First LLM call ──
    _req_start = time.time()
    _search_used = False
    if not stream:
        try:
            result = await providers.chat_completion(augmented, model=model, tools=effective_tools, tool_choice=tool_choice, provider=active)
        except Exception as e:
            log.error(f"Provider [{active.get('name', '?')}] request failed: {e}")
            return JSONResponse(
                status_code=502,
                content={"error": {"message": f"Provider error: {e}", "type": "upstream_error"}},
            )

        # ── Handle tool_calls (search_web + forwarding) ──
        # Up to 2 search rounds; non-search tool_calls are forwarded to client.
        for _round in range(2):
            msg = result.get("choices", [{}])[0].get("message", {})
            tool_calls = msg.get("tool_calls") or []
            if not tool_calls:
                break

            search_call = next(
                (tc for tc in tool_calls if tc.get("function", {}).get("name") == "search_web"),
                None,
            )
            if not (search_enabled and search_call):
                # No search_web call — forward tool_calls to client (HA)
                msg["content"] = ""
                return JSONResponse(content=result)

            # Execute search_web tool
            try:
                args = json.loads(search_call["function"]["arguments"])
                query = (args.get("query") or "").strip()[:200]
            except (json.JSONDecodeError, KeyError):
                query = ""
            if not query:
                break

            log.info(f"AI requested search (tool, round {_round + 1}): {query}")
            _search_used = True
            try:
                search_ctx = await search_and_fetch(query)
            except Exception as e:
                log.error(f"Search failed: {e}")
                search_ctx = ""

            # Add the tool exchange to conversation
            augmented.append(msg)  # assistant message with tool_calls
            augmented.append({
                "role": "tool",
                "tool_call_id": search_call.get("id", "call_search"),
                "content": (
                    f"[Web search results for '{query}' — use this to answer accurately. "
                    "Summarize clearly in your own words, do not paste raw text or cite sources.]\n"
                    + (search_ctx or "No results found.")
                ),
            })

            # Re-call without search_web tool to avoid loops
            re_tools = [t for t in all_tools if t.get("function", {}).get("name") != "search_web"]
            result = await providers.chat_completion(
                augmented, model=model, tools=re_tools or None,
                tool_choice=tool_choice, provider=active,
            )

        # If final result still has non-search tool_calls, forward to client
        final_msg = result.get("choices", [{}])[0].get("message", {})
        if final_msg.get("tool_calls"):
            remaining = [tc for tc in final_msg["tool_calls"] if tc.get("function", {}).get("name") != "search_web"]
            if remaining:
                final_msg["tool_calls"] = remaining
                final_msg["content"] = ""
                return JSONResponse(content=result)
            else:
                del final_msg["tool_calls"]

        assistant_content = final_msg.get("content", "") or ""

        # Strip any legacy <<SEARCH>> markers from content
        if assistant_content and _SEARCH_MARKER_STRIP.search(assistant_content):
            assistant_content = _strip_search_markers(assistant_content)
            result["choices"][0]["message"]["content"] = assistant_content

        # Save & extract memories
        if assistant_content:
            add_conversation_message(user_id, "assistant", assistant_content)
            all_msgs = messages + [{"role": "assistant", "content": assistant_content}]
            asyncio.create_task(_safe_extract(user_id, all_msgs))

        # Track usage statistics
        try:
            usage = result.get("usage", {})
            add_usage_stat(
                user_id=user_id, provider_id=active.get("id", ""),
                provider_name=active.get("name", ""), provider_type=active.get("type", ""),
                model=result.get("model", model or active.get("model", "")),
                tokens_prompt=usage.get("prompt_tokens", 0),
                tokens_completion=usage.get("completion_tokens", 0),
                tokens_total=usage.get("total_tokens", 0),
                response_time_ms=int((time.time() - _req_start) * 1000),
                stream=False, search_used=_search_used,
            )
        except Exception:
            pass

        return JSONResponse(content=result)

    # ── Streaming path ──
    # Uses tool_calls for search (like hass_memory). No marker parsing needed.
    # Tool call chunks are accumulated silently; content/reasoning chunks pass through.
    gen = providers.chat_completion_stream(augmented, model=model, tools=effective_tools, tool_choice=tool_choice, provider=active)

    async def stream_wrapper():
        nonlocal augmented
        full_response = ""
        # Accumulate streaming tool_call deltas
        tc_accum: dict[int, dict] = {}  # index -> {id, name, arguments}
        tc_chunks: list[str] = []  # raw chunks for forwarding if not search
        has_tool_calls = False

        async for chunk in _stream_with_keepalive_sse(gen):
            if chunk.startswith("data: ") and chunk.strip() != "data: [DONE]":
                try:
                    data = json.loads(chunk[6:])
                    delta = data.get("choices", [{}])[0].get("delta", {})
                except (json.JSONDecodeError, IndexError, KeyError):
                    yield chunk
                    continue

                content = delta.get("content", "")
                reasoning = delta.get("reasoning_content")
                tool_calls_delta = delta.get("tool_calls")
                finish_reason = data.get("choices", [{}])[0].get("finish_reason")

                # Tool call delta — accumulate silently (don't yield to client yet)
                if tool_calls_delta:
                    has_tool_calls = True
                    tc_chunks.append(chunk)
                    for tc in tool_calls_delta:
                        idx = tc.get("index", 0)
                        if idx not in tc_accum:
                            tc_accum[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc.get("id"):
                            tc_accum[idx]["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            tc_accum[idx]["name"] = fn["name"]
                        if fn.get("arguments"):
                            tc_accum[idx]["arguments"] += fn["arguments"]
                    continue

                # Suppress finish chunk when we have accumulated tool_calls
                # (we'll handle search and re-stream on [DONE])
                if has_tool_calls and finish_reason:
                    continue

                # Reasoning content — yield immediately (user sees "thinking")
                if reasoning:
                    yield chunk
                    continue

                # Regular content — yield directly (no buffering!)
                if content:
                    full_response += content
                yield chunk

            elif chunk.strip() == "data: [DONE]":
                # Stream finished — handle accumulated tool_calls
                if has_tool_calls and tc_accum:
                    search_call = next(
                        (tc for tc in tc_accum.values() if tc["name"] == "search_web"),
                        None,
                    )

                    if search_call and search_enabled:
                        # Execute search_web tool call
                        try:
                            args = json.loads(search_call["arguments"])
                            query = (args.get("query") or "").strip()[:200]
                        except (json.JSONDecodeError, KeyError):
                            query = ""

                        if query:
                            log.info(f"AI requested search (stream/tool): {query}")
                            search_ctx = ""
                            try:
                                search_ctx = await search_and_fetch(query)
                            except Exception as e:
                                log.error(f"Search failed: {e}")

                            # Build tool exchange messages
                            all_tcs = [
                                {
                                    "id": td["id"] or f"call_{idx}",
                                    "type": "function",
                                    "function": {"name": td["name"], "arguments": td["arguments"]},
                                }
                                for idx, td in tc_accum.items()
                            ]
                            augmented.append({"role": "assistant", "content": None, "tool_calls": all_tcs})
                            augmented.append({
                                "role": "tool",
                                "tool_call_id": search_call["id"] or "call_search",
                                "content": (
                                    f"[Web search results for '{query}' — use this to answer accurately. "
                                    "Summarize clearly in your own words, do not paste raw text or cite sources.]\n"
                                    + (search_ctx or "No results found.")
                                ),
                            })

                            # Re-stream without search_web tool
                            re_tools = [t for t in all_tools if t.get("function", {}).get("name") != "search_web"]
                            gen2 = providers.chat_completion_stream(
                                augmented, model=model, tools=re_tools or None,
                                tool_choice=tool_choice, provider=active,
                            )
                            async for chunk2 in gen2:
                                if chunk2.startswith("data: ") and chunk2.strip() != "data: [DONE]":
                                    try:
                                        d2 = json.loads(chunk2[6:])
                                        t2 = d2.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                        if t2:
                                            full_response += t2
                                    except (json.JSONDecodeError, IndexError, KeyError):
                                        pass
                                yield chunk2

                            # Save & extract
                            if full_response:
                                add_conversation_message(user_id, "assistant", full_response)
                                all_msgs = messages + [{"role": "assistant", "content": full_response}]
                                asyncio.create_task(_safe_extract(user_id, all_msgs))
                            try:
                                add_usage_stat(
                                    user_id=user_id, provider_id=active.get("id", ""),
                                    provider_name=active.get("name", ""), provider_type=active.get("type", ""),
                                    model=model or active.get("model", ""),
                                    tokens_prompt=0, tokens_completion=_estimate_tokens(full_response),
                                    tokens_total=_estimate_tokens(full_response),
                                    response_time_ms=int((time.time() - _req_start) * 1000),
                                    stream=True, search_used=True,
                                )
                            except Exception:
                                pass
                            return

                    # Not search_web — forward buffered tool_call chunks to client (HA)
                    for tc_chunk in tc_chunks:
                        yield tc_chunk
                    yield chunk  # forward the [DONE]

                else:
                    # No tool_calls — just forward [DONE]
                    yield chunk

            else:
                # Keepalive comments or other non-data lines — pass through
                yield chunk

        if full_response:
            clean_response = _strip_search_markers(full_response) if "<<SEARCH" in full_response else full_response
            add_conversation_message(user_id, "assistant", clean_response)
            all_msgs = messages + [{"role": "assistant", "content": clean_response}]
            asyncio.create_task(_safe_extract(user_id, all_msgs))

        try:
            add_usage_stat(
                user_id=user_id, provider_id=active.get("id", ""),
                provider_name=active.get("name", ""), provider_type=active.get("type", ""),
                model=model or active.get("model", ""),
                tokens_prompt=0, tokens_completion=_estimate_tokens(full_response),
                tokens_total=_estimate_tokens(full_response),
                response_time_ms=int((time.time() - _req_start) * 1000),
                stream=True, search_used=False,
            )
        except Exception:
            pass

    return StreamingResponse(stream_wrapper(), media_type="text/event-stream")


# Per-user extraction locks to prevent concurrent duplicate extractions (#6)
_extraction_locks: dict[str, asyncio.Lock] = {}
_EXTRACTION_TIMEOUT = 30.0  # seconds (#8)


async def _safe_extract(user_id: str, messages: list[dict]):
    """Safely run memory extraction in background with per-user lock and timeout."""
    if user_id not in _extraction_locks:
        _extraction_locks[user_id] = asyncio.Lock()

    # Skip if another extraction is already running for this user
    if _extraction_locks[user_id].locked():
        log.debug(f"Skipping extraction for {user_id} — already in progress")
        return

    async with _extraction_locks[user_id]:
        try:
            await asyncio.wait_for(
                extract_memories_from_conversation(user_id, messages),
                timeout=_EXTRACTION_TIMEOUT,
            )
        except asyncio.TimeoutError:
            log.warning(f"Memory extraction timed out for {user_id} (>{_EXTRACTION_TIMEOUT}s)")
        except Exception as e:
            log.error(f"Background memory extraction failed: {e}")


@router.get("/v1/models")
async def list_models():
    try:
        models = await providers.list_models()
        return {"object": "list", "data": models}
    except Exception as e:
        return JSONResponse(
            status_code=502,
            content={"error": f"Could not reach LMStudio: {e}"},
        )
