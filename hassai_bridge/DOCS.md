# HASSAI Bridge Add-on

AI bridge for Home Assistant with agentic chat, per-user memory, knowledge graph, and LLM proxy.

## Features

- **Sidebar panel** via Ingress — open **HASSAI** from the HA sidebar
- **Chat** as the home screen — HA admin copilot that keeps using tools until the job is done (dashboards/cards, logs, repairs, config files)
- **Settings** — providers, memory, users, search (existing Web UI)
- Works with the [HASSAI Bridge HA integration](https://github.com/andreidima11/hassai-bridge-ha) for Assist / voice

## Install

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add: `https://github.com/andreidima11/hassai-bridge`
3. Install **HASSAI Bridge**, start it
4. Open from the sidebar (**HASSAI**) or **Open Web UI**

The sidebar panel is a **prebuilt Docker image** (`ghcr.io/andreidima11/hassai-bridge:<version>`), the same code as `python main.py`. After **Update**, the chat home must show **v0.2.12-beta** (or newer) under the logo. If the store says you are current but the logo has no version / old UI: uninstall the add-on (keep data) and install again.

## Integration URL (Assist / sensors)

The custom integration talks to the **API**, not to Ingress.

Use one of these as **Bridge URL** (without `/v1`):

| When | Bridge URL |
|------|------------|
| Add-on on same HA OS (recommended) | `http://hassai_bridge:8899` |
| Port 8899 published on the host | `http://<IP-ul-HA>:8899` |

Examples that **do not** work for the integration:

- Ingress / sidebar URL
- `http://homeassistant.local:8123/...`
- Anything ending in `/v1` (the integration appends `/v1` itself)

API key: in add-on **Settings → Users**, copy the key for the Home Assistant user who should own Assist chats (or leave empty if none is set yet). Sidebar chat always follows the logged-in HA user.

## Users and conversations

- Sidebar chat is scoped to the Home Assistant login (Ingress `X-Remote-User-Id` / `X-Remote-User-Name`).
- Opening the panel upserts that user in Settings and generates an Assist API key.
- **Sync HA users** imports `person.*` entities.
- Use each user's API key in the integration so voice/Assist matches the same identity.

## Versioning

The add-on `version` in `config.yaml` must match the root `/VERSION` file.
Bump both (or run `bash scripts/sync_version.sh`) so Home Assistant shows an update in the add-on store.

The add-on image is built from `hassai_bridge/app/` (vendored copy of the app).
`sync_version.sh` refreshes that copy. Do not git-clone `main` in the Dockerfile:
Supervisor may cache that layer and ship an old UI version.

## Configuration

| Option | Description |
|--------|-------------|
| `log_level` | Logging verbosity |

Data is stored on the add-on data disk. Configure LLM providers in **Settings** inside the panel.

## Network

- **8899/tcp** is published on the host by default (for the integration and direct access).
- Sidebar UI still uses **Ingress** (no need to open a browser to `:8899`).

## Standalone

This same project still runs outside HA OS:

```bash
git clone https://github.com/andreidima11/hassai-bridge.git
bash hassai-bridge/install.sh
```
