#!/usr/bin/env python3
"""
HASSAI Bridge — AI Bridge between Home Assistant and LMStudio
Port 8899 | Memory engine | AI-powered web search via SearXNG
"""

import logging
import time
import uvicorn
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI, Request, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from database import init_db
from core.config import VERSION, load_config
from routers import chat, memory, settings

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

# ── Rate limiting (sliding window per IP) ──
_rate_buckets: dict[str, list[float]] = defaultdict(list)
_RATE_LIMIT = 60  # requests per minute
_RATE_WINDOW = 60.0  # seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("╔══════════════════════════════════════════════╗")
    print(f"║       HASSAI Bridge {VERSION} Started        ║")
    print("║  Web UI: http://0.0.0.0:8899                 ║")
    print("║  API:    http://0.0.0.0:8899/v1/             ║")
    print("║  Memory: LLM-powered auto-extraction         ║")
    print("║  Search: AI-driven SearXNG integration       ║")
    print("╚══════════════════════════════════════════════╝")
    yield


app = FastAPI(
    title="HASSAI Bridge",
    description="AI Bridge: Home Assistant ↔ LMStudio with smart memory & web search",
    version=VERSION,
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(settings.router)


@app.middleware("http")
async def rate_limit_and_timing(request: Request, call_next):
    """Rate limiting (chat endpoints) + request timing logs."""
    start = time.time()
    path = request.url.path

    # Rate limit only chat/API endpoints
    if path.startswith("/v1/"):
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

    response = await call_next(request)

    # Log timing for API requests
    duration = time.time() - start
    if path.startswith(("/v1/", "/api/")):
        log.info(f"{request.method} {path} — {response.status_code} — {duration:.2f}s")

    return response


# ── Logs API ──
@app.get("/api/logs")
async def get_logs(
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
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8899, reload=True)