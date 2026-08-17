"""Shared auth helpers for Web UI / HA Ingress / API keys."""

from urllib.parse import urlparse

from fastapi import HTTPException, Request

from core.config import load_config


def get_ingress_path(request: Request) -> str:
    """Return HA Ingress path prefix (no trailing slash), or empty string."""
    return (request.headers.get("x-ingress-path") or "").rstrip("/")


def is_trusted_webui(request: Request) -> bool:
    """True when the request comes from the bridge Web UI or HA Ingress.

    Ingress requests are already authenticated by Home Assistant.
    Same-origin browser requests (direct :8899) are trusted for admin/chat UI.
    """
    if request.headers.get("x-ingress-path"):
        return True

    server_host = request.headers.get("host", "")
    if not server_host:
        return False

    expected_origins = {
        f"http://{server_host}",
        f"https://{server_host}",
    }
    # Behind reverse proxies, compare against forwarded host too
    fwd_host = request.headers.get("x-forwarded-host", "").split(",")[0].strip()
    if fwd_host:
        expected_origins.update({f"http://{fwd_host}", f"https://{fwd_host}"})

    origin = request.headers.get("origin", "")
    if origin and origin in expected_origins:
        return True

    referer = request.headers.get("referer", "")
    if referer:
        ref = urlparse(referer)
        ref_origin = f"{ref.scheme}://{ref.netloc}"
        if ref_origin in expected_origins:
            return True

    return False


def require_api_key_or_webui(request: Request) -> None:
    """Require a valid API key, unless this is a trusted Web UI / Ingress request."""
    if is_trusted_webui(request):
        return

    cfg = load_config()
    expected_key = cfg.get("api_key", "")
    if not expected_key:
        return

    valid_keys = {expected_key}
    user_api_keys = cfg.get("users", {}).get("api_keys", {})
    valid_keys.update(user_api_keys.keys())

    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token in valid_keys:
            return

    assist_key = request.headers.get("x-assist-key", "").strip()
    if assist_key and assist_key in valid_keys:
        return

    raise HTTPException(status_code=401, detail="API key required")
