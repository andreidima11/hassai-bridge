# HASSAI Bridge

Home Assistant **add-on**: agentic chat, per-user memory, knowledge graph, and LLM proxy.

## Install

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add: `https://github.com/andreidima11/hassai-bridge`
3. Install **HASSAI Bridge**, start it
4. Open **HASSAI** from the sidebar (Ingress)

The add-on pulls `ghcr.io/andreidima11/{arch}-hassai-bridge:<version>`.

Works with the [HASSAI Bridge integration](https://github.com/andreidima11/hassai-bridge-ha) for Assist / voice.

## Integration URL (Assist / sensors)

Use **Bridge URL** without `/v1`:

| When | Bridge URL |
|------|------------|
| Add-on on same HA OS | `http://hassai_bridge:8899` |
| Port 8899 on the host | `http://<HA-IP>:8899` |

API key: add-on **Settings → Users**, copy that Home Assistant user's key.

## Versioning

Source of truth: [`hassai_bridge/app/VERSION`](hassai_bridge/app/VERSION) (no leading `v`).

```bash
# bump hassai_bridge/app/VERSION, then:
bash scripts/sync_version.sh
# update hassai_bridge/CHANGELOG.md, commit, merge to main, publish a GitHub Release
```

Home Assistant shows an update when `hassai_bridge/config.yaml` → `version` on `main` is newer.

## Project layout

```
hassai-bridge/
├── repository.yaml          # HA add-on store
├── hassai_bridge/           # the add-on (only app)
│   ├── config.yaml
│   ├── Dockerfile
│   ├── run.sh
│   └── app/                 # FastAPI + Web UI (this is what ships)
│       ├── main.py
│       ├── VERSION
│       ├── core/
│       ├── routers/
│       ├── services/
│       └── static/
└── .github/workflows/       # GHCR image on GitHub Release
```

Edit files under `hassai_bridge/app/`. There is no separate root copy of the server.

## API

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | Chat completions (OpenAI-compatible) |
| `/v1/models` | GET | List available models |
| `/api/settings/` | GET/PUT | Application settings |
| `/api/settings/info` | GET | System info |
| `/api/memory/*` | various | Memory + knowledge graph |
| `/` | GET | Chat UI |
| `/settings` | GET | Settings UI |

`/api/` routes need an API key (Bearer / X-Assist-Key) unless the request is trusted Web UI / Ingress.
