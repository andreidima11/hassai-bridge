# HASSAI Bridge

**AI Bridge între Home Assistant și LMStudio** — cu memorie per-utilizator și căutare web via SearXNG.

## Funcționalități

- **API compatibil OpenAI** (`/v1/chat/completions`) — se integrează direct cu Home Assistant (integrare Ollama/OpenAI)
- **Proxy LMStudio** — trimite requesturile către LMStudio local
- **Memorie separată per utilizator** — fiecare utilizator HA are memorii proprii
- **Căutare web SearXNG** — caută pe internet și preia conținut din pagini (ca ChatGPT)
- **Web UI** — panou de setări accesibil prin browser pe portul 8899

## Instalare

```bash
cd ~/hassai-bridge
pip install -r requirements.txt
python main.py
```

Aplicația va rula pe **http://0.0.0.0:8899**

## Configurare Home Assistant

În Home Assistant, adaugă integrarea **OpenAI** (sau **Ollama**) cu:

- **URL**: `http://<IP_HASSAI_BRIDGE>:8899/v1`
- **API Key**: orice valoare (nu se verifică)
- **Model**: modelul din LMStudio

### Exemplu `configuration.yaml`:

```yaml
conversation:
  intents: {}

# Folosind integrarea OpenAI-compatible
# Adaugă din UI: Settings > Integrations > OpenAI Conversation
# Base URL: http://<IP>:8899/v1
```

## Structură

```
hassai-bridge/
├── main.py              # FastAPI app (port 8899)
├── config.py            # Configurare (salvare JSON)
├── database.py          # SQLite - memorii & conversații
├── requirements.txt
├── routers/
│   ├── chat.py          # /v1/chat/completions (compatibil OpenAI)
│   ├── memory.py        # /api/memory/* (CRUD memorii)
│   ├── settings.py      # /api/settings/* (configurare)
│   └── search.py        # /api/search/* (SearXNG)
├── services/
│   ├── lmstudio.py      # Client LMStudio
│   ├── searxng.py       # Client SearXNG
│   └── web_scraper.py   # Extragere text din pagini web
├── static/
│   ├── index.html       # Web UI
│   ├── style.css
│   └── app.js
└── data/                # SQLite DB + config.json (auto-generat)
```

## API Endpoints

| Endpoint | Metodă | Descriere |
|---|---|---|
| `/v1/chat/completions` | POST | Chat completions (compatibil OpenAI) |
| `/v1/models` | GET | Lista modele disponibile |
| `/api/settings/` | GET/PUT | Setări aplicație |
| `/api/settings/health` | GET | Verificare conectivitate |
| `/api/memory/users` | GET | Lista utilizatori cu memorii |
| `/api/memory/{user_id}` | GET | Memorii utilizator |
| `/api/memory/` | POST | Adaugă memorie |
| `/api/memory/{id}` | DELETE | Șterge memorie |
| `/api/search/` | POST | Căutare SearXNG + fetch conținut |
| `/api/search/fetch` | POST | Preia text dintr-un URL |
| `/` | GET | Web UI |

## SearXNG

Pentru căutare web, ai nevoie de o instanță SearXNG. Poți rula una cu Docker:

```bash
docker run -d -p 8080:8080 searxng/searxng
```

Apoi activează SearXNG din Web UI > Setări > SearXNG > Activat.
