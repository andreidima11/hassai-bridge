#!/usr/bin/env python3
"""
HASSAI Bridge — AI Bridge between Home Assistant and LMStudio
Port 8899 | Memory engine | AI-powered web search via SearXNG
"""

import logging
import time
import uvicorn
from collections import defaultdict
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from pathlib import Path

from database import init_db
from core.config import VERSION, load_config
from routers import chat, memory, settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
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
    if path.startswith(("/v1/", "/api/chat")):
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

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8899, reload=True)