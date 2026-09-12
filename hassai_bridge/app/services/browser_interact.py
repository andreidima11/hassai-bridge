"""Interactive headless browser for HASSAI (system Chromium + CDP).

Playwright has no musllinux wheels (HA Alpine base), so we drive Chromium
via the Chrome DevTools Protocol over websockets. Allowlisted domains only.
Screenshots attach to chat like generated images.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
import websockets

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
    from services import bridge_tool_access as bta

    # Primary toggle: Settings → HASSAI Bridge tool permissions → browser.
    # Legacy: browser.enabled (Cameras card) still honored if set.
    if bta.group_enabled("browser", cfg):
        return True
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
        "/usr/bin/chromium",
        "/usr/bin/chromium-browser",
        "/usr/lib/chromium/chromium",
    ):
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class CdpClient:
    """Minimal Chrome DevTools Protocol client over one WebSocket."""

    def __init__(self, ws):
        self._ws = ws
        self._next_id = 1
        self._pending: dict[int, asyncio.Future] = {}
        self._reader: asyncio.Task | None = None

    async def start(self) -> None:
        self._reader = asyncio.create_task(self._read_loop())

    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mid = msg.get("id")
                if mid is None:
                    continue
                fut = self._pending.pop(int(mid), None)
                if fut and not fut.done():
                    if "error" in msg:
                        err = msg["error"]
                        fut.set_exception(
                            RuntimeError(err.get("message") or str(err))
                        )
                    else:
                        fut.set_result(msg.get("result") or {})
        except Exception:
            for fut in list(self._pending.values()):
                if not fut.done():
                    fut.set_exception(RuntimeError("CDP connection closed"))
            self._pending.clear()

    async def call(self, method: str, params: dict | None = None, *, timeout: float = 45.0) -> dict:
        mid = self._next_id
        self._next_id += 1
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        payload = {"id": mid, "method": method, "params": params or {}}
        await self._ws.send(json.dumps(payload))
        return await asyncio.wait_for(fut, timeout=timeout)

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
            try:
                await self._reader
            except Exception:
                pass
            self._reader = None
        try:
            await self._ws.close()
        except Exception:
            pass


class BrowserSession:
    def __init__(self, session_id: str):
        self.session_id = session_id
        self._proc: asyncio.subprocess.Process | None = None
        self._cdp: CdpClient | None = None
        self._port = 0
        self._viewport = dict(_DEFAULT_VIEWPORT)
        self.last_used = time.time()
        self.authenticated_ha = False
        self._url = "about:blank"
        self._title = ""

    async def ensure(self, cfg: dict | None = None, *, viewport: str = "desktop") -> None:
        self.last_used = time.time()
        self._viewport = dict(_MOBILE_VIEWPORT if viewport == "mobile" else _DEFAULT_VIEWPORT)
        if self._cdp is not None and self._proc and self._proc.returncode is None:
            await self._cdp.call(
                "Emulation.setDeviceMetricsOverride",
                {
                    "width": self._viewport["width"],
                    "height": self._viewport["height"],
                    "deviceScaleFactor": 1,
                    "mobile": viewport == "mobile",
                },
            )
            return

        exe = _chromium_path()
        if not exe:
            raise RuntimeError(
                "Chromium binary not found. Rebuild the add-on image with Chromium packages."
            )

        self._port = _free_port()
        args = [
            exe,
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-extensions",
            "--disable-background-networking",
            "--hide-scrollbars",
            "--mute-audio",
            f"--remote-debugging-address=127.0.0.1",
            f"--remote-debugging-port={self._port}",
            "--remote-allow-origins=*",
            "about:blank",
        ]
        self._proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        ws_url = await self._wait_devtools(self._port)
        ws = await websockets.connect(ws_url, max_size=32 * 1024 * 1024)
        self._cdp = CdpClient(ws)
        await self._cdp.start()
        await self._cdp.call("Page.enable")
        await self._cdp.call("Runtime.enable")
        await self._cdp.call("DOM.enable")
        await self._cdp.call(
            "Emulation.setDeviceMetricsOverride",
            {
                "width": self._viewport["width"],
                "height": self._viewport["height"],
                "deviceScaleFactor": 1,
                "mobile": viewport == "mobile",
            },
        )

    async def _wait_devtools(self, port: int, timeout: float = 20.0) -> str:
        deadline = time.time() + timeout
        url = f"http://127.0.0.1:{port}/json/version"
        last_err = ""
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.time() < deadline:
                if self._proc and self._proc.returncode is not None:
                    raise RuntimeError(f"Chromium exited early (code {self._proc.returncode})")
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        data = resp.json()
                        ws = data.get("webSocketDebuggerUrl")
                        if ws:
                            return str(ws)
                except Exception as exc:
                    last_err = str(exc)
                await asyncio.sleep(0.15)
        raise RuntimeError(f"Chromium DevTools not ready: {last_err or 'timeout'}")

    async def close(self) -> None:
        if self._cdp:
            try:
                await self._cdp.close()
            except Exception:
                pass
            self._cdp = None
        if self._proc and self._proc.returncode is None:
            try:
                self._proc.terminate()
                try:
                    await asyncio.wait_for(self._proc.wait(), timeout=3)
                except asyncio.TimeoutError:
                    self._proc.kill()
                    await self._proc.wait()
            except Exception:
                pass
        self._proc = None
        self.authenticated_ha = False

    async def evaluate(self, expression: str) -> Any:
        assert self._cdp
        result = await self._cdp.call(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
        )
        if result.get("exceptionDetails"):
            detail = result["exceptionDetails"]
            text = detail.get("text") or detail.get("exception", {}).get("description") or "JS error"
            raise RuntimeError(text)
        return (result.get("result") or {}).get("value")

    async def goto(self, url: str, wait_ms: int = 750) -> None:
        assert self._cdp
        await self._cdp.call("Page.navigate", {"url": url})
        # Best-effort wait for load event + settle time
        await asyncio.sleep(max(0.2, wait_ms / 1000.0))
        try:
            self._title = str(await self.evaluate("document.title") or "")
        except Exception:
            self._title = ""
        try:
            self._url = str(await self.evaluate("location.href") or url)
        except Exception:
            self._url = url

    async def inject_ha_auth(self, cfg: dict | None = None) -> None:
        if self.authenticated_ha:
            return
        b = _browser_cfg(cfg)
        token = str(b.get("access_token") or "").strip()
        if not token:
            token = os.environ.get("SUPERVISOR_TOKEN", "").strip()
        if not token:
            return
        ha_url = _ha_base_url(cfg)
        expires = int(time.time() * 1000) + 10 * 365 * 24 * 3600 * 1000
        try:
            await self.goto(ha_url + "/", wait_ms=500)
            payload = json.dumps({
                "hassUrl": ha_url,
                "access_token": token,
                "token_type": "Bearer",
                "expires": expires,
                "refresh_token": "",
                "clientId": ha_url + "/",
            })
            await self.evaluate(
                f"localStorage.setItem('hassTokens', {json.dumps(payload)});"
            )
            self.authenticated_ha = True
        except Exception as exc:
            log.warning("HA auth inject failed: %s", exc)

    async def click(self, selector: str) -> None:
        sel = json.dumps(selector)
        ok = await self.evaluate(
            f"""(() => {{
              const el = document.querySelector({sel});
              if (!el) return false;
              el.scrollIntoView({{block: 'center', inline: 'center'}});
              el.click();
              return true;
            }})()"""
        )
        if not ok:
            raise RuntimeError(f"selector not found: {selector}")

    async def type_text(self, selector: str, text: str) -> None:
        sel = json.dumps(selector)
        val = json.dumps(text)
        ok = await self.evaluate(
            f"""(() => {{
              const el = document.querySelector({sel});
              if (!el) return false;
              el.focus();
              el.value = {val};
              el.dispatchEvent(new Event('input', {{bubbles: true}}));
              el.dispatchEvent(new Event('change', {{bubbles: true}}));
              return true;
            }})()"""
        )
        if not ok:
            raise RuntimeError(f"selector not found: {selector}")

    async def scroll(self, direction: str) -> None:
        if direction == "top":
            await self.evaluate("window.scrollTo(0, 0)")
        elif direction == "bottom":
            await self.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        elif direction == "up":
            await self.evaluate("window.scrollBy(0, -Math.floor(window.innerHeight * 0.8))")
        else:
            await self.evaluate("window.scrollBy(0, Math.floor(window.innerHeight * 0.8))")

    async def screenshot_png(self) -> bytes:
        assert self._cdp
        result = await self._cdp.call(
            "Page.captureScreenshot",
            {"format": "png", "fromSurface": True},
        )
        data = result.get("data") or ""
        return base64.b64decode(data)

    async def accessibility_summary(self, limit: int = 1200) -> str:
        try:
            items = await self.evaluate(
                """(() => {
                  const out = [];
                  const nodes = document.querySelectorAll('a,button,h1,h2,h3,input,textarea,[role="button"],[role="link"],[role="tab"]');
                  for (const el of nodes) {
                    const role = el.getAttribute('role') || el.tagName.toLowerCase();
                    const name = (el.innerText || el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.value || '').trim().slice(0, 80);
                    if (name) out.push(role + ': ' + name);
                    if (out.length >= 40) break;
                  }
                  return out;
                })()"""
            )
        except Exception:
            return ""
        if not isinstance(items, list):
            return ""
        text = "\n".join(str(x) for x in items)
        return text[:limit]


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
        await sess.ensure(cfg, viewport=viewport)
    except Exception as exc:
        return f"Error: could not start browser — {exc}"

    try:
        if action == "open":
            url = str(args.get("url") or "").strip()
            ok, reason = url_allowed(url, cfg)
            if not ok:
                return f"Error: {reason}"
            ha_base = _ha_base_url(cfg)
            host = (urlparse(url).hostname or "")
            if url.rstrip("/").startswith(ha_base.rstrip("/")) or "homeassistant" in host:
                await sess.inject_ha_auth(cfg)
            await sess.goto(url, wait_ms=wait_ms or 750)
            return (
                f"Opened {sess._url} (title: {sess._title or '—'}). "
                "Call action=screenshot to capture the page."
            )

        if action == "click":
            selector = str(args.get("selector") or "").strip()
            if not selector:
                return "Error: selector required for click"
            await sess.click(selector)
            await asyncio.sleep((wait_ms or 400) / 1000.0)
            return f"Clicked {selector}. Call action=screenshot to verify."

        if action == "type":
            selector = str(args.get("selector") or "").strip()
            text = str(args.get("text") or "")
            if not selector:
                return "Error: selector required for type"
            await sess.type_text(selector, text)
            return f"Typed into {selector}."

        if action == "scroll":
            direction = str(args.get("direction") or "down").lower()
            await sess.scroll(direction)
            await asyncio.sleep(0.3)
            return f"Scrolled {direction}."

        if wait_ms:
            await asyncio.sleep(wait_ms / 1000.0)
        png = _resize_png(await sess.screenshot_png())
        summary = await sess.accessibility_summary()
        from services import chat_media as cm

        att = cm.save_uploaded_file(
            user_id or "default",
            png,
            filename="browser-screenshot.png",
            content_type="image/png",
        )
        if generated_attachments is not None:
            generated_attachments.append(att)
        bits = [f"Screenshot of {sess._url}", f"title: {sess._title or '—'}"]
        if summary:
            bits.append("Visible controls:\n" + summary)
        bits.append("Image attached to the chat for visual review.")
        return "\n".join(bits)
    except Exception as exc:
        log.exception("browser_interact failed action=%s", action)
        return f"Error: browser {action} failed — {exc}"
