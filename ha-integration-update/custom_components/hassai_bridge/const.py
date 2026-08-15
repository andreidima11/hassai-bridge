"""Constants for the HASSAI Bridge integration."""

DOMAIN = "hassai_bridge"
DEFAULT_NAME = "HASSAI Bridge"

CONF_BASE_URL = "base_url"
CONF_API_KEY = "api_key"

CONF_PROMPT = "prompt"
CONF_CHAT_MODEL = "chat_model"
CONF_MAX_TOKENS = "max_tokens"
CONF_TEMPERATURE = "temperature"
CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION = "max_function_calls_per_conversation"
CONF_FUNCTIONS = "functions"

DEFAULT_CHAT_MODEL = "default"
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TEMPERATURE = 0.7
DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION = 5
DEFAULT_CONTEXT_THRESHOLD = 12000

DEFAULT_PROMPT = """Current Time: {{now()}}

Available Devices:
```csv
entity_id,name,state,area,aliases
{% for entity in exposed_entities -%}
{{ entity.entity_id }},{{ entity.name }},{{ entity.state }},{{ entity.area }},{{entity.aliases | join('/')}}
{% endfor -%}
```

The current state of devices is provided in available devices.
Use execute_services only for requested device actions, not for reading current states.
Do not execute services without the user's confirmation.
Do not restate or appreciate what the user says; make a quick inquiry when needed.

Automation rules:
- You can list, inspect, create, update, delete, and enable/disable Home Assistant automations.
- For create/update/delete you MUST first explain the plan, ask for explicit confirmation, then call the tool again with confirm=true.
- Prefer modern keys: triggers, conditions, actions.
- Keep automations simple and safe; never target unexposed entities in actions.
"""

DEFAULT_CONF_FUNCTIONS = [
    {
        "spec": {
            "name": "execute_services",
            "description": "Use this function to execute service of devices in Home Assistant.",
            "parameters": {
                "type": "object",
                "properties": {
                    "list": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "domain": {
                                    "type": "string",
                                    "description": "The domain of the service",
                                },
                                "service": {
                                    "type": "string",
                                    "description": "The service to be called",
                                },
                                "service_data": {
                                    "type": "object",
                                    "description": "The service data object to indicate what to control.",
                                    "properties": {
                                        "entity_id": {
                                            "type": "string",
                                            "description": "The entity_id retrieved from available devices. It must start with domain, followed by dot character.",
                                        }
                                    },
                                    "required": ["entity_id"],
                                },
                            },
                            "required": ["domain", "service", "service_data"],
                        },
                    }
                },
            },
        },
        "function": {"type": "native", "name": "execute_service"},
    },
    {
        "spec": {
            "name": "list_automations",
            "description": "List Home Assistant automations with id, alias, entity_id, and enabled state.",
            "parameters": {"type": "object", "properties": {}},
        },
        "function": {"type": "native", "name": "list_automations"},
    },
    {
        "spec": {
            "name": "get_automation",
            "description": "Get one automation's live state and YAML config (if editable).",
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {
                        "type": "string",
                        "description": "Automation config id (unique id).",
                    },
                    "entity_id": {
                        "type": "string",
                        "description": "Automation entity_id, e.g. automation.lights_evening.",
                    },
                },
            },
        },
        "function": {"type": "native", "name": "get_automation"},
    },
    {
        "spec": {
            "name": "create_automation",
            "description": (
                "Create a YAML automation in automations.yaml. "
                "First call with confirm=false to preview; after user approval call again with confirm=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "alias": {"type": "string", "description": "Friendly name"},
                    "description": {"type": "string"},
                    "triggers": {
                        "description": "Trigger config (object or list). Prefer modern 'triggers' schema.",
                    },
                    "conditions": {
                        "description": "Optional conditions (object or list).",
                    },
                    "actions": {
                        "description": "Action config (object or list).",
                    },
                    "mode": {
                        "type": "string",
                        "description": "single | restart | queued | parallel",
                    },
                    "automation_id": {
                        "type": "string",
                        "description": "Optional custom id; generated if omitted.",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually create after user confirmation.",
                    },
                },
                "required": ["alias", "triggers", "actions"],
            },
        },
        "function": {"type": "native", "name": "create_automation"},
    },
    {
        "spec": {
            "name": "update_automation",
            "description": (
                "Update an existing YAML automation. "
                "First call with confirm=false to preview; after user approval call again with confirm=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {
                        "type": "string",
                        "description": "Automation config id to update",
                    },
                    "updates": {
                        "type": "object",
                        "description": "Fields to merge (alias, triggers, conditions, actions, mode, description, ...)",
                    },
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually update after user confirmation.",
                    },
                },
                "required": ["automation_id", "updates"],
            },
        },
        "function": {"type": "native", "name": "update_automation"},
    },
    {
        "spec": {
            "name": "delete_automation",
            "description": (
                "Delete a YAML automation. "
                "First call with confirm=false to preview; after user approval call again with confirm=true."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "automation_id": {"type": "string"},
                    "confirm": {
                        "type": "boolean",
                        "description": "Must be true to actually delete after user confirmation.",
                    },
                },
                "required": ["automation_id"],
            },
        },
        "function": {"type": "native", "name": "delete_automation"},
    },
    {
        "spec": {
            "name": "toggle_automation",
            "description": "Enable or disable an automation without editing YAML.",
            "parameters": {
                "type": "object",
                "properties": {
                    "entity_id": {"type": "string"},
                    "automation_id": {"type": "string"},
                    "enabled": {
                        "type": "boolean",
                        "description": "true=enable, false=disable; omit to flip current state",
                    },
                },
            },
        },
        "function": {"type": "native", "name": "toggle_automation"},
    },
]
