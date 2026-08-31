"""Supervisor-level HA admin tools (backups, add-ons, updates, network, …)."""

from __future__ import annotations

import asyncio
import base64
import logging
import re
import socket
from pathlib import Path
from typing import Any

log = logging.getLogger("hassai.ha.supervisor")

TOOL_SPECS: dict[str, dict] = {
    "ha_create_automation": {
        "description": (
            "Create a new automation in automations.yaml (REST config API). "
            "Pass config with alias, triggers, actions, optional conditions/mode. "
            "confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Config id (slug), e.g. porch_light_motion"},
                "config": {
                    "type": "object",
                    "description": "Automation config object (alias, triggers, actions, …)",
                },
                "confirm": {"type": "boolean"},
            },
            "required": ["config", "confirm"],
        },
    },
    "ha_update_automation": {
        "description": "Update an existing automation config by id. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Config id from automations.yaml"},
                "config": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["id", "config", "confirm"],
        },
    },
    "ha_create_script": {
        "description": "Create a script in scripts.yaml. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Script config id"},
                "config": {"type": "object", "description": "Script config (alias, sequence, …)"},
                "confirm": {"type": "boolean"},
            },
            "required": ["config", "confirm"],
        },
    },
    "ha_update_script": {
        "description": "Update an existing script config by id. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "config": {"type": "object"},
                "confirm": {"type": "boolean"},
            },
            "required": ["id", "config", "confirm"],
        },
    },
    "ha_list_backups": {
        "description": "List Home Assistant Supervisor backups (slug, name, date, size).",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_create_backup": {
        "description": (
            "Create a full Supervisor backup. Optional name; background=true returns job_id. "
            "confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "compressed": {"type": "boolean"},
                "exclude_database": {
                    "type": "boolean",
                    "description": "Exclude HA database from backup",
                },
                "background": {"type": "boolean", "description": "Return immediately with job_id"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_restore_backup": {
        "description": "Restore a full backup by slug from ha_list_backups. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "password": {"type": "string", "description": "If backup is protected"},
                "background": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["slug", "confirm"],
        },
    },
    "ha_list_addons": {
        "description": "List installed add-ons (slug, name, state, version, update_available).",
        "parameters": {
            "type": "object",
            "properties": {
                "search": {"type": "string", "description": "Filter by slug or name"},
            },
        },
    },
    "ha_get_addon": {
        "description": "Details for one add-on by slug.",
        "parameters": {
            "type": "object",
            "properties": {"slug": {"type": "string"}},
            "required": ["slug"],
        },
    },
    "ha_start_addon": {
        "description": "Start an add-on. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["slug", "confirm"],
        },
    },
    "ha_stop_addon": {
        "description": "Stop an add-on. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["slug", "confirm"],
        },
    },
    "ha_restart_addon": {
        "description": "Restart an add-on (e.g. go2rtc, Frigate). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "confirm": {"type": "boolean"},
            },
            "required": ["slug", "confirm"],
        },
    },
    "ha_list_updates": {
        "description": "List available updates for Core, OS, Supervisor, and add-ons.",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_update_core": {
        "description": "Update Home Assistant Core to latest (optional backup before). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "version": {"type": "string", "description": "Target version; default latest"},
                "backup": {"type": "boolean", "description": "Partial backup before update"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_update_addon": {
        "description": "Update an add-on from the store. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "slug": {"type": "string"},
                "backup": {"type": "boolean"},
                "background": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["slug", "confirm"],
        },
    },
    "ha_update_supervisor": {
        "description": "Update the Supervisor. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {"confirm": {"type": "boolean"}},
            "required": ["confirm"],
        },
    },
    "ha_update_os": {
        "description": "Update Home Assistant OS. Host may reboot. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {"confirm": {"type": "boolean"}},
            "required": ["confirm"],
        },
    },
    "ha_restart_core": {
        "description": "Restart Home Assistant Core container. confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "safe_mode": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_reboot_host": {
        "description": "Reboot the host machine (full system reboot). confirm=true required.",
        "parameters": {
            "type": "object",
            "properties": {
                "force": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["confirm"],
        },
    },
    "ha_network_info": {
        "description": "Supervisor network summary (interfaces, DNS, internet connectivity).",
        "parameters": {"type": "object", "properties": {}},
    },
    "ha_ping_host": {
        "description": "Ping a host/IP from the add-on network (ICMP). Helps debug unavailable devices.",
        "parameters": {
            "type": "object",
            "properties": {
                "host": {"type": "string", "description": "Hostname or IP"},
                "count": {"type": "integer", "description": "Packets (default 3, max 5)"},
            },
            "required": ["host"],
        },
    },
    "ha_check_port": {
        "description": "TCP connect check to host:port (device online / service up).",
        "parameters": {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "port": {"type": "integer"},
                "timeout": {"type": "number", "description": "Seconds (default 3)"},
            },
            "required": ["host", "port"],
        },
    },
    "ha_upload_file": {
        "description": (
            "Write a binary file to /config, /media, or /share (base64 content). "
            "For text YAML prefer ha_write_file. confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "root": {
                    "type": "string",
                    "enum": ["config", "media", "share"],
                    "description": "Mount root (default config)",
                },
                "path": {"type": "string", "description": "Relative path under root"},
                "content_base64": {"type": "string", "description": "Base64-encoded file bytes"},
                "confirm": {"type": "boolean"},
            },
            "required": ["path", "content_base64", "confirm"],
        },
    },
    "ha_mesh_network": {
        "description": (
            "ZHA / Z-Wave mesh actions via integration services: "
            "permit (ZHA join window), remove_device (ZHA ieee), heal_zwave (Z-Wave JS). "
            "confirm=true required."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["permit", "remove_device", "heal_zwave"],
                },
                "duration": {
                    "type": "integer",
                    "description": "Permit seconds (default 60)",
                },
                "ieee": {
                    "type": "string",
                    "description": "ZHA device IEEE for remove_device",
                },
                "confirm": {"type": "boolean"},
            },
            "required": ["action", "confirm"],
        },
    },
    "ha_get_job": {
        "description": "Get Supervisor job status (backups, updates, restore) by job_id.",
        "parameters": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
        },
    },
}

HANDLERS: dict[str, Any] = {}


def _ha():
    from . import homeassistant as ha
    return ha


def _require_confirm(args: dict) -> str | None:
    return _ha()._require_confirm(args)


def _dump(obj: Any, max_chars: int = 14_000) -> str:
    return _ha()._dump(obj, max_chars=max_chars)


async def _supervisor(method: str, path: str, **kwargs) -> Any:
    return await _ha()._supervisor(method, path, **kwargs)


async def _core(method: str, path: str, **kwargs) -> Any:
    return await _ha()._core(method, path, **kwargs)


def _config_id(args: dict, config: dict) -> str:
    raw = (args.get("id") or config.get("id") or config.get("alias") or "").strip()
    if not raw:
        raise ValueError("id or config.alias is required")
    return re.sub(r"[^\w]+", "_", raw.lower()).strip("_") or "automation"


async def _create_automation(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    config = args.get("config")
    if not isinstance(config, dict):
        return "Error: config must be an object"
    cid = _config_id(args, config)
    body = dict(config)
    body.setdefault("id", cid)
    await _core("POST", f"/config/automation/config/{cid}", json_body=body)
    return f"OK: created automation id={cid}. Run ha_reload what=automations confirm=true."


async def _update_automation(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    cid = (args.get("id") or "").strip()
    config = args.get("config")
    if not cid:
        return "Error: id is required"
    if not isinstance(config, dict):
        return "Error: config must be an object"
    body = dict(config)
    body["id"] = cid
    await _core("POST", f"/config/automation/config/{cid}", json_body=body)
    return f"OK: updated automation id={cid}. Run ha_reload what=automations confirm=true."


async def _create_script(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    config = args.get("config")
    if not isinstance(config, dict):
        return "Error: config must be an object"
    cid = _config_id(args, config)
    body = dict(config)
    body.setdefault("id", cid)
    await _core("POST", f"/config/script/config/{cid}", json_body=body)
    return f"OK: created script id={cid}. Run ha_reload what=scripts confirm=true."


async def _update_script(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    cid = (args.get("id") or "").strip()
    config = args.get("config")
    if not cid:
        return "Error: id is required"
    if not isinstance(config, dict):
        return "Error: config must be an object"
    body = dict(config)
    body["id"] = cid
    await _core("POST", f"/config/script/config/{cid}", json_body=body)
    return f"OK: updated script id={cid}. Run ha_reload what=scripts confirm=true."


async def _list_backups(_args: dict) -> str:
    data = await _supervisor("GET", "/backups")
    if isinstance(data, dict) and "backups" in data:
        return _dump(data.get("backups") or data)
    return _dump(data)


async def _create_backup(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    body: dict[str, Any] = {}
    if args.get("name"):
        body["name"] = str(args["name"])
    if args.get("compressed") is not None:
        body["compressed"] = bool(args["compressed"])
    if args.get("exclude_database"):
        body["homeassistant_exclude_database"] = True
    if args.get("background"):
        body["background"] = True
    result = await _supervisor("POST", "/backups/new/full", json_body=body or None)
    return f"OK: backup started\n{_dump(result)}"


async def _restore_backup(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    slug = (args.get("slug") or "").strip()
    if not slug:
        return "Error: slug is required"
    body: dict[str, Any] = {}
    if args.get("password"):
        body["password"] = str(args["password"])
    if args.get("background"):
        body["background"] = True
    result = await _supervisor("POST", f"/backups/{slug}/restore/full", json_body=body or None)
    return f"OK: restore started for {slug}\n{_dump(result)}"


def _addon_rows(data: Any) -> list[dict]:
    if isinstance(data, dict):
        addons = data.get("addons")
        if isinstance(addons, list):
            return [a for a in addons if isinstance(a, dict)]
    if isinstance(data, list):
        return [a for a in data if isinstance(a, dict)]
    return []


async def _list_addons(args: dict) -> str:
    data = await _supervisor("GET", "/addons")
    rows = _addon_rows(data)
    search = (args.get("search") or "").strip().lower()
    lines: list[str] = []
    for row in rows:
        slug = str(row.get("slug") or row.get("name") or "")
        name = str(row.get("name") or slug)
        if search and search not in slug.lower() and search not in name.lower():
            continue
        state = row.get("state") or row.get("status") or "?"
        ver = row.get("version") or "?"
        upd = row.get("update_available") or row.get("version_latest")
        extra = f" update→{upd}" if upd else ""
        lines.append(f"{slug}\t{name}\t{state}\tv{ver}{extra}")
    if not lines:
        return "No matching add-ons."
    return "slug\tname\tstate\tversion\n" + "\n".join(lines[:80])


async def _get_addon(args: dict) -> str:
    slug = (args.get("slug") or "").strip()
    if not slug:
        return "Error: slug is required"
    data = await _supervisor("GET", f"/addons/{slug}/info")
    if isinstance(data, dict) and "data" in data:
        data = data["data"]
    return _dump(data)


async def _addon_action(args: dict, action: str) -> str:
    if msg := _require_confirm(args):
        return msg
    slug = (args.get("slug") or "").strip()
    if not slug:
        return "Error: slug is required"
    await _supervisor("POST", f"/addons/{slug}/{action}")
    return f"OK: {action} {slug}"


async def _list_updates(_args: dict) -> str:
    try:
        data = await _supervisor("GET", "/available_updates")
    except Exception:
        await _supervisor("POST", "/refresh_updates")
        data = await _supervisor("GET", "/available_updates")
    return _dump(data)


async def _update_core(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    body: dict[str, Any] = {}
    if args.get("version"):
        body["version"] = str(args["version"])
    if args.get("backup"):
        body["backup"] = True
    result = await _supervisor("POST", "/core/update", json_body=body or None)
    return f"OK: Core update started\n{_dump(result)}"


async def _update_addon(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    slug = (args.get("slug") or "").strip()
    if not slug:
        return "Error: slug is required"
    body: dict[str, Any] = {}
    if args.get("backup"):
        body["backup"] = True
    if args.get("background"):
        body["background"] = True
    result = await _supervisor("POST", f"/store/addons/{slug}/update", json_body=body or None)
    return f"OK: add-on update started for {slug}\n{_dump(result)}"


async def _update_supervisor(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    result = await _supervisor("POST", "/supervisor/update")
    return f"OK: Supervisor update started\n{_dump(result)}"


async def _update_os(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    result = await _supervisor("POST", "/os/update")
    return f"OK: OS update started (host may reboot)\n{_dump(result)}"


async def _restart_core(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    body: dict[str, Any] = {}
    if args.get("safe_mode"):
        body["safe_mode"] = True
    await _supervisor("POST", "/core/restart", json_body=body or None)
    return "OK: Home Assistant Core restart requested."


async def _reboot_host(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    body: dict[str, Any] = {}
    if args.get("force"):
        body["force"] = True
    await _supervisor("POST", "/host/reboot", json_body=body or None)
    return "OK: Host reboot requested."


async def _network_info(_args: dict) -> str:
    data = await _supervisor("GET", "/network/info")
    return _dump(data)


async def _ping_host(args: dict) -> str:
    host = (args.get("host") or "").strip()
    if not host:
        return "Error: host is required"
    try:
        count = int(args.get("count") or 3)
    except (TypeError, ValueError):
        count = 3
    count = max(1, min(count, 5))
    proc = await asyncio.create_subprocess_exec(
        "ping", "-c", str(count), "-W", "2", host,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    text = (out or b"").decode("utf-8", errors="replace").strip()
    status = "reachable" if proc.returncode == 0 else "unreachable"
    return f"{host}: {status}\n{text[:4000]}"


async def _check_port(args: dict) -> str:
    host = (args.get("host") or "").strip()
    if not host:
        return "Error: host is required"
    try:
        port = int(args.get("port"))
    except (TypeError, ValueError):
        return "Error: port is required"
    try:
        timeout = float(args.get("timeout") or 3.0)
    except (TypeError, ValueError):
        timeout = 3.0
    timeout = max(0.5, min(timeout, 15.0))
    try:
        await asyncio.wait_for(
            asyncio.to_thread(_tcp_probe, host, port, timeout),
            timeout=timeout + 1.0,
        )
        return f"OK: {host}:{port} accepts TCP connections."
    except Exception as e:
        return f"FAIL: {host}:{port} — {e}"


def _tcp_probe(host: str, port: int, timeout: float) -> None:
    with socket.create_connection((host, port), timeout=timeout):
        pass


_UPLOAD_ROOTS = {
    "config": None,  # resolved via homeassistant._ha_config_dir()
    "media": Path("/media"),
    "share": Path("/share"),
}


def _safe_upload_path(root_key: str, rel: str) -> Path:
    root_key = (root_key or "config").strip().lower()
    if root_key == "config":
        from services import homeassistant as ha_mod
        root = ha_mod._ha_config_dir()
    else:
        root = _UPLOAD_ROOTS.get(root_key)
    if not root:
        raise ValueError("root must be config, media, or share")
    if not root.is_dir():
        raise ValueError(f"{root_key} mount not available")
    raw = (rel or "").strip().lstrip("/")
    if not raw or raw.endswith("/"):
        raise ValueError("path must be a file path")
    target = (root / raw).resolve()
    root_resolved = root.resolve()
    if root_resolved not in target.parents and target != root_resolved:
        raise ValueError("path escapes mount root")
    return target


async def _upload_file(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    b64 = (args.get("content_base64") or "").strip()
    if not b64:
        return "Error: content_base64 is required"
    try:
        data = base64.b64decode(b64, validate=True)
    except Exception as e:
        return f"Error: invalid base64: {e}"
    if len(data) > 25_000_000:
        return "Error: file too large (max 25MB)"
    try:
        path = _safe_upload_path(str(args.get("root") or "config"), str(args.get("path") or ""))
    except ValueError as e:
        return f"Error: {e}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"OK: wrote {path} ({len(data)} bytes)"


async def _mesh_network(args: dict) -> str:
    if msg := _require_confirm(args):
        return msg
    action = (args.get("action") or "").strip().lower()
    if action == "permit":
        try:
            duration = int(args.get("duration") or 60)
        except (TypeError, ValueError):
            duration = 60
        duration = max(10, min(duration, 300))
        await _core(
            "POST",
            "/services/zha/permit",
            json_body={"duration": duration},
        )
        return f"OK: ZHA permit join for {duration}s."
    if action == "remove_device":
        ieee = (args.get("ieee") or "").strip()
        if not ieee:
            return "Error: ieee is required for remove_device"
        await _core(
            "POST",
            "/services/zha/remove",
            json_body={"ieee": ieee},
        )
        return f"OK: ZHA remove requested for {ieee}."
    if action == "heal_zwave":
        await _core("POST", "/services/zwave_js/heal_network", json_body={})
        return "OK: Z-Wave JS heal_network started."
    return "Error: action must be permit, remove_device, or heal_zwave"


async def _get_job(args: dict) -> str:
    job_id = (args.get("job_id") or "").strip()
    if not job_id:
        return "Error: job_id is required"
    data = await _supervisor("GET", f"/jobs/{job_id}")
    return _dump(data)


async def _start_addon(args: dict) -> str:
    return await _addon_action(args, "start")


async def _stop_addon(args: dict) -> str:
    return await _addon_action(args, "stop")


async def _restart_addon(args: dict) -> str:
    return await _addon_action(args, "restart")


HANDLERS.update({
    "ha_create_automation": _create_automation,
    "ha_update_automation": _update_automation,
    "ha_create_script": _create_script,
    "ha_update_script": _update_script,
    "ha_list_backups": _list_backups,
    "ha_create_backup": _create_backup,
    "ha_restore_backup": _restore_backup,
    "ha_list_addons": _list_addons,
    "ha_get_addon": _get_addon,
    "ha_start_addon": _start_addon,
    "ha_stop_addon": _stop_addon,
    "ha_restart_addon": _restart_addon,
    "ha_list_updates": _list_updates,
    "ha_update_core": _update_core,
    "ha_update_addon": _update_addon,
    "ha_update_supervisor": _update_supervisor,
    "ha_update_os": _update_os,
    "ha_restart_core": _restart_core,
    "ha_reboot_host": _reboot_host,
    "ha_network_info": _network_info,
    "ha_ping_host": _ping_host,
    "ha_check_port": _check_port,
    "ha_upload_file": _upload_file,
    "ha_mesh_network": _mesh_network,
    "ha_get_job": _get_job,
})

