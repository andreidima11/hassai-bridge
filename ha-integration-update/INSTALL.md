# HASSAI Bridge HA Integration 1.5.0 (update pack)

Includes:
- Sensor fix (no more Unknown/unavailable when bridge is reachable)
- Automation tools: list/get/create/update/delete/toggle with confirm=true

## Install into Home Assistant

```bash
# From your HA config directory (where configuration.yaml lives):
cp -a ha-integration-update/custom_components/hassai_bridge \
  /config/custom_components/hassai_bridge

# Or if using Samba/SSH to HA:
# copy the hassai_bridge folder over the existing custom_components/hassai_bridge
```

Then:
1. Restart Home Assistant
2. Reload the HASSAI Bridge integration (or restart again)
3. If sensors still look empty, open the integration → Configure / re-enter API key from bridge `data/config.json`
4. Existing installs keep old Functions YAML — to enable automation tools, either reset Functions to defaults in options, or re-add the integration

## Automation tools usage

Ask Assist things like:
- "List my automations"
- "Create an automation that turns on light.living_room at sunset" (it will ask for confirmation first)
