"""Frigate camera tools: recent events + snapshots into chat.

Prefers the Frigate HTTP API (HA add-on). Falls back to /media/frigate clips
when the API is unreachable but the media folder is mounted.
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from config import load_config
from services import chat_files as cf

log = logging.getLogger("hassai.frigate")

# Official Frigate HA add-on hostname on the supervisor network.
_DEFAULT_BASE_URLS = (
    "http://ccab4aaf-frigate:5000",
    "http://frigate:5000",
    "http://homeassistant.local:5000",
)

_CAMERA_RE = re.compile(r"^[a-zA-Z0-9_-]+$")


def _cfg() -> dict:
    return dict((load_config().get("frigate") or {}))


def is_enabled() -> bool:
    cfg = _cfg()
    if cfg.get("enabled") is False:
        return False
    # Auto-on when explicitly configured, or when media/frigate exists, or default URL works.
    if cfg.get("base_url") or cfg.get("enabled") is True:
        return True
    return bool(media_frigate_root())


def media_frigate_root() -> Path | None:
    for root in cf.roots():
        candidate = root / "frigate"
        if candidate.is_dir():
            return candidate
        # Sometimes Frigate mounts directly as /media with clips/ at top
        if root.name == "media" and (root / "clips").is_dir():
            return root
    return None


def base_url() -> str:
    cfg = _cfg()
    raw = str(cfg.get("base_url") or "").strip().rstrip("/")
    if raw:
        return raw
    return _DEFAULT_BASE_URLS[0]


def _timeout() -> float:
    try:
        return float((_cfg().get("timeout") or 12))
    except (TypeError, ValueError):
        return 12.0


def _normalize_camera(name: str) -> str:
    cam = str(name or "").strip()
    if not cam:
        return ""
    # Allow entity ids like camera.front_yard → front_yard
    if cam.startswith("camera."):
        cam = cam.split(".", 1)[1]
    cam = cam.replace(" ", "_")
    if not _CAMERA_RE.match(cam):
        raise ValueError(f"Invalid camera name: {name}")
    return cam


def _fmt_ts(ts: float | int | None) -> str:
    if ts is None:
        return "—"
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    except (TypeError, ValueError, OSError):
        return str(ts)


async def _get_json(path: str, params: dict | None = None) -> Any:
    url = f"{base_url()}{path}"
    async with httpx.AsyncClient(timeout=_timeout(), follow_redirects=True) as client:
        resp = await client.get(url, params=params or {})
        if resp.status_code >= 400:
            raise ValueError(f"Frigate API {resp.status_code} for {path}: {resp.text[:200]}")
        return resp.json()


async def _get_bytes(path: str, params: dict | None = None) -> tuple[bytes, str]:
    url = f"{base_url()}{path}"
    async with httpx.AsyncClient(timeout=_timeout(), follow_redirects=True) as client:
        resp = await client.get(url, params=params or {})
        if resp.status_code >= 400:
            raise ValueError(f"Frigate API {resp.status_code} for {path}: {resp.text[:120]}")
        ctype = (resp.headers.get("content-type") or "image/jpeg").split(";")[0].strip()
        data = resp.content
        if not data:
            raise ValueError("Empty image from Frigate")
        return data, ctype


async def api_reachable() -> bool:
    try:
        await _get_json("/api/version")
        return True
    except Exception:
        try:
            await _get_json("/api/config")
            return True
        except Exception:
            return False


async def health_status(*, probe_timeout: float = 2.5) -> dict:
    """Fast status for Settings dashboard (must not hang Ingress).

    Returns {"status": connected|unreachable|disabled, "via": api|media|"", "url": str, "enabled": bool}
    """
    cfg = _cfg()
    enabled = cfg.get("enabled") is not False
    url = base_url()
    if not enabled:
        return {"status": "disabled", "via": "", "url": url, "enabled": False}

    async def _probe_api() -> bool:
        timeout = min(float(probe_timeout), _timeout())
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                resp = await client.get(f"{url}/api/version")
                if resp.status_code < 400:
                    return True
                resp = await client.get(f"{url}/api/config")
                return resp.status_code < 400
        except Exception:
            return False

    try:
        ok = await asyncio.wait_for(_probe_api(), timeout=float(probe_timeout) + 0.5)
    except Exception:
        ok = False

    if ok:
        return {"status": "connected", "via": "api", "url": url, "enabled": True}

    # Tools still work via /media/frigate — treat as connected for the dashboard.
    if media_frigate_root():
        return {"status": "connected", "via": "media", "url": url, "enabled": True}

    return {"status": "unreachable", "via": "", "url": url, "enabled": True}


async def list_cameras() -> str:
    """List Frigate cameras (API preferred, else media folder)."""
    try:
        cfg = await _get_json("/api/config")
        cams = sorted((cfg.get("cameras") or {}).keys())
        if not cams:
            return "Frigate API reachable, but no cameras are configured."
        lines = [f"Frigate cameras ({len(cams)}):"]
        for name in cams:
            lines.append(f"• {name}")
        lines.append("Tip: use frigate_events or frigate_snapshot with camera=<name>.")
        return "\n".join(lines)
    except Exception as api_err:
        log.info("Frigate API list failed (%s); trying /media/frigate", api_err)

    root = media_frigate_root()
    if not root:
        return (
            f"Error: cannot reach Frigate at {base_url()} and /media/frigate is not mounted. "
            "Set Settings → config frigate.base_url (e.g. http://ccab4aaf-frigate:5000) "
            "or map the Frigate media folder into the add-on."
        )
    cams: set[str] = set()
    clips = root / "clips"
    base = clips if clips.is_dir() else root
    try:
        for path in base.iterdir():
            if not path.is_file():
                continue
            # front_door-1234567890.123456-abcdef.jpg or camera-name-uuid.jpg
            stem = path.stem
            if "-" in stem:
                cams.add(stem.split("-", 1)[0])
    except OSError as exc:
        return f"Error reading {base}: {exc}"
    if not cams:
        return f"Found {root}, but no camera clip files yet."
    lines = [f"Cameras from media ({root}):"]
    for name in sorted(cams):
        lines.append(f"• {name}")
    return "\n".join(lines)


def _event_line(ev: dict) -> str:
    cam = ev.get("camera") or "?"
    label = ev.get("label") or "?"
    sub = str(ev.get("sub_label") or "").strip()
    if sub:
        label = f"{label}/{sub}"
    score = ev.get("top_score") or ev.get("score")
    score_s = f"{float(score):.0%}" if isinstance(score, (int, float)) else "—"
    start = _fmt_ts(ev.get("start_time"))
    end = ev.get("end_time")
    if end is None:
        status = "still on camera (in progress)"
    else:
        status = f"left {_fmt_ts(end)}"
    if ev.get("stationary") or ev.get("motionless"):
        status += ", stationary"
    zones = ev.get("current_zones") or ev.get("entered_zones") or ev.get("zones") or []
    zone_s = ""
    if isinstance(zones, list) and zones:
        zone_s = f" — zone: {', '.join(str(z) for z in zones[:3])}"
    eid = ev.get("id") or ""
    snap = "yes" if ev.get("has_snapshot") else "no"
    return (
        f"• {start} — {cam} / {label} ({score_s}) — {status}{zone_s} — "
        f"snapshot={snap} — id={eid}"
    )


_MAX_ATTACHED_SNAPSHOTS = 1


async def list_events(
    camera: str = "",
    label: str = "",
    limit: int = 8,
    *,
    include_snapshot: bool = False,
) -> dict:
    """Return recent events. Optionally attach snapshots for the listed events.

    Returns {
      "text": str,
      "image": first snap or None (back-compat),
      "images": list of {"bytes", "filename", "mime"},
    }
    """
    cam = _normalize_camera(camera) if camera else ""
    lab = str(label or "").strip().lower()
    try:
        lim = max(1, min(int(limit or 8), 25))
    except (TypeError, ValueError):
        lim = 8

    params: dict[str, Any] = {"limit": lim, "has_snapshot": 1}
    if cam:
        params["camera"] = cam
    if lab:
        params["label"] = lab

    try:
        events = await _get_json("/api/events", params)
        if not isinstance(events, list):
            events = []
    except Exception as api_err:
        log.info("Frigate events API failed (%s); using media fallback", api_err)
        return await _events_from_media(cam, lim, include_snapshot=include_snapshot)

    if not events:
        where = f" on {cam}" if cam else ""
        what = f" ({lab})" if lab else ""
        return {
            "text": f"No recent Frigate events{where}{what} with snapshots.",
            "image": None,
            "images": [],
        }

    header = f"Recent Frigate events ({len(events)}):"
    lines = [header] + [_event_line(ev) for ev in events]
    images: list[dict] = []
    if include_snapshot:
        top = events[0]
        eid = str(top.get("id") or "")
        if eid and top.get("has_snapshot"):
            try:
                data, mime = await _get_bytes(f"/api/events/{eid}/snapshot.jpg")
                cam_name = top.get("camera") or "camera"
                images.append({
                    "bytes": data,
                    "filename": f"frigate-{cam_name}-{eid[:12]}.jpg",
                    "mime": mime or "image/jpeg",
                })
                lines.append(
                    f"Attached snapshot for latest event: {cam_name} / {top.get('label')}."
                )
            except Exception as snap_err:
                lines.append(f"(Could not fetch snapshot for {eid}: {snap_err})")
        if not images:
            cname = _normalize_camera(top.get("camera") or cam)
            if cname:
                try:
                    data, mime = await _get_bytes(f"/api/{cname}/latest.jpg")
                    images.append({
                        "bytes": data,
                        "filename": f"frigate-{cname}-latest.jpg",
                        "mime": mime or "image/jpeg",
                    })
                    lines.append(f"Attached latest frame from {cname}.")
                except Exception as snap_err:
                    lines.append(f"(Could not fetch latest frame: {snap_err})")

    return {
        "text": "\n".join(lines),
        "image": images[0] if images else None,
        "images": images,
    }


async def _events_from_media(camera: str, limit: int, *, include_snapshot: bool) -> dict:
    root = media_frigate_root()
    if not root:
        return {
            "text": (
                f"Error: Frigate API unreachable ({base_url()}) and /media/frigate not found. "
                "Set frigate.base_url in config."
            ),
            "image": None,
            "images": [],
        }
    clips = root / "clips"
    base = clips if clips.is_dir() else root
    files: list[Path] = []
    try:
        for path in base.iterdir():
            if not path.is_file():
                continue
            if path.suffix.lower() not in cf.IMAGE_EXT:
                continue
            if camera and not path.name.lower().startswith(camera.lower() + "-"):
                continue
            # Skip clean copies for listing preference
            if "-clean" in path.stem:
                continue
            files.append(path)
    except OSError as exc:
        return {"text": f"Error reading {base}: {exc}", "image": None, "images": []}

    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    files = files[:limit]
    if not files:
        return {
            "text": f"No snapshot files under {base}" + (f" for {camera}" if camera else "") + ".",
            "image": None,
            "images": [],
        }

    lines = [f"Recent Frigate media files ({base}):"]
    for path in files:
        try:
            when = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        except OSError:
            when = "—"
        lines.append(f"• {when} — {path.name}")

    images: list[dict] = []
    if include_snapshot and files:
        path = files[0]
        try:
            images.append({
                "bytes": path.read_bytes(),
                "filename": path.name,
                "mime": "image/jpeg",
            })
            lines.append(f"Attached {path.name}.")
        except OSError as exc:
            lines.append(f"(Could not read {path.name}: {exc})")

    return {
        "text": "\n".join(lines),
        "image": images[0] if images else None,
        "images": images,
    }


async def snapshot(camera: str = "", event_id: str = "") -> dict:
    """Fetch one snapshot (event id or latest for camera)."""
    eid = str(event_id or "").strip()
    cam = _normalize_camera(camera) if camera else ""

    def _one(text: str, image: dict) -> dict:
        return {"text": text, "image": image, "images": [image]}

    if eid:
        data, mime = await _get_bytes(f"/api/events/{eid}/snapshot.jpg")
        return _one(
            f"Snapshot for event {eid}.",
            {
                "bytes": data,
                "filename": f"frigate-event-{eid[:16]}.jpg",
                "mime": mime or "image/jpeg",
            },
        )

    if not cam:
        # Latest event with snapshot across all cameras
        result = await list_events(limit=1, include_snapshot=True)
        if result.get("image"):
            return result
        raise ValueError("camera or event_id is required for a snapshot")

    # Prefer latest.jpg for a live-ish frame; also try events
    try:
        data, mime = await _get_bytes(f"/api/{cam}/latest.jpg")
        # Enrich with last event info when possible
        extra = ""
        try:
            events = await _get_json(
                "/api/events",
                {"camera": cam, "limit": 1, "has_snapshot": 1},
            )
            if isinstance(events, list) and events:
                ev = events[0]
                extra = (
                    f" Last detection: {_fmt_ts(ev.get('start_time'))} — "
                    f"{ev.get('label') or '?'} "
                    f"({float(ev.get('top_score') or ev.get('score') or 0):.0%})."
                )
        except Exception:
            pass
        return _one(
            f"Latest snapshot from {cam}.{extra}",
            {
                "bytes": data,
                "filename": f"frigate-{cam}-latest.jpg",
                "mime": mime or "image/jpeg",
            },
        )
    except Exception as api_err:
        log.info("Frigate latest.jpg failed for %s (%s); media fallback", cam, api_err)
        media = await _events_from_media(cam, 1, include_snapshot=True)
        if media.get("image"):
            return media
        raise ValueError(
            f"Cannot get snapshot for {cam}: API error ({api_err}) and no media files."
        ) from api_err


def system_hint() -> str:
    if not is_enabled():
        return ""
    return (
        "Frigate cameras (real NVR — never use generate_image / Imagine): "
        "When the user asks what was detected (people, cars, times, parked/still on camera), "
        "call frigate_events with include_snapshot=false and answer in natural language from the "
        "event list — do not attach photos unless they explicitly ask to see/show snaps or a photo. "
        "Only then use include_snapshot=true (one newest snap) or frigate_snapshot for a specific "
        "camera or event_id. Do not call frigate_events with include_snapshot on every turn."
    )
