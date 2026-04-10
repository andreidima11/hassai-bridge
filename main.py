#!/usr/bin/env python3
"""
HASSAI Bridge — AI Bridge between Home Assistant and LMStudio
Port 8899 | Memory engine | AI-powered web search via SearXNG
"""

import logging
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pathlib import Path

from database import init_db
from routers import chat, memory, settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    print("╔══════════════════════════════════════════════╗")
    print("║       HASSAI Bridge v2.0.0 Started           ║")
    print("║  Web UI: http://0.0.0.0:8899                 ║")
    print("║  API:    http://0.0.0.0:8899/v1/             ║")
    print("║  Memory: LLM-powered auto-extraction         ║")
    print("║  Search: AI-driven SearXNG integration       ║")
    print("╚══════════════════════════════════════════════╝")
    yield


app = FastAPI(
    title="HASSAI Bridge",
    description="AI Bridge: Home Assistant ↔ LMStudio with smart memory & web search",
    version="2.0.0",
    lifespan=lifespan,
)

app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(settings.router)

STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(STATIC_DIR / "index.html"))


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8899, reload=True)