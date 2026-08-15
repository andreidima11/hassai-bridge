"""Config flow for HASSAI Bridge integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol
import yaml

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

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

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL, default="http://192.168.0.100:8899"): str,
        vol.Optional(CONF_API_KEY, default=""): str,
    }
)


async def validate_connection(hass, base_url: str, api_key: str) -> dict[str, Any]:
    """Validate the connection to HASSAI Bridge."""
    client = get_async_client(hass)
    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    url = f"{base_url.rstrip('/')}/v1/models"
    response = await client.get(url, headers=headers, timeout=15.0)

    if response.status_code == 401:
        return {"error": "invalid_auth"}
    if response.status_code == 403:
        return {"error": "invalid_auth"}

    response.raise_for_status()
    data = response.json()
    return {"models": data.get("data", [])}


class HASSAIBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for HASSAI Bridge."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            api_key = user_input.get(CONF_API_KEY, "")

            try:
                result = await validate_connection(self.hass, base_url, api_key)
                if "error" in result:
                    errors["base"] = result["error"]
                else:
                    await self.async_set_unique_id(base_url)
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title=f"HASSAI Bridge ({base_url})",
                        data={
                            CONF_BASE_URL: base_url,
                            CONF_API_KEY: api_key,
                        },
                    )
            except Exception:
                _LOGGER.exception("Error connecting to HASSAI Bridge")
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Create the options flow."""
        return HASSAIBridgeOptionsFlow()


class HASSAIBridgeOptionsFlow(OptionsFlow):
    """Handle options for HASSAI Bridge."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        if user_input is not None:
            # Validate functions YAML
            if CONF_FUNCTIONS in user_input:
                try:
                    yaml.safe_load(user_input[CONF_FUNCTIONS])
                except yaml.YAMLError:
                    return self.async_show_form(
                        step_id="init",
                        data_schema=self._build_options_schema(),
                        errors={CONF_FUNCTIONS: "invalid_yaml"},
                        description_placeholders={
                            "url": self.config_entry.data.get(CONF_BASE_URL, ""),
                        },
                    )

            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self._build_options_schema(),
            description_placeholders={
                "url": self.config_entry.data.get(CONF_BASE_URL, ""),
            },
        )

    def _build_options_schema(self) -> vol.Schema:
        """Build the options schema with current values."""
        options = self.config_entry.options

        return vol.Schema(
            {
                vol.Optional(
                    CONF_PROMPT,
                    default=options.get(CONF_PROMPT, DEFAULT_PROMPT),
                ): TextSelector(TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)),
                vol.Optional(
                    CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION,
                    default=options.get(
                        CONF_MAX_FUNCTION_CALLS_PER_CONVERSATION,
                        DEFAULT_MAX_FUNCTION_CALLS_PER_CONVERSATION,
                    ),
                ): int,
                vol.Optional(
                    CONF_FUNCTIONS,
                    default=options.get(
                        CONF_FUNCTIONS,
                        yaml.dump(DEFAULT_CONF_FUNCTIONS, default_flow_style=False),
                    ),
                ): TextSelector(TextSelectorConfig(multiline=True, type=TextSelectorType.TEXT)),
            }
        )
