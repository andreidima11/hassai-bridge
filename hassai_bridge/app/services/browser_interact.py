"""Interactive headless browser for HASSAI (system Chromium + CDP).

Playwright has no musllinux wheels (HA Alpine base), so we drive Chromium
via the Chrome DevTools Protocol over websockets. Hosts on the Settings
allowlist (plus HA defaults) open immediately; others pause for Allow /
Decline in chat. Screenshots attach to chat like generated images.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import shutil
import socket
import tempfile
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
# session_id → hosts allowed for this chat (Approve without allowlist persist)
_session_hosts: dict[str, set[str]] = {}


def clear_session_hosts(session_id: str | None) -> None:
    sid = str(session_id or "").strip()
    if sid:
        _session_hosts.pop(sid, None)


def grant_session_host(session_id: str | None, host: str) -> None:
    sid = str(session_id or "").strip()
    h = _normalize_domain(host)
    if not sid or not h:
        return
    _session_hosts.setdefault(sid, set()).add(h)


def session_hosts(session_id: str | None) -> set[str]:
    sid = str(session_id or "").strip()
    if not sid:
        return set()
    return set(_session_hosts.get(sid) or ())


def host_from_url(url: str) -> str:
    try:
        return _normalize_domain(urlparse(str(url or "").strip()).hostname or "")
    except Exception:
        return ""


def host_preapproved(url: str, cfg: dict | None = None, session_id: str | None = None) -> bool:
    """True when host is on Settings allowlist, HA defaults, or session memory."""
    host = host_from_url(url)
    if not host:
        return False
    if host in session_hosts(session_id):
        return True
    return host in allowed_hosts(cfg)


def persist_host_to_allowlist(host: str) -> str:
    """Append host to Settings → browser.allowlist. Returns status text."""
    from config import load_config, save_config

    h = _normalize_domain(host)
    if not h:
        return "Error: empty host"
    cfg = load_config()
    browser = dict(cfg.get("browser") or {})
    allow = []
    seen: set[str] = set()
    for item in browser.get("allowlist") or []:
        n = _normalize_domain(item)
        if n and n not in seen:
            seen.add(n)
            allow.append(n)
    if h not in seen:
        allow.append(h)
        browser["allowlist"] = allow
        cfg["browser"] = browser
        save_config(cfg)
        return f"Added {h} to browser allowlist."
    return f"{h} is already on the browser allowlist."


def host_approval_preview(url: str) -> str:
    host = host_from_url(url) or "site"
    raw = str(url or "").strip()
    if len(raw) > 120:
        raw = raw[:119] + "…"
    return f"{host} · {raw}" if raw else host

TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "Open a web page in a headless browser, take screenshots, click, scroll, or type. "
            "Use to visually verify Home Assistant dashboards and other sites after changes. "
            "Requires Browser ON in Settings (or Approve to enable for this chat). "
            "Hosts not on the browser allowlist pause for Allow / Decline in the chat UI "
            "(optional: add to allowlist). Always screenshot after navigate/click."
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


def is_enabled(cfg: dict | None = None, session_id: str | None = None) -> bool:
    """True when browser tools may run (Settings and/or this-chat grant)."""
    if cfg is None:
        from config import load_config

        cfg = load_config()
    from services import tool_enable as te

    return te.effectively_enabled("bridge:browser", cfg, session_id)


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


def url_allowed(url: str, cfg: dict | None = None, session_id: str | None = None) -> tuple[bool, str]:
    """Validate scheme/path. Host trust is separate (``host_preapproved``)."""
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
    path = parsed.path or "/"
    for prefix in _SENSITIVE_PATH_PREFIXES:
        if path == prefix or path.startswith(prefix + "/"):
            return False, f"path '{path}' is blocked"
    _ = session_id
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


def _page_ws_url_from_targets(payload: Any) -> str | None:
    """Pick a page-target DevTools WebSocket (not the browser-level one).

    ``/json/version`` returns ``webSocketDebuggerUrl`` for the *browser* target.
    ``Page.*`` / ``Emulation.*`` only exist on page/tab targets from ``/json/list``.
    """
    if not isinstance(payload, list):
        return None
    pages: list[dict] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        ws = item.get("webSocketDebuggerUrl")
        if not ws:
            continue
        if item.get("type") in {"page", "webview"}:
            pages.append(item)
    # Prefer about:blank / the first page Chromium opened with our CLI args.
    for item in pages:
        url = str(item.get("url") or "")
        if url.startswith("about:"):
            return str(item["webSocketDebuggerUrl"])
    if pages:
        return str(pages[0]["webSocketDebuggerUrl"])
    return None


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
        self._stderr_buf = bytearray()
        self._stderr_task: asyncio.Task | None = None
        self._profile_dir: str | None = None
        self._ensure_lock = asyncio.Lock()

    async def ensure(self, cfg: dict | None = None, *, viewport: str = "desktop") -> None:
        async with self._ensure_lock:
            await self._ensure_locked(cfg, viewport=viewport)

    async def _ensure_locked(self, cfg: dict | None = None, *, viewport: str = "desktop") -> None:
        self.last_used = time.time()
        self._viewport = dict(_MOBILE_VIEWPORT if viewport == "mobile" else _DEFAULT_VIEWPORT)
        if self._cdp is not None and self._proc and self._proc.returncode is None:
            try:
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
            except Exception as exc:
                log.warning("Existing CDP session unusable (%s) — restarting Chromium", exc)
                await self.close()

        exe = _chromium_path()
        if not exe:
            raise RuntimeError(
                "Chromium binary not found. Rebuild the add-on image with Chromium packages."
            )

        self._port = _free_port()
        # Prefer modern headless; fall back if the Alpine Chromium build rejects it.
        headless_flags = ("--headless=new", "--headless")
        last_launch_err: Exception | None = None
        for headless in headless_flags:
            if self._profile_dir:
                shutil.rmtree(self._profile_dir, ignore_errors=True)
            self._profile_dir = tempfile.mkdtemp(prefix="hassai-chrome-")
            args = [
                exe,
                headless,
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--disable-crash-reporter",
                "--hide-scrollbars",
                "--mute-audio",
                f"--user-data-dir={self._profile_dir}",
                "--remote-debugging-address=127.0.0.1",
                f"--remote-debugging-port={self._port}",
                "--remote-allow-origins=*",
                "about:blank",
            ]
            self._stderr_buf = bytearray()
            self._proc = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            self._stderr_task = asyncio.create_task(self._drain_stderr())
            try:
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
                last_launch_err = None
                break
            except Exception as exc:
                last_launch_err = exc
                log.warning("Chromium launch with %s failed: %s", headless, exc)
                await self.close()
                self._port = _free_port()
        if last_launch_err is not None:
            raise last_launch_err

    async def _drain_stderr(self) -> None:
        proc = self._proc
        if not proc or not proc.stderr:
            return
        try:
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                self._stderr_buf.extend(chunk)
                if len(self._stderr_buf) > 8000:
                    del self._stderr_buf[:-4000]
        except Exception:
            pass

    def _stderr_tail(self) -> str:
        return bytes(self._stderr_buf).decode("utf-8", "replace")[-400:].strip()

    async def _wait_devtools(self, port: int, timeout: float = 20.0) -> str:
        deadline = time.time() + timeout
        last_err = ""
        async with httpx.AsyncClient(timeout=2.0) as client:
            while time.time() < deadline:
                if self._proc and self._proc.returncode is not None:
                    err_tail = self._stderr_tail()
                    raise RuntimeError(
                        f"Chromium exited early (code {self._proc.returncode})"
                        + (f": {err_tail}" if err_tail else "")
                    )
                try:
                    # Page/tab targets — required for Page.* / Emulation.*.
                    for path in ("/json/list", "/json"):
                        resp = await client.get(f"http://127.0.0.1:{port}{path}")
                        if resp.status_code != 200:
                            continue
                        ws = _page_ws_url_from_targets(resp.json())
                        if ws:
                            return ws
                    # No page yet — ask Chromium to open one.
                    for method in ("PUT", "GET"):
                        try:
                            resp = await client.request(
                                method,
                                f"http://127.0.0.1:{port}/json/new?about:blank",
                            )
                            if resp.status_code == 200:
                                data = resp.json()
                                if isinstance(data, dict) and data.get("webSocketDebuggerUrl"):
                                    return str(data["webSocketDebuggerUrl"])
                                ws = _page_ws_url_from_targets(
                                    data if isinstance(data, list) else [data]
                                )
                                if ws:
                                    return ws
                        except Exception as exc:
                            last_err = str(exc)
                except Exception as exc:
                    last_err = str(exc)
                await asyncio.sleep(0.15)
        raise RuntimeError(f"Chromium DevTools page target not ready: {last_err or 'timeout'}")

    async def close(self) -> None:
        if self._cdp:
            try:
                await self._cdp.close()
            except Exception:
                pass
            self._cdp = None
        if self._stderr_task:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except Exception:
                pass
            self._stderr_task = None
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
        self._stderr_buf = bytearray()
        self.authenticated_ha = False
        if self._profile_dir:
            shutil.rmtree(self._profile_dir, ignore_errors=True)
            self._profile_dir = None

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
        # Poll readyState — our CDP client ignores events, so no loadEventFired hook.
        deadline = time.time() + 15.0
        while time.time() < deadline:
            try:
                state = await self.evaluate("document.readyState")
                if state in {"interactive", "complete"}:
                    break
            except Exception:
                pass
            await asyncio.sleep(0.2)
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
    if not is_enabled(cfg, session_id):
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
            ok, reason = url_allowed(url, cfg, session_id)
            if not ok:
                return f"Error: {reason}"
            if not host_preapproved(url, cfg, session_id):
                host = host_from_url(url) or "site"
                return (
                    f"Error: host “{host}” is not approved. "
                    "The chat UI should have asked Allow / Decline first."
                )
            ha_base = _ha_base_url(cfg)
            host = (urlparse(url).hostname or "")
            if url.rstrip("/").startswith(ha_base.rstrip("/")) or "homeassistant" in host.lower():
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
