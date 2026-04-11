# HASSAI Bridge

**AI Bridge for Home Assistant** — with per-user memory, knowledge graph, and web search.

## Features

- **OpenAI-compatible API** (`/v1/chat/completions`) — integrates directly with Home Assistant via the [HASSAI Bridge integration](https://github.com/andreidima11/hassai-bridge-ha)
- **Local LLM Proxy** — routes requests to a local LLM inference server
- **Per-user Memory** — each Home Assistant user gets their own persistent memory store
- **Knowledge Graph** — automatically builds entity-relationship graphs from conversations
- **Web Search** — searches the internet and extracts page content (like ChatGPT)
- **Web UI** — settings and management panel accessible on port 8899

## Installation

```bash
cd ~/hassai-bridge
pip install -r requirements.txt
python main.py
```

The app will run on **http://0.0.0.0:8899**

## Home Assistant Setup

In Home Assistant, add the **HASSAI Bridge** integration with:

- **URL**: `http://<HASSAI_BRIDGE_IP>:8899/v1`
- **API Key**: any value (not verified)
- **Model**: the model name from your LLM server

## Project Structure

```
hassai-bridge/
├── main.py              # FastAPI app (port 8899)
├── config.py            # Configuration (JSON-backed)
├── database.py          # SQLite — memories & conversations
├── requirements.txt
├── routers/
│   ├── chat.py          # /v1/chat/completions (OpenAI-compatible)
│   ├── memory.py        # /api/memory/* (memory CRUD + knowledge graph)
│   ├── settings.py      # /api/settings/* (configuration)
│   └── search.py        # /api/search/* (web search)
├── services/
│   ├── lmstudio.py      # LLM inference client
│   ├── memory_engine.py # Tiered memory retrieval & extraction
│   ├── knowledge_graph.py # Per-user knowledge graph
│   ├── searxng.py       # Web search client
│   └── web_scraper.py   # Web page text extraction
├── static/
│   ├── index.html       # Web UI
│   ├── style.css
│   └── app.js
└── data/                # SQLite DB + config.json (auto-generated)
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | Chat completions (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/api/settings/` | GET/PUT | Application settings |
| `/api/settings/health` | GET | Health check |
| `/api/memory/users` | GET | List users with memories |
| `/api/memory/{user_id}` | GET | User memories |
| `/api/memory/` | POST | Add a memory |
| `/api/memory/{id}` | DELETE | Delete a memory |
| `/api/memory/graph/{user_id}/*` | various | Knowledge graph endpoints |
| `/api/search/` | POST | Web search + content fetch |
| `/api/search/fetch` | POST | Extract text from a URL |
| `/` | GET | Web UI |

## Web Search

For web search functionality, you need a search engine instance. You can run one with Docker:

```bash
docker run -d -p 8080:8080 searxng/searxng
```

Then enable web search from the Web UI > Settings.
