"""Sensor platform for HASSAI Bridge integration."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorDeviceClass,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.httpx_client import get_async_client
from homeassistant.helpers.device_registry import DeviceEntryType
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import CONF_API_KEY, CONF_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(minutes=2)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up HASSAI Bridge sensors."""
    base_url = entry.data[CONF_BASE_URL].rstrip("/")
    api_key = entry.data.get(CONF_API_KEY, "")

    coordinator = HASSAIDataCoordinator(hass, base_url, api_key)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {"coordinator": coordinator}

    entities = [
        HASSAIProviderSensor(coordinator, entry),
        HASSAIModelSensor(coordinator, entry),
        HASSAIUptimeSensor(coordinator, entry),
        HASSAITotalRequestsSensor(coordinator, entry),
        HASSAITotalTokensSensor(coordinator, entry),
        HASSAISearchRequestsSensor(coordinator, entry),
        HASSAIStreamRequestsSensor(coordinator, entry),
        HASSAIMemoriesSensor(coordinator, entry),
        HASSAIProviderCountSensor(coordinator, entry),
        HASSAIVersionSensor(coordinator, entry),
    ]
    async_add_entities(entities)


class HASSAIDataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetch data from HASSAI Bridge APIs."""

    def __init__(self, hass: HomeAssistant, base_url: str, api_key: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="HASSAI Bridge",
            update_interval=SCAN_INTERVAL,
        )
        self.base_url = base_url
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.api_key:
            h["Authorization"] = f"Bearer {self.api_key}"
        return h

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch all data from the bridge."""
        client = get_async_client(self.hass)
        headers = self._headers()
        info_data: dict[str, Any] = {}
        stats_data: dict[str, Any] = {}
        memory_data: dict[str, Any] = {}
        errors: list[str] = []

        try:
            resp = await client.get(
                f"{self.base_url}/api/settings/info",
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code == 401:
                raise UpdateFailed(
                    "Unauthorized (401) fetching /api/settings/info — check API key"
                )
            if resp.status_code >= 400:
                errors.append(f"info HTTP {resp.status_code}")
            else:
                info_data = resp.json()
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Failed to fetch info from HASSAI Bridge: {err}") from err

        try:
            resp = await client.get(
                f"{self.base_url}/api/settings/stats?days=30",
                headers=headers,
                timeout=15.0,
            )
            if resp.status_code < 400:
                stats_data = resp.json()
            else:
                errors.append(f"stats HTTP {resp.status_code}")
        except Exception as err:
            _LOGGER.warning("Failed to fetch stats from HASSAI Bridge: %s", err)
            errors.append("stats error")

        try:
            resp = await client.get(
                f"{self.base_url}/api/memory/users",
                headers=headers,
                timeout=10.0,
            )
            if resp.status_code < 400:
                data = resp.json()
                user_list = data.get("users", data) if isinstance(data, dict) else data
                if user_list and isinstance(user_list, list):
                    user_id = (
                        user_list[0]
                        if isinstance(user_list[0], str)
                        else user_list[0].get("user_id", "")
                    )
                    if user_id:
                        resp2 = await client.get(
                            f"{self.base_url}/api/memory/stats/{user_id}",
                            headers=headers,
                            timeout=10.0,
                        )
                        if resp2.status_code < 400:
                            memory_data = resp2.json()
            elif resp.status_code not in (401, 403):
                errors.append(f"memory HTTP {resp.status_code}")
        except Exception as err:
            _LOGGER.debug("Failed to fetch memory stats from HASSAI Bridge: %s", err)

        if not info_data:
            raise UpdateFailed(
                "HASSAI Bridge info unavailable"
                + (f" ({', '.join(errors)})" if errors else "")
            )

        return {
            "info": info_data,
            "stats": stats_data,
            "memory": memory_data,
            "errors": errors,
        }

    @property
    def info_data(self) -> dict[str, Any]:
        return (self.data or {}).get("info", {})

    @property
    def stats_data(self) -> dict[str, Any]:
        return (self.data or {}).get("stats", {})

    @property
    def memory_data(self) -> dict[str, Any]:
        return (self.data or {}).get("memory", {})


class HASSAIBaseSensor(CoordinatorEntity[HASSAIDataCoordinator], SensorEntity):
    """Base sensor for HASSAI Bridge."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HASSAIDataCoordinator,
        entry: ConfigEntry,
        key: str,
        name: str,
        icon: str,
    ) -> None:
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="HASSAI",
            entry_type=DeviceEntryType.SERVICE,
        )


class HASSAIProviderSensor(HASSAIBaseSensor):
    """Active provider sensor."""

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "active_provider", "Active Provider", "mdi:server-network")

    @property
    def native_value(self) -> str | None:
        info = self.coordinator.info_data
        providers = info.get("providers", [])
        active_id = info.get("active_provider")
        for p in providers:
            if p.get("id") == active_id:
                return p.get("name", active_id)
        # Fallback to services.provider block
        provider = (info.get("services") or {}).get("provider") or {}
        return provider.get("name") or active_id or None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        info = self.coordinator.info_data
        providers = info.get("providers", [])
        active_id = info.get("active_provider")
        for p in providers:
            if p.get("id") == active_id:
                return {
                    "provider_id": p.get("id"),
                    "provider_type": p.get("type"),
                    "base_url": p.get("base_url"),
                }
        provider = (info.get("services") or {}).get("provider") or {}
        if provider:
            return {
                "provider_id": provider.get("id"),
                "provider_type": provider.get("type"),
                "base_url": provider.get("url"),
            }
        return {}


class HASSAIModelSensor(HASSAIBaseSensor):
    """Active model sensor."""

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "active_model", "Active Model", "mdi:brain")

    @property
    def native_value(self) -> str | None:
        info = self.coordinator.info_data
        providers = info.get("providers", [])
        active_id = info.get("active_provider")
        for p in providers:
            if p.get("id") == active_id:
                return p.get("model")
        provider = (info.get("services") or {}).get("provider") or {}
        return provider.get("model")


class HASSAIUptimeSensor(HASSAIBaseSensor):
    """Server uptime sensor."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_suggested_display_precision = 0

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "uptime", "Uptime", "mdi:timer-outline")

    @property
    def native_value(self) -> int | None:
        return self.coordinator.info_data.get("uptime_seconds")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        secs = self.coordinator.info_data.get("uptime_seconds")
        if secs is None:
            return {}
        days = secs // 86400
        hours = (secs % 86400) // 3600
        mins = (secs % 3600) // 60
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        parts.append(f"{mins}m")
        return {"formatted": " ".join(parts)}


class HASSAITotalRequestsSensor(HASSAIBaseSensor):
    """Total requests sensor (last 30 days)."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "total_requests", "Total Requests (30d)", "mdi:message-processing-outline")

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.stats_data:
            return 0
        return self.coordinator.stats_data.get("total_requests", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        by_provider = self.coordinator.stats_data.get("by_provider", [])
        attrs: dict[str, Any] = {}
        for p in by_provider:
            name = p.get("provider_name", "unknown")
            attrs[f"{name}_requests"] = p.get("requests", 0)
            attrs[f"{name}_avg_ms"] = p.get("avg_response_ms", 0)
        return attrs


class HASSAITotalTokensSensor(HASSAIBaseSensor):
    """Total tokens sensor (last 30 days)."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "total_tokens", "Total Tokens (30d)", "mdi:counter")

    @property
    def native_value(self) -> int | None:
        tokens = self.coordinator.stats_data.get("tokens", {})
        return tokens.get("total", 0) if self.coordinator.stats_data else 0

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        tokens = self.coordinator.stats_data.get("tokens", {})
        return {
            "prompt_tokens": tokens.get("prompt", 0),
            "completion_tokens": tokens.get("completion", 0),
        }


class HASSAISearchRequestsSensor(HASSAIBaseSensor):
    """Search requests sensor (last 30 days)."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "search_requests", "Search Requests (30d)", "mdi:magnify")

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.stats_data:
            return 0
        return self.coordinator.stats_data.get("search_requests", 0)


class HASSAIStreamRequestsSensor(HASSAIBaseSensor):
    """Stream requests sensor (last 30 days)."""

    _attr_state_class = SensorStateClass.TOTAL

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "stream_requests", "Stream Requests (30d)", "mdi:access-point")

    @property
    def native_value(self) -> int | None:
        if not self.coordinator.stats_data:
            return 0
        return self.coordinator.stats_data.get("stream_requests", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "non_stream_requests": self.coordinator.stats_data.get("non_stream_requests", 0),
        }


class HASSAIMemoriesSensor(HASSAIBaseSensor):
    """Total memories sensor."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "memories", "Memories", "mdi:head-cog-outline")

    @property
    def native_value(self) -> int | None:
        # Prefer memory endpoint; fall back to info.stats
        if "total" in self.coordinator.memory_data:
            return self.coordinator.memory_data.get("total", 0)
        stats = self.coordinator.info_data.get("stats") or {}
        return stats.get("total_memories", 0)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        by_cat = self.coordinator.memory_data.get("by_category", {})
        return dict(by_cat) if by_cat else {}


class HASSAIProviderCountSensor(HASSAIBaseSensor):
    """Number of configured providers."""

    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "provider_count", "Providers", "mdi:cloud-outline")

    @property
    def native_value(self) -> int | None:
        providers = self.coordinator.info_data.get("providers", [])
        return len(providers)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        providers = self.coordinator.info_data.get("providers", [])
        return {
            "providers": [p.get("name", p.get("id")) for p in providers],
        }


class HASSAIVersionSensor(HASSAIBaseSensor):
    """Bridge server version sensor."""

    def __init__(self, coordinator: HASSAIDataCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry, "version", "Server Version", "mdi:tag-outline")

    @property
    def native_value(self) -> str | None:
        return self.coordinator.info_data.get("version")
