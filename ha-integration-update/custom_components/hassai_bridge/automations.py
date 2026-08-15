"""Helpers for listing and managing Home Assistant automations."""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from homeassistant.components.automation import DOMAIN as AUTOMATION_DOMAIN
from homeassistant.const import CONF_ID, SERVICE_RELOAD, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.util.yaml import dump, load_yaml
from homeassistant.util.file import write_utf8_file_atomic

_LOGGER = logging.getLogger(__name__)

AUTOMATION_CONFIG_PATH = "automations.yaml"


def _config_path(hass: HomeAssistant) -> str:
    return hass.config.path(AUTOMATION_CONFIG_PATH)


async def _read_yaml_automations(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Read automations.yaml (empty list if missing)."""
    path = _config_path(hass)

    def _read() -> list[dict[str, Any]]:
        if not os.path.isfile(path):
            return []
        data = load_yaml(path)
        if data is None:
            return []
        if not isinstance(data, list):
            raise HomeAssistantError("automations.yaml must be a list")
        return data

    return await hass.async_add_executor_job(_read)


async def _write_yaml_automations(
    hass: HomeAssistant, data: list[dict[str, Any]]
) -> None:
    """Atomically write automations.yaml."""
    path = _config_path(hass)

    def _write() -> None:
        write_utf8_file_atomic(path, dump(data))

    await hass.async_add_executor_job(_write)


async def _reload_automations(hass: HomeAssistant, automation_id: str | None = None) -> None:
    """Reload automations after a config change."""
    service_data = {CONF_ID: automation_id} if automation_id else {}
    await hass.services.async_call(
        AUTOMATION_DOMAIN, SERVICE_RELOAD, service_data, blocking=True
    )


async def _validate_automation_config(
    hass: HomeAssistant, config_key: str, config: dict[str, Any]
) -> None:
    """Validate automation config using HA's own validator when available."""
    try:
        from homeassistant.components.automation.config import (  # type: ignore
            async_validate_config_item,
        )
    except ImportError as err:
        raise HomeAssistantError(
            "Automation config validation is unavailable on this HA version"
        ) from err

    await async_validate_config_item(hass, config_key, config)


def list_automations(hass: HomeAssistant) -> list[dict[str, Any]]:
    """List automation entities with basic metadata."""
    ent_reg = er.async_get(hass)
    results: list[dict[str, Any]] = []

    for state in hass.states.async_all(AUTOMATION_DOMAIN):
        entry = ent_reg.async_get(state.entity_id)
        automation_id = entry.unique_id if entry else state.entity_id.replace(
            f"{AUTOMATION_DOMAIN}.", "", 1
        )
        results.append(
            {
                "entity_id": state.entity_id,
                "id": automation_id,
                "alias": state.attributes.get("friendly_name", state.entity_id),
                "state": state.state,
                "enabled": state.state == STATE_ON,
                "last_triggered": state.attributes.get("last_triggered"),
                "description": state.attributes.get("description"),
            }
        )

    results.sort(key=lambda item: (item.get("alias") or item["entity_id"]).lower())
    return results


async def get_automation(
    hass: HomeAssistant, automation_id: str | None = None, entity_id: str | None = None
) -> dict[str, Any]:
    """Get automation config + live state."""
    resolved_id = automation_id
    state = None

    if entity_id:
        state = hass.states.get(entity_id)
        if state is None:
            return {"error": f"Entity not found: {entity_id}"}
        if not resolved_id:
            entry = er.async_get(hass).async_get(entity_id)
            resolved_id = (
                entry.unique_id
                if entry and entry.unique_id
                else entity_id.replace(f"{AUTOMATION_DOMAIN}.", "", 1)
            )

    if not resolved_id:
        return {"error": "Provide automation_id or entity_id"}

    data = await _read_yaml_automations(hass)
    config = next((item for item in data if str(item.get(CONF_ID)) == str(resolved_id)), None)

    # Resolve state by unique_id if needed
    if state is None:
        ent_reg = er.async_get(hass)
        entity = ent_reg.async_get_entity_id(
            AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, str(resolved_id)
        )
        if entity:
            state = hass.states.get(entity)

    result: dict[str, Any] = {
        "id": resolved_id,
        "entity_id": state.entity_id if state else None,
        "state": state.state if state else None,
        "enabled": (state.state == STATE_ON) if state else None,
        "config": config,
        "editable_in_yaml": config is not None,
    }
    if config is None:
        result["note"] = (
            "No YAML config found for this id. It may be a UI/storage automation "
            "that cannot be edited via automations.yaml."
        )
    return result


def _normalize_automation_payload(payload: dict[str, Any], config_key: str) -> dict[str, Any]:
    """Normalize alias/trigger/action keys for HA automation schema."""
    normalized = dict(payload)
    normalized[CONF_ID] = config_key

    # Prefer modern plural keys; accept legacy singular from the model
    if "triggers" not in normalized and "trigger" in normalized:
        normalized["triggers"] = normalized.pop("trigger")
    if "actions" not in normalized and "action" in normalized:
        normalized["actions"] = normalized.pop("action")
    if "conditions" not in normalized and "condition" in normalized:
        normalized["conditions"] = normalized.pop("condition")

    return normalized


async def create_automation(
    hass: HomeAssistant,
    *,
    alias: str,
    triggers: list | dict,
    actions: list | dict,
    conditions: list | dict | None = None,
    description: str | None = None,
    mode: str | None = None,
    automation_id: str | None = None,
    confirm: bool = False,
) -> dict[str, Any]:
    """Create a new automation in automations.yaml."""
    if not confirm:
        return {
            "error": "Confirmation required",
            "hint": "Set confirm=true after the user explicitly approves creating this automation.",
            "preview": {
                "alias": alias,
                "triggers": triggers,
                "actions": actions,
                "conditions": conditions,
                "description": description,
            },
        }

    if not alias or triggers is None or actions is None:
        return {"error": "alias, triggers, and actions are required"}

    config_key = automation_id or uuid.uuid4().hex
    payload: dict[str, Any] = {
        "alias": alias,
        "triggers": triggers,
        "actions": actions,
    }
    if conditions is not None:
        payload["conditions"] = conditions
    if description:
        payload["description"] = description
    if mode:
        payload["mode"] = mode

    payload = _normalize_automation_payload(payload, config_key)
    await _validate_automation_config(hass, config_key, payload)

    data = await _read_yaml_automations(hass)
    if any(str(item.get(CONF_ID)) == config_key for item in data):
        return {"error": f"Automation id already exists: {config_key}"}

    # Match HA UI ordering preferences
    ordered = {CONF_ID: config_key}
    for key in (
        "alias",
        "description",
        "triggers",
        "trigger",
        "conditions",
        "condition",
        "actions",
        "action",
        "mode",
    ):
        if key in payload:
            ordered[key] = payload[key]
    ordered.update(payload)

    data.append(ordered)
    await _write_yaml_automations(hass, data)
    await _reload_automations(hass, config_key)

    return {"success": True, "id": config_key, "alias": alias, "action": "created"}


async def update_automation(
    hass: HomeAssistant,
    automation_id: str,
    updates: dict[str, Any],
    *,
    confirm: bool = False,
) -> dict[str, Any]:
    """Update an existing YAML automation."""
    if not confirm:
        return {
            "error": "Confirmation required",
            "hint": "Set confirm=true after the user explicitly approves editing this automation.",
            "preview": {"id": automation_id, "updates": updates},
        }

    data = await _read_yaml_automations(hass)
    index = next(
        (
            idx
            for idx, item in enumerate(data)
            if str(item.get(CONF_ID)) == str(automation_id)
        ),
        None,
    )
    if index is None:
        return {
            "error": f"Automation not found in automations.yaml: {automation_id}",
            "hint": "Only YAML automations with an id can be edited this way.",
        }

    merged = dict(data[index])
    merged.update(updates)
    merged = _normalize_automation_payload(merged, str(automation_id))
    await _validate_automation_config(hass, str(automation_id), merged)

    ordered = {CONF_ID: str(automation_id)}
    for key in (
        "alias",
        "description",
        "triggers",
        "trigger",
        "conditions",
        "condition",
        "actions",
        "action",
        "mode",
    ):
        if key in merged:
            ordered[key] = merged[key]
    ordered.update(merged)
    data[index] = ordered

    await _write_yaml_automations(hass, data)
    await _reload_automations(hass, str(automation_id))
    return {"success": True, "id": automation_id, "action": "updated", "config": ordered}


async def delete_automation(
    hass: HomeAssistant, automation_id: str, *, confirm: bool = False
) -> dict[str, Any]:
    """Delete a YAML automation."""
    if not confirm:
        return {
            "error": "Confirmation required",
            "hint": "Set confirm=true after the user explicitly approves deleting this automation.",
            "preview": {"id": automation_id},
        }

    data = await _read_yaml_automations(hass)
    new_data = [item for item in data if str(item.get(CONF_ID)) != str(automation_id)]
    if len(new_data) == len(data):
        return {"error": f"Automation not found in automations.yaml: {automation_id}"}

    await _write_yaml_automations(hass, new_data)

    # Remove entity if present, then reload
    ent_reg = er.async_get(hass)
    entity_id = ent_reg.async_get_entity_id(
        AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, str(automation_id)
    )
    if entity_id:
        ent_reg.async_remove(entity_id)

    await _reload_automations(hass)
    return {"success": True, "id": automation_id, "action": "deleted"}


async def toggle_automation(
    hass: HomeAssistant,
    *,
    entity_id: str | None = None,
    automation_id: str | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    """Enable/disable an automation via services (no YAML rewrite)."""
    target = entity_id
    if not target and automation_id:
        ent_reg = er.async_get(hass)
        target = ent_reg.async_get_entity_id(
            AUTOMATION_DOMAIN, AUTOMATION_DOMAIN, str(automation_id)
        )
    if not target:
        return {"error": "Provide entity_id or automation_id"}

    state = hass.states.get(target)
    if state is None:
        return {"error": f"Entity not found: {target}"}

    if enabled is None:
        enabled = state.state != STATE_ON

    service = "turn_on" if enabled else "turn_off"
    await hass.services.async_call(
        AUTOMATION_DOMAIN,
        service,
        {"entity_id": target},
        blocking=True,
    )
    return {"success": True, "entity_id": target, "enabled": enabled, "action": service}
