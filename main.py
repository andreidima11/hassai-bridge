#!/usr/bin/env python3
"""
HASSAI Bridge — AI Bridge for Home Assistant
Port 8899 | Per-user memory & knowledge graph | Web search
"""

import asyncio
import logging
import signal
import time
import uuid
import uvicorn
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from urllib.parse import urlparse
from fastapi import FastAPI, Request, Query, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pathlib import Path

from database import init_db, cleanup_old_conversations, get_all_users
from core.config import VERSION, load_config
from services.knowledge_graph import init_graph_tables
from services.memory_engine import consolidate_memories
from services.providers import get_active_provider, get_secondary_provider
from routers import chat, memory, settings, skills

# ── In-memory ring buffer for logs ──
_LOG_BUFFER_SIZE = 2000
_log_buffer: deque[dict] = deque(maxlen=_LOG_BUFFER_SIZE)


class BufferHandler(logging.Handler):
    """Logging handler that stores records in a ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        _log_buffer.append({
            "ts": datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            "level": record.levelname,
            "name": record.name,
            "msg": self.format(record),
        })


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
# Attach ring buffer handler to root logger
_buf_handler = BufferHandler()
_buf_handler.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s: %(message)s"))
logging.getLogger().addHandler(_buf_handler)
log = logging.getLogger("hassai")

# ── Rate limiting (sliding window per IP, capped to prevent leak) ──
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 60  # requests per minute
_RATE_WINDOW = 60.0  # seconds
_RATE_MAX_IPS = 10000  # max tracked IPs


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    init_graph_tables()
    # Auto-cleanup old conversations on startup (#18)
    try:
        deleted = cleanup_old_conversations(days=90)
        if deleted:
            log.info(f"Startup cleanup: removed {deleted} conversation messages older than 90 days")
    except Exception as e:
        log.warning(f"Conversation cleanup failed: {e}")

    # Start auto-consolidation scheduler
    consolidation_task = asyncio.create_task(_auto_consolidation_loop())

    print("╔══════════════════════════════════════════════╗")
    print(f"║       HASSAI Bridge {VERSION} Started        ║")
    print("║  Web UI: http://0.0.0.0:8899                 ║")
    print("║  API:    http://0.0.0.0:8899/v1/             ║")
    print("║  Memory: Tiered retrieval + knowledge graph   ║")
    print("║  Search: AI-driven web search                 ║")
    print("╚══════════════════════════════════════════════╝")
    yield
    consolidation_task.cancel()


async def _auto_consolidation_loop():
    """Background loop that runs memory consolidation on schedule."""
    last_run_date = None
    while True:
        try:
            await asyncio.sleep(60)  # check every minute
            cfg = load_config()
            ac = cfg.get("memory", {}).get("auto_consolidation", {})
            if not ac.get("enabled", False):
                continue

            now = datetime.now()
            schedule = ac.get("schedule", "daily")
            target_hour = ac.get("hour", 3)

            if now.hour != target_hour:
                continue

            # Determine if we should run based on schedule
            run_key = now.strftime("%Y-%m-%d")
            if schedule == "weekly" and now.weekday() != 0:  # Monday
                continue
            if run_key == last_run_date:
                continue

            last_run_date = run_key
            log.info(f"Auto-consolidation triggered ({schedule}, hour={target_hour})")

            # Get secondary provider for memory operations
            active = get_active_provider()
            secondary = get_secondary_provider(active)

            users = get_all_users()
            for user_id in users:
                try:
                    await consolidate_memories(user_id, provider=secondary)
                    log.info(f"Auto-consolidation complete for user: {user_id}")
                except Exception as e:
                    log.error(f"Auto-consolidation failed for {user_id}: {e}")

        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error(f"Auto-consolidation loop error: {e}")
            await asyncio.sleep(300)


app = FastAPI(
    title="HASSAI Bridge",
    description="AI Bridge for Home Assistant with memory, knowledge graph & web search",
    version=VERSION,
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(settings.router)
app.include_router(skills.router)

# ── CORS middleware — allow cross-origin API access (API-key auth, no cookies) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Admin auth dependency — protects /api/ routes ──
def _require_admin_key(request: Request):
    """Validate API key for admin endpoints (/api/settings, /api/memory, /api/logs)."""
    cfg = load_config()
    expected_key = cfg.get("api_key", "")
    if not expected_key:
        return  # No key configured — allow all

    valid_keys = {expected_key}
    user_api_keys = cfg.get("users", {}).get("api_keys", {})
    valid_keys.update(user_api_keys.keys())

    # Try Bearer token
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token in valid_keys:
            return

    # Try X-Assist-Key header
    assist_key = request.headers.get("x-assist-key", "").strip()
    if assist_key and assist_key in valid_keys:
        return

    # Allow same-origin requests (WebUI served by this server) — strict match
    server_host = request.headers.get("host", "")
    if server_host:
        expected_origins = {
            f"http://{server_host}",
            f"https://{server_host}",
        }
        origin = request.headers.get("origin", "")
        if origin and origin in expected_origins:
            return
        referer = request.headers.get("referer", "")
        if referer:
            ref_parsed = urlparse(referer)
            ref_origin = f"{ref_parsed.scheme}://{ref_parsed.netloc}"
            if ref_origin in expected_origins:
                return

    raise HTTPException(status_code=401, detail="API key required")


@app.middleware("http")
async def rate_limit_and_timing(request: Request, call_next):
    """Rate limiting (chat endpoints) + request timing logs."""
    start = time.time()
    path = request.url.path

    # Rate limit chat and API endpoints
    if path.startswith(("/v1/", "/api/")):
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        bucket = _rate_buckets[client_ip]
        # Prune old entries
        cutoff = now - _RATE_WINDOW
        _rate_buckets[client_ip] = bucket = [t for t in bucket if t > cutoff]
        if len(bucket) >= _RATE_LIMIT:
            return JSONResponse(
                status_code=429,
                content={"error": "Rate limit exceeded. Try again later."},
            )
        bucket.append(now)
        # Evict stale IPs to prevent unbounded growth (#6)
        if len(_rate_buckets) > _RATE_MAX_IPS:
            stale = [ip for ip, ts in _rate_buckets.items() if not ts or ts[-1] < cutoff]
            for ip in stale:
                del _rate_buckets[ip]

    response = await call_next(request)

    # Add request ID header for tracing
    request_id = uuid.uuid4().hex[:12]
    response.headers["X-Request-ID"] = request_id

    # Log timing for API requests
    duration = time.time() - start
    if path.startswith(("/v1/", "/api/")):
        log.info(f"{request.method} {path} — {response.status_code} — {duration:.2f}s [{request_id}]")

    return response


# ── Logs API (requires admin auth #14) ──
@app.get("/api/logs", dependencies=[Depends(_require_admin_key)])
async def get_logs(
    request: Request,
    limit: int = Query(200, ge=1, le=2000),
    level: str = Query("ALL"),
    search: str = Query(""),
):
    """Return recent log entries from the ring buffer."""
    logs = list(_log_buffer)
    if level != "ALL":
        logs = [e for e in logs if e["level"] == level.upper()]
    if search:
        q = search.lower()
        logs = [e for e in logs if q in e["msg"].lower()]
    return logs[-limit:]


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("__CACHE_BUSTER__", VERSION)
    return HTMLResponse(content=html)


# ── Graceful shutdown ──
def _handle_sigterm(*_):
    """Handle SIGTERM for clean shutdown (systemd, Docker, etc.)."""
    log.info("Received SIGTERM — shutting down gracefully")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, _handle_sigterm)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8899, reload=True)