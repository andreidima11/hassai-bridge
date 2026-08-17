# HASSAI Bridge Add-on

AI bridge for Home Assistant with agentic chat, per-user memory, knowledge graph, and LLM proxy.

## Features

- **Sidebar panel** via Ingress — open **HASSAI** from the HA sidebar
- **Chat** as the home screen — HA admin copilot (dashboards/cards, logs, repairs, config files)
- **Settings** — providers, memory, users, search (existing Web UI)
- Works with the [HASSAI Bridge HA integration](https://github.com/andreidima11/hassai-bridge-ha) for Assist / voice

## Install

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add: `https://github.com/andreidima11/hassai-bridge`
3. Install **HASSAI Bridge**, start it
4. Open from the sidebar (**HASSAI**) or **Open Web UI**

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

API key: the one from add-on **Settings** (or leave empty if none is set yet).

## Versioning

The add-on `version` in `config.yaml` must match the root `/VERSION` file.
Bump both (or run `bash scripts/sync_version.sh`) and publish a GitHub release
tag `v…` so Home Assistant shows an update in the add-on store.

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
