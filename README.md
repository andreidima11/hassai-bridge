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
- **API Key**: used as the user identifier to separate memories per user (e.g. use a different key for each HA user)
- **Model**: the model name from your LLM server

## Project Structure

```
hassai-bridge/
├── main.py              # FastAPI app (port 8899)
├── config.py            # Configuration (JSON-backed, compat shim)
├── database.py          # SQLite — memories & conversations (compat shim)
├── requirements.txt
├── core/
│   ├── config.py        # Configuration with caching
│   └── database.py      # SQLite — memories, conversations, usage stats
├── routers/
│   ├── chat.py          # /v1/chat/completions (OpenAI-compatible)
│   ├── memory.py        # /api/memory/* (memory CRUD + knowledge graph)
│   └── settings.py      # /api/settings/* (configuration)
├── services/
│   ├── providers.py     # Multi-provider LLM client
│   ├── memory_engine.py # Tiered memory retrieval & extraction
│   ├── knowledge_graph.py # Per-user knowledge graph
│   ├── searxng.py       # Web search client
│   └── web_scraper.py   # Web page text extraction
├── static/
│   ├── index.html       # Web UI
│   ├── css/style.css
│   └── js/
│       ├── app.js       # Main frontend logic
│       └── i18n.js      # Internationalization (EN/RO)
└── data/                # SQLite DB + config.json (auto-generated)
```

## API Endpoints

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | Chat completions (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/api/settings/` | GET/PUT | Application settings |
| `/api/settings/health` | GET | Health check |
| `/api/settings/info` | GET | System info dashboard |
| `/api/settings/stats` | GET | Usage statistics |
| `/api/settings/providers` | GET/POST | Provider management |
| `/api/settings/backup` | GET | Database backup download |
| `/api/settings/restore/upload` | POST | Database restore (upload) |
| `/api/memory/users` | GET | List users with memories |
| `/api/memory/{user_id}` | GET | User memories |
| `/api/memory/` | POST | Add a memory |
| `/api/memory/{id}` | PUT/DELETE | Update/delete a memory |
| `/api/memory/graph/{user_id}/*` | various | Knowledge graph endpoints |
| `/api/logs` | GET | Server logs |
| `/` | GET | Web UI |

> **Note:** All `/api/` endpoints require authentication (API key via Bearer token, X-Assist-Key header, or localhost access).

## Web Search

For web search functionality, you need a search engine instance. You can run one with Docker:

```bash
docker run -d -p 8080:8080 searxng/searxng
```

Then enable web search from the Web UI > Settings.
