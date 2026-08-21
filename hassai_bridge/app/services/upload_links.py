"""Short-lived upload links.

The Companion app tears down the Ingress panel when the native file dialog
opens. A link lets the user pick the file in the phone browser instead; the
chat picks up whatever arrives on the link.
"""

from __future__ import annotations

import secrets
import time

TTL_SECONDS = 900.0
MAX_LINKS = 50
MAX_FILES_PER_LINK = 8

_links: dict[str, dict] = {}


def _prune(now: float | None = None) -> None:
    stamp = now if now is not None else time.time()
    for token in [t for t, link in _links.items() if link["expires"] <= stamp]:
        _links.pop(token, None)
    while len(_links) > MAX_LINKS:
        oldest = min(_links, key=lambda t: _links[t]["created"])
        _links.pop(oldest, None)


def create(username: str) -> dict:
    _prune()
    token = secrets.token_hex(16)
    now = time.time()
    _links[token] = {
        "username": str(username or "default"),
        "created": now,
        "expires": now + TTL_SECONDS,
        "files": [],
    }
    return {"token": token, "expires_in": int(TTL_SECONDS)}


def owner(token: str) -> str | None:
    """Username the link belongs to, or None when unknown/expired."""
    _prune()
    link = _links.get(str(token or "").strip())
    return link["username"] if link else None


def add_file(token: str, payload: dict) -> None:
    _prune()
    link = _links.get(str(token or "").strip())
    if not link:
        raise ValueError("Link expired")
    if len(link["files"]) >= MAX_FILES_PER_LINK:
        raise ValueError("Too many files for this link")
    link["files"].append(payload)


def take_files(token: str, username: str) -> dict:
    """Return files uploaded so far and clear them (only for the owner)."""
    _prune()
    link = _links.get(str(token or "").strip())
    if not link:
        return {"expired": True, "files": []}
    if link["username"] != str(username or "default"):
        return {"expired": True, "files": []}
    files = link["files"]
    link["files"] = []
    return {"expired": False, "files": files}


def reset_for_test() -> None:
    _links.clear()
