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
from fastapi import FastAPI, Request, Query, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from pathlib import Path

from database import init_db, cleanup_old_conversations, get_all_users
from core.auth import get_ingress_path, require_api_key_or_webui, _INGRESS_RE
from core.config import VERSION, BUILD_ID, load_config, save_config
from services.knowledge_graph import init_graph_tables
from services.memory_engine import consolidate_memories
from services.consolidation_schedule import normalize_auto_consolidation, should_run_now
from services.providers import get_active_provider
from routers import chat, memory, settings, skills, conversations

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
# Behind HA Ingress every browser tab + the HA integration share one client IP.
# Sensor polls and UI GETs must not burn the budget or chat/HA look "dead".
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 180  # mutating / chat requests per minute per IP
_RATE_WINDOW = 60.0  # seconds
_RATE_MAX_IPS = 10000  # max tracked IPs
# Chunked backup restore can be 80+ POSTs for a large ZIP — never throttle those.
_RATE_LIMIT_EXEMPT_PREFIXES = (
    "/api/settings/import/",
    "/api/settings/export",
    "/api/settings/backup",
    "/api/settings/restore",
)


def _rate_limit_exempt(path: str) -> bool:
    return any(path.startswith(prefix) for prefix in _RATE_LIMIT_EXEMPT_PREFIXES)


def _should_rate_limit(method: str, path: str) -> bool:
    """Only throttle write/chat traffic — never GETs (sensors, UI, logs)."""
    m = (method or "GET").upper()
    if m in ("GET", "HEAD", "OPTIONS"):
        return False
    if not path.startswith(("/v1/", "/api/")):
        return False
    if "/chat/activity/" in path:
        return False
    if _rate_limit_exempt(path):
        return False
    return True


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
    last_daily_key = None
    while True:
        try:
            await asyncio.sleep(60)  # check every minute
            cfg = load_config()
            ac = normalize_auto_consolidation(
                (cfg.get("memory") or {}).get("auto_consolidation"),
            )
            due, new_key = should_run_now(ac, last_daily_key=last_daily_key)
            if not due:
                continue

            if new_key is not None:
                last_daily_key = new_key

            log.info(
                "Auto-consolidation triggered (%s hour=%s interval=%sh)",
                ac["schedule"], ac["hour"], ac["interval_hours"],
            )

            # Memory consolidation uses the primary provider (final voice / quality).
            active = get_active_provider()

            users = get_all_users()
            for user_id in users:
                try:
                    await consolidate_memories(user_id, provider=active)
                    log.info(f"Auto-consolidation complete for user: {user_id}")
                except Exception as e:
                    log.error(f"Auto-consolidation failed for {user_id}: {e}")

            # Persist last run for interval schedules (survives restart).
            if ac["schedule"] == "interval":
                fresh = load_config()
                mem = fresh.setdefault("memory", {})
                block = normalize_auto_consolidation(mem.get("auto_consolidation"))
                block["last_run_at"] = time.time()
                mem["auto_consolidation"] = block
                save_config(fresh)

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
app.include_router(conversations.router)

# ── CORS middleware — allow cross-origin API access (API-key auth, no cookies) ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Admin auth dependency — protects /api/ routes ──
# Read-only monitoring endpoints used by the HA integration sensors.
# These never expose raw secrets (API keys are masked in /info).
_PUBLIC_GET_PATHS = {
    "/api/settings/info",
    "/api/settings/health",
    "/api/settings/stats",
    "/api/me",
    "/api/build",
}


def _require_admin_key(request: Request):
    """Validate API key for admin endpoints (/api/settings, /api/memory, /api/logs)."""
    # Allow unauthenticated GET for HA sensor polling (info/stats/health)
    # Strip ingress prefix if present (HA may forward the full path).
    path = request.url.path
    ingress = get_ingress_path(request)
    if ingress and path.startswith(ingress):
        path = path[len(ingress):] or "/"
    if request.method == "GET" and path in _PUBLIC_GET_PATHS:
        return

    require_api_key_or_webui(request)


@app.middleware("http")
async def strip_ingress_prefix(request: Request, call_next):
    """If Supervisor forwards the full /api/hassio_ingress/<token>/... path, strip it."""
    path = request.url.path
    match = _INGRESS_RE.search(path)
    if match:
        prefix = match.group(1)
        if path.startswith(prefix):
            request.scope["path"] = path[len(prefix):] or "/"
            request.scope["root_path"] = (request.scope.get("root_path") or "") + prefix
    return await call_next(request)


@app.middleware("http")
async def rate_limit_and_timing(request: Request, call_next):
    """Rate limiting (chat/mutating endpoints) + request timing logs."""
    start = time.time()
    path = request.url.path

    if _should_rate_limit(request.method, path):
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
                headers={"Retry-After": "15"},
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
    # Ingress / Companion WebView otherwise keep a stale chat UI after add-on updates
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
    response.headers["Pragma"] = "no-cache"

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
_CACHE_BUSTER = BUILD_ID

_NO_STORE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
    "Surrogate-Control": "no-store",
}


@app.get("/static/{asset_path:path}")
async def serve_static(asset_path: str):
    """Serve UI assets with strict no-cache headers (HA Ingress caches aggressively)."""
    file_path = (STATIC_DIR / asset_path).resolve()
    if not str(file_path).startswith(str(STATIC_DIR.resolve())) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(file_path, headers=_NO_STORE_HEADERS)


@app.get("/assets/{asset_path:path}")
async def serve_vite_assets(asset_path: str):
    """Vite chat bundle (relative ./assets/... from the Ingress index)."""
    file_path = (STATIC_DIR / "assets" / asset_path).resolve()
    static_root = (STATIC_DIR / "assets").resolve()
    if not str(file_path).startswith(str(static_root)) or not file_path.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(file_path, headers=_NO_STORE_HEADERS)


def _render_html(filename: str, request: Request) -> HTMLResponse:
    """Serve an HTML page with cache-buster + HA Ingress prefix injected."""
    html = (STATIC_DIR / filename).read_text(encoding="utf-8")
    ingress = get_ingress_path(request)
    prefix = (ingress or "").rstrip("/")
    html = (
        html.replace("__CACHE_BUSTER__", _CACHE_BUSTER)
        .replace("__INGRESS_PATH__", prefix)
        .replace("__ASSET_PREFIX__", prefix)
        .replace("__VERSION__", VERSION)
    )
    return HTMLResponse(
        content=html,
        headers=_NO_STORE_HEADERS,
    )


@app.get("/")
async def root(request: Request):
    """Agentic chat home (HA sidebar entrypoint)."""
    return _render_html("index.html", request)


@app.get("/api/build")
async def build_info():
    """Cache-buster token for Ingress / browser (version + UI file hash)."""
    return JSONResponse(
        {"version": VERSION, "build": BUILD_ID},
        headers=_NO_STORE_HEADERS,
    )


@app.get("/settings")
async def settings_page(request: Request):
    """Legacy / full settings Web UI."""
    return _render_html("settings.html", request)


# ── Graceful shutdown ──
def _handle_sigterm(*_):
    """Handle SIGTERM for clean shutdown (systemd, Docker, etc.)."""
    log.info("Received SIGTERM — shutting down gracefully")
    raise SystemExit(0)

signal.signal(signal.SIGTERM, _handle_sigterm)


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8899, reload=True)