# HASSAI Bridge - Home Assistant Integration

Custom Home Assistant integration that connects to a [HASSAI Bridge](https://github.com/andreidima11/hassai-bridge) server for AI-powered conversations with device control.

## Features

- **Conversation Agent** — Registers as a native HA conversation agent (works with Assist pipeline)
- **Device Control** — Controls exposed HA entities via `execute_services` tool calling
- **Automations** — List/inspect/create/update/delete/toggle automations (mutating actions require `confirm=true`)
- **Memory & Search** — The HASSAI Bridge server handles long-term memory, web search, and context augmentation
- **Jinja2 Prompts** — System prompt supports Jinja2 templates with exposed entity data
- **Configurable** — Model, temperature, max tokens, and function specs are all configurable via the UI
- **Sensors** — Polls bridge `/api/settings/info` + stats for live status in HA

## Prerequisites

- Home Assistant 2024.8.0+
- A running [HASSAI Bridge](https://github.com/andreidima11/hassai-bridge) server
- An LLM backend connected to the bridge (e.g. LMStudio)

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant
2. Click the three dots menu → **Custom repositories**
3. Add `https://github.com/andreidima11/hassai-bridge-ha` as an **Integration**
4. Search for "HASSAI Bridge" and install
5. Restart Home Assistant

### Manual

1. Copy the `custom_components/hassai_bridge` folder to your HA `custom_components/` directory
2. Restart Home Assistant

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for "HASSAI Bridge"
3. Enter:
   - **Bridge URL**: The URL of your HASSAI Bridge server (e.g. `http://192.168.0.100:8899`)
   - **API Key**: Optional, only if your bridge has API key authentication enabled

### Options

After setup, click **Configure** on the integration to adjust:

| Option | Default | Description |
|--------|---------|-------------|
| System Prompt | *(entities template)* | Jinja2 template — `exposed_entities` variable is available |
| Model | `default` | Model name, or `default` to use bridge-configured model |
| Max Tokens | 2048 | Maximum response tokens |
| Temperature | 0.7 | LLM temperature (0–2) |
| Max Function Calls | 5 | Maximum tool call iterations per conversation turn |
| Functions (YAML) | `execute_services` | YAML list of function specs with tool definitions |

## Architecture

```
┌─────────────┐     ┌───────────────┐     ┌──────────┐
│   Home       │     │  HASSAI       │     │          │
│   Assistant  │────▶│  Bridge       │────▶│ LMStudio │
│              │◀────│  (FastAPI)    │◀────│          │
└─────────────┘     └───────────────┘     └──────────┘
      │                    │
      │ execute_services   │ memory, search,
      │ (tool calls)       │ system prompt
      ▼                    ▼
  HA Services         SearXNG / SQLite
```

1. User speaks to Assist → HA sends message to this integration
2. Integration builds messages with exposed entities + user text
3. Sends to HASSAI Bridge `/v1/chat/completions` (with tools)
4. Bridge augments with system prompt, memory context, and search capability
5. Bridge forwards to LLM (LMStudio)
6. If LLM returns `tool_calls` → integration executes them in HA → sends results back
7. Final response is returned to the user

## License

MIT
