# HASSAI Bridge Add-on

AI bridge for Home Assistant with agentic chat, per-user memory, knowledge graph, and LLM proxy.

## Features

- **Sidebar panel** via Ingress — open **HASSAI** from the HA sidebar
- **Chat** as the home screen (agentic work)
- **Settings** — providers, memory, users, search (existing Web UI)
- Works with the [HASSAI Bridge HA integration](https://github.com/andreidima11/hassai-bridge-ha) for Assist

## Install

1. **Settings → Add-ons → Add-on store → ⋮ → Repositories**
2. Add: `https://github.com/andreidima11/hassai-bridge`
3. Install **HASSAI Bridge**, start it
4. Open from the sidebar (**HASSAI**) or **Open Web UI**

## Configuration

| Option | Description |
|--------|-------------|
| `log_level` | Logging verbosity |

Data is stored on the add-on data disk. Configure LLM providers in **Settings** inside the panel.

## Direct port (optional)

Ingress is preferred. If you map port `8899`, you can also open `http://homeassistant.local:8899`.

## Standalone

This same project still runs outside HA OS:

```bash
git clone https://github.com/andreidima11/hassai-bridge.git
bash hassai-bridge/install.sh
```
