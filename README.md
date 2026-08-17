# HASSAI Bridge

**AI Bridge for Home Assistant** — with per-user memory, knowledge graph, and web search.

## Features

- **OpenAI-compatible API** (`/v1/chat/completions`) — integrates directly with Home Assistant via the [HASSAI Bridge integration](https://github.com/andreidima11/hassai-bridge-ha)
- **Local LLM Proxy** — routes requests to a local LLM inference server
- **Per-user Memory** — each Home Assistant user gets their own persistent memory store
- **Knowledge Graph** — automatically builds entity-relationship graphs from conversations
- **Web Search** — searches the internet and extracts page content (like ChatGPT)
- **Web UI** — agentic chat home + settings panel (port 8899, or HA sidebar via add-on Ingress)

## Quick Install (one command)

```bash
git clone https://github.com/andreidima11/hassai-bridge.git ~/hassai-bridge && bash ~/hassai-bridge/install.sh
```

This will:
1. Check Python 3.10+ is available
2. Create a virtual environment and install dependencies
3. Generate a default config
4. Create a `hassai-bridge` launcher script
5. Optionally install as a system service (auto-start on boot)

### Home Assistant Add-on (recommended on HA OS)

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add: `https://github.com/andreidima11/hassai-bridge`
3. Install **HASSAI Bridge**, start it
4. Open **HASSAI** from the sidebar (Ingress) — chat is the home screen; **Settings** is the management UI

Add-on sources live under `hassai_bridge/`.

### Managing the server

```bash
cd ~/hassai-bridge
./hassai-bridge start      # Start (background)
./hassai-bridge stop       # Stop
./hassai-bridge restart    # Restart
./hassai-bridge status     # Check status
./hassai-bridge logs       # View logs
./hassai-bridge update     # Pull latest & restart
```

### Manual Installation

```bash
cd ~/hassai-bridge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python main.py
```

The app will run on **http://0.0.0.0:8899**
- **Chat**: `http://<host>:8899/`
- **Settings**: `http://<host>:8899/settings`

### Uninstall

```bash
cd ~/hassai-bridge
bash uninstall.sh
```

## Versioning & add-on updates

All version strings come from the root [`VERSION`](VERSION) file:

| Place | Value |
|-------|--------|
| `/VERSION` | `0.2.4-beta` (source of truth, no leading `v`) |
| App / Web UI / API | `v0.2.4-beta` |
| Add-on `hassai_bridge/config.yaml` | `0.2.4-beta` |
| Add-on image sources | `hassai_bridge/app/` (vendored by `scripts/sync_version.sh`) |

Home Assistant shows an add-on **Update** when `hassai_bridge/config.yaml` → `version` on `main` is newer than the installed add-on. After bumping, run `bash scripts/sync_version.sh`, merge to `main`, then refresh the add-on store.

```bash
# bump VERSION, then:
bash scripts/sync_version.sh
# update hassai_bridge/CHANGELOG.md, commit, merge to main
```

## Home Assistant Setup

### Add-on + integration

1. Install the **HASSAI Bridge** add-on from this repository (sidebar **HASSAI**).
2. Install the [HASSAI Bridge integration](https://github.com/andreidima11/hassai-bridge-ha).
3. In the integration, set **Bridge URL** to (no `/v1`):

| Setup | Bridge URL |
|-------|------------|
| HA OS add-on (same machine) | `http://hassai_bridge:8899` |
| Bridge on LAN / published port | `http://<IP>:8899` |

### Manual / standalone Bridge

In Home Assistant, add the **HASSAI Bridge** integration with:

- **URL**: `http://<HASSAI_BRIDGE_IP>:8899` (no `/v1`)
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
│   ├── index.html       # Agentic chat home
│   ├── settings.html    # Settings / management UI
│   ├── css/
│   │   ├── style.css
│   │   └── chat.css
│   └── js/
│       ├── app.js       # Settings frontend
│       ├── chat.js      # Chat client (streaming)
│       └── i18n.js      # Internationalization (EN/RO)
├── hassai_bridge/       # Home Assistant add-on (Ingress sidebar)
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
