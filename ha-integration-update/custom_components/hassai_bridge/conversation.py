"""Conversation agent for HASSAI Bridge integration."""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Literal

import yaml

from homeassistant.components import conversation
from homeassistant.components.conversation import ConversationEntity, ConversationInput, ConversationResult
from homeassistant.components.homeassistant.exposed_entities import async_should_expose
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import MATCH_ALL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, TemplateError
from homeassistant.helpers import area_registry as ar, entity_registry as er, intent, template
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from .const import (
    CONF_API_KEY,
    CONF_BASE_URL,
    CONF_CHAT_MODEL,
    CONF_FUNCTIONS,
    CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION,
    CONF_MAX_TOKENS,
    CONF_PROMPT,
    CONF_TEMPERATURE,
    DEFAULT_CHAT_MODEL,
    DEFAULT_CONF_FUNCTIONS,
    DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION,
    DEFAULT_MAX_TOKENS,
    DEFAULT_PROMPT,
    DEFAULT_TEMPERATURE,
    DOMAIN,
)
from . import automations as automation_tools

_LOGGER = logging.getLogger(__name__)

# Maximum number of back-and-forth messages to keep per conversation
MAX_HISTORY_MESSAGES = 20
# Expire conversations after 1 hour of inactivity
CONVERSATION_EXPIRY_SECONDS = 3600
# Max number of tracked conversations before cleanup
MAX_CONVERSATIONS = 100


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the conversation platform."""
    async_add_entities([HASSAIBridgeAgent(hass, config_entry)])


class HASSAIBridgeAgent(ConversationEntity):
    """HASSAI Bridge conversation agent."""

    _attr_has_entity_name = True
    _attr_name = "Conversation"
    _attr_supported_features = conversation.ConversationEntityFeature.CONTROL
    _attr_should_poll = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the agent."""
        self.hass = hass
        self.entry = entry
        self._history: dict[str, list[dict[str, Any]]] = {}
        self._history_timestamps: dict[str, float] = {}

        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HASSAI",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def supported_languages(self) -> list[str] | Literal["*"]:
        """Return a list of supported languages."""
        return MATCH_ALL

    @property
    def _base_url(self) -> str:
        return self.entry.data[CONF_BASE_URL].rstrip("/")

    @property
    def _api_key(self) -> str:
        return self.entry.data.get(CONF_API_KEY, "")

    @property
    def _model(self) -> str:
        return self.entry.options.get(CONF_CHAT_MODEL, DEFAULT_CHAT_MODEL)

    @property
    def _max_tokens(self) -> int:
        return self.entry.options.get(CONF_MAX_TOKENS, DEFAULT_MAX_TOKENS)

    @property
    def _temperature(self) -> float:
        return self.entry.options.get(CONF_TEMPERATURE, DEFAULT_TEMPERATURE)

    @property
    def _max_function_calls(self) -> int:
        return self.entry.options.get(
            CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION,
            DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION,
        )

    @property
    def _prompt_template(self) -> str:
        return self.entry.options.get(CONF_PROMPT, DEFAULT_PROMPT)

    async def async_update(self) -> None:
        """Poll the bridge to update availability."""
        try:
            client = get_async_client(self.hass)
            headers: dict[str, str] = {}
            if self._api_key:
                headers["Authorization"] = f"Bearer {self._api_key}"
            response = await client.get(
                f"{self._base_url}/v1/models",
                headers=headers,
                timeout=10.0,
            )
            self._attr_available = response.status_code < 400
        except Exception:
            self._attr_available = False

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when entity is removed."""
        self._history.clear()
        self._history_timestamps.clear()

    @property
    def _functions(self) -> list[dict]:
        raw = self.entry.options.get(CONF_FUNCTIONS)
        if raw:
            try:
                parsed = yaml.safe_load(raw)
                if isinstance(parsed, list):
                    return parsed
            except yaml.YAMLError:
                _LOGGER.warning("Invalid YAML in functions config, using defaults")
        return DEFAULT_CONF_FUNCTIONS

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Process a sentence."""
        conversation_id = user_input.conversation_id or conversation.async_create_conversation_id()

        # Get exposed entities
        exposed_entities = self._get_exposed_entities()

        # Render system prompt
        try:
            system_prompt = self._render_prompt(exposed_entities)
        except TemplateError as err:
            _LOGGER.error("Error rendering prompt: %s", err)
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN,
                f"Error rendering prompt: {err}",
            )
            return ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        # Get or create conversation history
        if conversation_id not in self._history:
            self._history[conversation_id] = []
        self._history_timestamps[conversation_id] = time.monotonic()

        # Cleanup stale conversations
        self._cleanup_stale_conversations()

        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(self._history[conversation_id])
        messages.append({"role": "user", "content": user_input.text})

        # Build tools from function specs
        functions = self._functions
        tools = (
            [{"type": "function", "function": f["spec"]} for f in functions]
            if functions
            else None
        )

        # LLM call loop with tool execution
        try:
            response_content = await self._run_tool_loop(
                messages, tools, functions, exposed_entities
            )
        except HomeAssistantError as err:
            intent_response = intent.IntentResponse(language=user_input.language)
            intent_response.async_set_error(
                intent.IntentResponseErrorCode.UNKNOWN, str(err)
            )
            return ConversationResult(
                response=intent_response, conversation_id=conversation_id
            )

        # Update conversation history
        self._history[conversation_id].append(
            {"role": "user", "content": user_input.text}
        )
        self._history[conversation_id].append(
            {"role": "assistant", "content": response_content}
        )

        # Trim history to prevent unbounded growth
        if len(self._history[conversation_id]) > MAX_HISTORY_MESSAGES * 2:
            self._history[conversation_id] = self._history[conversation_id][
                -(MAX_HISTORY_MESSAGES * 2) :
            ]

        # Build response
        intent_response = intent.IntentResponse(language=user_input.language)
        intent_response.async_set_speech(response_content)
        return ConversationResult(
            response=intent_response, conversation_id=conversation_id
        )

    def _cleanup_stale_conversations(self) -> None:
        """Remove expired conversations to prevent memory leaks."""
        now = time.monotonic()
        expired = [
            cid for cid, ts in self._history_timestamps.items()
            if now - ts > CONVERSATION_EXPIRY_SECONDS
        ]
        for cid in expired:
            self._history.pop(cid, None)
            self._history_timestamps.pop(cid, None)

        # If still too many, remove oldest
        if len(self._history) > MAX_CONVERSATIONS:
            sorted_convs = sorted(
                self._history_timestamps.items(), key=lambda x: x[1]
            )
            for cid, _ in sorted_convs[: len(self._history) - MAX_CONVERSATIONS]:
                self._history.pop(cid, None)
                self._history_timestamps.pop(cid, None)

    async def _run_tool_loop(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None,
        functions: list[dict],
        exposed_entities: list[dict],
    ) -> str:
        """Run the LLM call loop, handling tool calls."""
        content = ""

        for iteration in range(self._max_function_calls + 1):
            tool_choice = "auto" if iteration < self._max_function_calls else "none"

            result = await self._call_api(messages, tools, tool_choice)

            choice = result.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "") or ""
            tool_calls = message.get("tool_calls")

            if not tool_calls:
                break

            # Append assistant message with tool_calls to conversation
            messages.append(message)

            # Execute each tool call
            for tc in tool_calls:
                tc_result = await self._execute_tool_call(
                    tc, functions, exposed_entities
                )
                messages.append(
                    {
                        "tool_call_id": tc["id"],
                        "role": "tool",
                        "name": tc["function"]["name"],
                        "content": (
                            json.dumps(tc_result)
                            if isinstance(tc_result, (dict, list))
                            else str(tc_result)
                        ),
                    }
                )

        if not content:
            content = "I processed the request but have no additional response."

        return content

    async def _call_api(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict] | None,
        tool_choice: str = "auto",
    ) -> dict[str, Any]:
        """Call the HASSAI Bridge /v1/chat/completions endpoint via SSE stream."""
        client = get_async_client(self.hass)

        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        payload: dict[str, Any] = {
            "messages": messages,
            "max_tokens": self._max_tokens,
            "temperature": self._temperature,
            "stream": True,
        }

        if self._model and self._model != "default":
            payload["model"] = self._model

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice

        try:
            content = ""
            tool_calls_acc: dict[int, dict[str, Any]] = {}

            async with client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=headers,
                timeout=120.0,
            ) as response:
                if response.status_code == 401:
                    raise HomeAssistantError(
                        "Invalid API key for HASSAI Bridge"
                    )
                if response.status_code >= 400:
                    error_text = ""
                    async for chunk in response.aiter_text():
                        error_text += chunk
                        if len(error_text) > 500:
                            break
                    _LOGGER.error(
                        "HASSAI Bridge returned %s: %s",
                        response.status_code,
                        error_text[:500],
                    )
                    raise HomeAssistantError(
                        f"HASSAI Bridge error (HTTP {response.status_code})"
                    )

                async for line in response.aiter_lines():
                    line = line.strip()
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})

                    if delta.get("content"):
                        content += delta["content"]

                    if tc_deltas := delta.get("tool_calls"):
                        for tc_delta in tc_deltas:
                            idx = tc_delta.get("index", 0)
                            if idx not in tool_calls_acc:
                                tool_calls_acc[idx] = {
                                    "id": tc_delta.get("id", ""),
                                    "type": "function",
                                    "function": {
                                        "name": tc_delta.get("function", {}).get("name", ""),
                                        "arguments": "",
                                    },
                                }
                            tc = tool_calls_acc[idx]
                            if tc_delta.get("id"):
                                tc["id"] = tc_delta["id"]
                            if func := tc_delta.get("function"):
                                if func.get("name"):
                                    tc["function"]["name"] = func["name"]
                                tc["function"]["arguments"] += func.get("arguments", "")

            # Build OpenAI-compatible response
            message: dict[str, Any] = {
                "role": "assistant",
                "content": content or None,
            }
            if tool_calls_acc:
                message["tool_calls"] = [
                    tool_calls_acc[idx] for idx in sorted(tool_calls_acc)
                ]

            return {
                "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
            }

        except HomeAssistantError:
            raise
        except Exception as err:
            _LOGGER.error("Error calling HASSAI Bridge: %s", err)
            raise HomeAssistantError(
                f"Error communicating with HASSAI Bridge: {err}"
            ) from err

    async def _execute_tool_call(
        self,
        tool_call: dict[str, Any],
        functions: list[dict],
        exposed_entities: list[dict],
    ) -> Any:
        """Execute a tool call from the LLM."""
        func_name = tool_call["function"]["name"]

        try:
            arguments = json.loads(tool_call["function"]["arguments"])
        except (json.JSONDecodeError, KeyError) as err:
            _LOGGER.error("Invalid tool call arguments: %s", err)
            return {"error": f"Invalid arguments: {err}"}

        # Find matching function definition
        func_def = next(
            (f for f in functions if f["spec"]["name"] == func_name), None
        )
        if func_def is None:
            return {"error": f"Unknown function: {func_name}"}

        func_type = func_def.get("function", {}).get("type")
        native_name = func_def.get("function", {}).get("name")

        if func_type == "native" and native_name == "execute_service":
            return await self._execute_services(arguments, exposed_entities)

        if func_type == "native" and native_name == "list_automations":
            return automation_tools.list_automations(self.hass)

        if func_type == "native" and native_name == "get_automation":
            return await automation_tools.get_automation(
                self.hass,
                automation_id=arguments.get("automation_id"),
                entity_id=arguments.get("entity_id"),
            )

        if func_type == "native" and native_name == "create_automation":
            return await automation_tools.create_automation(
                self.hass,
                alias=arguments.get("alias", ""),
                triggers=arguments.get("triggers") or arguments.get("trigger"),
                actions=arguments.get("actions") or arguments.get("action"),
                conditions=arguments.get("conditions", arguments.get("condition")),
                description=arguments.get("description"),
                mode=arguments.get("mode"),
                automation_id=arguments.get("automation_id"),
                confirm=bool(arguments.get("confirm", False)),
            )

        if func_type == "native" and native_name == "update_automation":
            return await automation_tools.update_automation(
                self.hass,
                automation_id=arguments.get("automation_id", ""),
                updates=arguments.get("updates") or {},
                confirm=bool(arguments.get("confirm", False)),
            )

        if func_type == "native" and native_name == "delete_automation":
            return await automation_tools.delete_automation(
                self.hass,
                automation_id=arguments.get("automation_id", ""),
                confirm=bool(arguments.get("confirm", False)),
            )

        if func_type == "native" and native_name == "toggle_automation":
            return await automation_tools.toggle_automation(
                self.hass,
                entity_id=arguments.get("entity_id"),
                automation_id=arguments.get("automation_id"),
                enabled=arguments.get("enabled"),
            )

        return {"error": f"Unsupported function: {func_name}"}

    async def _execute_services(
        self,
        arguments: dict[str, Any],
        exposed_entities: list[dict],
    ) -> list[dict[str, Any]]:
        """Execute HA service calls."""
        exposed_ids = {e["entity_id"] for e in exposed_entities}
        results = []

        service_list = arguments.get("list", [])
        if not isinstance(service_list, list):
            return [{"error": "Expected 'list' to be an array"}]

        for service_call in service_list:
            domain = service_call.get("domain", "")
            service = service_call.get("service", "")
            service_data = service_call.get(
                "service_data", service_call.get("data", {})
            )

            if not domain or not service:
                results.append({"error": "Missing domain or service"})
                continue

            # Validate entity_ids are exposed
            entity_id = service_data.get("entity_id")
            if entity_id:
                # Handle both string and list formats
                if isinstance(entity_id, str):
                    entity_ids = [eid.strip() for eid in entity_id.split(",")]
                elif isinstance(entity_id, list):
                    entity_ids = entity_id
                else:
                    entity_ids = [str(entity_id)]

                unauthorized = [
                    eid for eid in entity_ids if eid not in exposed_ids
                ]
                if unauthorized:
                    results.append(
                        {
                            "error": f"Entity not exposed: {', '.join(unauthorized)}"
                        }
                    )
                    continue

            if not self.hass.services.has_service(domain, service):
                results.append(
                    {"error": f"Service {domain}.{service} not found"}
                )
                continue

            try:
                await self.hass.services.async_call(
                    domain=domain,
                    service=service,
                    service_data=service_data,
                    blocking=True,
                )
                results.append({"success": True})
            except Exception as err:
                _LOGGER.error("Error executing %s.%s: %s", domain, service, err)
                results.append({"error": str(err)})

        return results

    def _get_exposed_entities(self) -> list[dict[str, Any]]:
        """Get the list of exposed entities with their state and area."""
        entity_reg = er.async_get(self.hass)
        area_reg = ar.async_get(self.hass)
        entities = []

        for state in self.hass.states.async_all():
            if not async_should_expose(self.hass, conversation.DOMAIN, state.entity_id):
                continue

            entry = entity_reg.async_get(state.entity_id)
            aliases: list[str] = []
            area_name = ""
            if entry:
                if entry.aliases:
                    aliases = list(entry.aliases)
                # Resolve area: entity area > device area
                area_id = entry.area_id
                if not area_id and entry.device_id:
                    from homeassistant.helpers import device_registry as dr
                    device_reg = dr.async_get(self.hass)
                    device = device_reg.async_get(entry.device_id)
                    if device:
                        area_id = device.area_id
                if area_id:
                    area_entry = area_reg.async_get_area(area_id)
                    if area_entry:
                        area_name = area_entry.name

            entities.append(
                {
                    "entity_id": state.entity_id,
                    "name": state.name,
                    "state": state.state,
                    "area": area_name,
                    "aliases": aliases,
                }
            )

        return entities

    def _render_prompt(self, exposed_entities: list[dict]) -> str:
        """Render the system prompt template."""
        tpl = template.Template(self._prompt_template, self.hass)
        return tpl.async_render(
            {"exposed_entities": exposed_entities},
            parse_result=False,
        )
