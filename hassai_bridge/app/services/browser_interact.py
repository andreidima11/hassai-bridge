"""Interactive headless browser for HASSAI (Playwright + system Chromium).

Allowlisted domains only. Screenshots attach to chat like generated images.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

log = logging.getLogger("hassai.browser")

TOOL_NAME = "browser_interact"
_IDLE_SEC = 10 * 60
_MAX_WIDTH = 1280
_DEFAULT_VIEWPORT = {"width": 1280, "height": 800}
_MOBILE_VIEWPORT = {"width": 390, "height": 844}

_SENSITIVE_PATH_PREFIXES = (
    "/auth",
    "/api/hassio",
    "/hassio",
    "/config/cloud",
)

# session_id → BrowserSession
_sessions: dict[str, "BrowserSession"] = {}
_lock = asyncio.Lock()

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Open an allowlisted web page in a headless browser, take screenshots, "
            "click, scroll, or type. Use to visually verify Home Assistant dashboards "
            "and other approved sites after changes. Always screenshot after navigate/click."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["open", "screenshot", "click", "scroll", "type", "close"],
                    "description": "Browser action to perform",
                },
                "url": {
                    "type": "string",
                    "description": "Full http(s) URL for action=open",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS selector for click/type",
                },
                "text": {
                    "type": "string",
                    "description": "Text to type (action=type)",
                },
                "direction": {
                    "type": "string",
                    "enum": ["down", "up", "top", "bottom"],
                    "description": "Scroll direction (action=scroll)",
                },
                "viewport": {
                    "type": "string",
                    "enum": ["desktop", "mobile"],
                    "description": "Viewport preset (default desktop)",
                },
                "wait_ms": {
                    "type": "integer",
                    "description": "Extra wait after load/action (ms, max 15000)",
                },
            },
            "required": ["action"],
        },
    },
}


def is_enabled(cfg: dict | None = None) -> bool:
    if cfg is None:
        from config import load_config

        cfg = load_config()
    browser = (cfg or {}).get("browser") or {}
    return bool(browser.get("enabled"))


def _browser_cfg(cfg: dict | None = None) -> dict:
    if cfg is None:
        from config import load_config

        cfg = load_config()
    return dict((cfg or {}).get("browser") or {})


def _normalize_domain(host: str) -> str:
    host = str(host or "").strip().lower().rstrip(".")
    if host.startswith("www."):
        host = host[4:]
    return host


def _ha_base_url(cfg: dict | None = None) -> str:
    b = _browser_cfg(cfg)
    url = str(b.get("ha_url") or "").strip()
    if url:
        return url.rstrip("/")
    return "http://homeassistant:8123"


def allowed_hosts(cfg: dict | None = None) -> set[str]:
    b = _browser_cfg(cfg)
    hosts: set[str] = set()
    for item in b.get("allowlist") or []:
        host = _normalize_domain(item)
        if host:
            hosts.add(host)
    try:
        ha = urlparse(_ha_base_url(cfg))
        if ha.hostname:
            hosts.add(_normalize_domain(ha.hostname))
    except Exception:
        pass
    # Common LAN aliases for HA
    hosts.update({"homeassistant", "homeassistant.local", "supervisor", "localhost", "127.0.0.1"})
    return hosts


def url_allowed(url: str, cfg: dict | None = None) -> tuple[bool, str]:
    raw = str(url or "").strip()
    if not raw:
        return False, "empty URL"
    try:
        parsed = urlparse(raw)
    except Exception as exc:
        return False, f"invalid URL: {exc}"
    if parsed.scheme not in {"http", "https"}:
        return False, "only http(s) URLs are allowed"
    host = _normalize_domain(parsed.hostname or "")
    if not host:
        return False, "URL missing host"
    if host not in allowed_hosts(cfg):
        return False, f"host '{host}' is not on the browser allowlist"
    path = parsed.path or "/"
    for prefix in _SENSITIVE_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return False, f"path '{path}' is blocked"
    return True, ""


def _chromium_path() -> str | None:
    for candidate in (
        os.environ.get("HASSAI_CHROMIUM_PATH", "").strip(),
        "/usr/bin/chromium-browser",
        "/usr/bin/chromium",
        "/usr/lib/chromium/chromium",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


class BrowserSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self.last_used = time.time()
        self.authenticated_ha = False

    async def ensure(self, cfg: dict | None = None, *, viewport: str = "desktop") -> Any:
        self.last_used = time.time()
        vp = _MOBILE_VIEWPORT if viewport == "mobile" else _DEFAULT_VIEWPORT
        if self._page is not None:
            try:
                await self._page.set_viewport_size(vp)
            except Exception:
                pass
            return self._page

        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise RuntimeError(
                "Playwright is not installed. Rebuild the add-on with Chromium support."
            ) from exc

        exe = _chromium_path()
        if not exe:
            raise RuntimeError(
                "Chromium binary not found. Rebuild the add-on image with Chromium packages."
            )

        self._pw = await async_playwright().start()
        launch_args = [
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
        ]
        self._browser = await self._pw.chromium.launch(
            executable_path=exe,
            headless=True,
            args=launch_args,
        )
        self._context = await self._browser.new_context(
            viewport=vp,
            ignore_https_errors=True,
        )
        self._page = await self._context.new_page()
        return self._page

    async def close(self) -> None:
        for closer in (
            (self._context, "close"),
            (self._browser, "close"),
            (self._pw, "stop"),
        ):
            obj, method = closer
            if obj is None:
                continue
            try:
                await getattr(obj, method)()
            except Exception:
                pass
        self._page = None
        self._context = None
        self._browser = None
        self._pw = None
        self.authenticated_ha = False

    async def inject_ha_auth(self, cfg: dict | None = None) -> None:
        if self.authenticated_ha or self._page is None:
            return
        b = _browser_cfg(cfg)
        token = str(b.get("access_token") or "").strip()
        if not token:
            token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
        if not token:
            return
        ha_url = _ha_base_url(cfg)
        # Home Assistant frontend reads hassTokens from localStorage.
        expires = int(time.time() * 1000) + 10 * 365 * 24 * 3600 * 1000
        script = """
        ([haUrl, token, expires]) => {
          const payload = {
            hassUrl: haUrl,
            access_token: token,
            token_type: 'Bearer',
            expires: expires,
            refresh_token: '',
            clientId: haUrl + '/',
          };
          localStorage.setItem('hassTokens', JSON.stringify(payload));
        }
        """
        try:
            await self._page.goto(ha_url + "/", wait_until="domcontentloaded", timeout=30000)
            await self._page.evaluate(script, [ha_url, token, expires])
            self.authenticated_ha = True
        except Exception as exc:
            log.warning("HA auth inject failed: %s", exc)


async def _gc_sessions(cfg: dict | None = None) -> None:
    now = time.time()
    idle = _IDLE_SEC
    if (_browser_cfg(cfg).get("keep_warm")):
        idle = max(idle, 60 * 60)
    stale = [sid for sid, s in _sessions.items() if now - s.last_used > idle]
    for sid in stale:
        sess = _sessions.pop(sid, None)
        if sess:
            await sess.close()


async def _get_session(session_id: str, cfg: dict | None = None) -> BrowserSession:
    sid = str(session_id or "").strip() or "default"
    async with _lock:
        await _gc_sessions(cfg)
        sess = _sessions.get(sid)
        if sess is None:
            sess = BrowserSession(sid)
            _sessions[sid] = sess
        return sess


async def close_session(session_id: str | None) -> None:
    sid = str(session_id or "").strip() or "default"
    async with _lock:
        sess = _sessions.pop(sid, None)
    if sess:
        await sess.close()


def _resize_png(raw: bytes, max_width: int = _MAX_WIDTH) -> bytes:
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(raw))
        if img.width <= max_width:
            return raw
        ratio = max_width / float(img.width)
        size = (max_width, max(1, int(img.height * ratio)))
        img = img.resize(size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        img.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        return raw


async def _accessibility_summary(page, limit: int = 1200) -> str:
    try:
        snapshot = await page.accessibility.snapshot()
    except Exception:
        return ""
    if not isinstance(snapshot, dict):
        return ""
    lines: list[str] = []

    def walk(node: dict, depth: int = 0) -> None:
        if len("\n".join(lines)) > limit:
            return
        role = str(node.get("role") or "")
        name = str(node.get("name") or "").strip()
        if name and role in {"button", "link", "heading", "textbox", "checkbox", "switch", "tab"}:
            lines.append(f"{'  ' * depth}{role}: {name[:80]}")
        for child in node.get("children") or []:
            if isinstance(child, dict):
                walk(child, depth + 1)

    walk(snapshot)
    return "\n".join(lines)[:limit]


async def run_tool(
    args: dict,
    *,
    user_id: str = "",
    session_id: str | None = None,
    generated_attachments: list | None = None,
    cfg: dict | None = None,
) -> str:
    if not is_enabled(cfg):
        return "Error: browser_interact is disabled in Settings."
    action = str(args.get("action") or "").strip().lower()
    if action not in {"open", "screenshot", "click", "scroll", "type", "close"}:
        return "Error: action must be open|screenshot|click|scroll|type|close"

    if action == "close":
        await close_session(session_id)
        return "Browser session closed."

    viewport = str(args.get("viewport") or "desktop").strip().lower()
    wait_ms = max(0, min(int(args.get("wait_ms") or 0), 15000))
    sess = await _get_session(session_id or "", cfg)
    try:
        page = await sess.ensure(cfg, viewport=viewport)
    except Exception as exc:
        return f"Error: could not start browser — {exc}"

    try:
        if action == "open":
            url = str(args.get("url") or "").strip()
            ok, reason = url_allowed(url, cfg)
            if not ok:
                return f"Error: {reason}"
            ha_base = _ha_base_url(cfg)
            if url.rstrip("/").startswith(ha_base.rstrip("/")) or "homeassistant" in (urlparse(url).hostname or ""):
                await sess.inject_ha_auth(cfg)
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            if wait_ms:
                await page.wait_for_timeout(wait_ms)
            else:
                await page.wait_for_timeout(750)
            title = await page.title()
            return f"Opened {url} (title: {title or '—'}). Call action=screenshot to capture the page."

        if action == "click":
            selector = str(args.get("selector") or "").strip()
            if not selector:
                return "Error: selector required for click"
            await page.click(selector, timeout=15000)
            if wait_ms:
                await page.wait_for_timeout(wait_ms)
            else:
                await page.wait_for_timeout(400)
            return f"Clicked {selector}. Call action=screenshot to verify."

        if action == "type":
            selector = str(args.get("selector") or "").strip()
            text = str(args.get("text") or "")
            if not selector:
                return "Error: selector required for type"
            await page.fill(selector, text, timeout=15000)
            return f"Typed into {selector}."

        if action == "scroll":
            direction = str(args.get("direction") or "down").lower()
            if direction == "top":
                await page.evaluate("window.scrollTo(0, 0)")
            elif direction == "bottom":
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            elif direction == "up":
                await page.evaluate("window.scrollBy(0, -Math.floor(window.innerHeight * 0.8))")
            else:
                await page.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.8))")
            await page.wait_for_timeout(300)
            return f"Scrolled {direction}."

        # screenshot
        if wait_ms:
            await page.wait_for_timeout(wait_ms)
        png = await page.screenshot(full_page=False, type="png")
        png = _resize_png(png)
        summary = await _accessibility_summary(page)
        url = page.url
        title = await page.title()
        from services import chat_media as cm

        att = cm.save_uploaded_file(
            user_id or "default",
            png,
            filename="browser-screenshot.png",
            content_type="image/png",
        )
        if generated_attachments is not None:
            generated_attachments.append(att)
        bits = [f"Screenshot of {url}", f"title: {title or '—'}"]
        if summary:
            bits.append("Visible controls:\n" + summary)
        bits.append("Image attached to the chat for visual review.")
        return "\n".join(bits)
    except Exception as exc:
        log.exception("browser_interact failed action=%s", action)
        return f"Error: browser {action} failed — {exc}"
