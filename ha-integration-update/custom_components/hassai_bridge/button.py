"""Button platform for HASSAI Bridge integration."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo

from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HASSAI Bridge buttons."""
    async_add_entities([HASSAIRestartButton(hass, entry)])


class HASSAIRestartButton(ButtonEntity):
    """Button to restart the HASSAI Bridge server."""

    _attr_has_entity_name = True
    _attr_name = "Restart Server"
    _attr_icon = "mdi:restart"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_restart"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HASSAI",
            entry_type=DeviceEntryType.SERVICE,
        )

    async def async_press(self) -> None:
        """Restart the HASSAI Bridge server."""
        base_url = self.entry.data[CONF_BASE_URL].rstrip("/")
        api_key = self.entry.data.get(CONF_API_KEY, "")

        client = get_async_client(self.hass)
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            resp = await client.post(
                f"{base_url}/api/settings/restart",
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code < 400:
                _LOGGER.info("HASSAI Bridge server restart triggered")
            else:
                _LOGGER.error(
                    "Failed to restart HASSAI Bridge: HTTP %s", resp.status_code
                )
        except Exception as err:
            _LOGGER.error("Error restarting HASSAI Bridge: %s", err)
