import hashlib
import json
import os
import time
import uuid
from pathlib import Path

# Single source of truth: /VERSION (no leading "v")
_VERSION_FILE = Path(__file__).parent.parent / "VERSION"
_raw = _VERSION_FILE.read_text(encoding="utf-8").strip() if _VERSION_FILE.exists() else "0.0.0-dev"
VERSION = _raw if _raw.startswith("v") else f"v{_raw}"
ADDON_VERSION = _raw.lstrip("v")  # HA add-on config.yaml version field
DB_SCHEMA_VERSION = 7


def _static_build_id() -> str:
    """VERSION + hash of UI files — query-string cache buster for Ingress."""
    root = Path(__file__).parent.parent / "static"
    h = hashlib.sha256()
    files = [
        "index.html",
        "settings.html",
        "css/style.css",
        "js/app.js",
        "js/i18n.js",
    ]
    assets = root / "assets" / "chat"
    if assets.is_dir():
        files.extend(
            str(p.relative_to(root))
            for p in sorted(assets.rglob("*"))
            if p.is_file()
        )
    for name in files:
        path = root / name
        if path.is_file():
            h.update(name.encode())
            h.update(path.read_bytes())
    return f"{ADDON_VERSION}.{h.hexdigest()[:12]}"


BUILD_ID = _static_build_id()

DATA_DIR = Path(os.environ.get("HASSAI_DATA_DIR") or (Path(__file__).parent.parent / "data"))
CONFIG_FILE = DATA_DIR / "config.json"

# ── In-memory config cache (debounced mtime check #12) ──
_config_cache: dict | None = None
_config_mtime: float = 0.0
_config_last_check: float = 0.0
_CONFIG_CHECK_INTERVAL = 1.0  # seconds — don't stat() more often than this


def _generate_api_key() -> str:
    return f"hab_{uuid.uuid4().hex}"


DEFAULT_CONFIG = {
    "api_key": "",
    "active_provider": "",
    "providers": [],
    "secondary_providers": [],
    "lmstudio": {
        "base_url": "http://localhost:1234",
        "model": "default",
        "timeout": 120,
        "max_tokens": 2048,
        "temperature": 0.7,
    },
    "searxng": {
        "enabled": False,
        "base_url": "http://localhost:8080",
        "max_results": 5,
        "max_searches_per_prompt": 2,
        "max_fetches_per_prompt": 2,
        "max_page_chars": 4000,
        "search_timeout": 15,
        "fetch_page_content": False,
        "max_pages_to_fetch": 0,
        "min_fetch_interval_ms": 2000,
        "min_search_interval_ms": 1500,
        "cache_ttl": 300,
    },
    "frigate": {
        "enabled": True,
        "base_url": "http://ccab4aaf-frigate:5000",
        "timeout": 12,
    },
    "voice": {
        "enabled": False,
        "provider": "google",
        "google_api_key": "",
        "language": "ro-RO",
        "voice": "Kore",
        "speaking_rate": 1.0,
        "autoplay": True,
        "max_reply_chars": 800,
        # Chat UI: both | mic | conversation
        "controls": "both",
        # Speech engines are picked separately, so Whisper can feed a Google
        # voice (or the other way around): google | local
        "stt_engine": "google",
        "tts_engine": "google",
        # Wyoming host:port (Home Assistant Whisper/Piper add-ons) or an
        # http(s) OpenAI-compatible speech server.
        "local_stt": {"url": "core_whisper:10300", "model": "", "timeout": 60},
        "local_tts": {"url": "core_piper:10200", "voice": "", "speaker": "", "model": "", "timeout": 60},
    },
    "memory": {
        "enabled": True,
        "auto_extract": True,
        "max_memories_per_user": 500,
        "extract_prompt": "",
        "auto_consolidation": {
            "enabled": False,
            "schedule": "daily",  # daily | weekly | interval
            "hour": 3,
            "interval_hours": 6,
            "last_run_at": 0,
        },
    },
    "performance": {
        "history_limit": 10,
        "local_history_limit": 6,
        "parallel_page_fetch": False,
        "agent_max_rounds": 16,
        "tool_profile": "auto",
        "tool_replay_turns": 0,
    },
    "skills_disabled": [],
    "routing": {
        "mode": "manual",
        "profile": "balanced",
        "sticky_session": True,
        "roles": {"fast": "", "deep": "", "vision": "", "fallback": ""},
    },
    "knowledge_cutoff": "2024-01",
    "language": "en",
    "dynamic_greetings": True,
    "greetings": {
        "refresh_days": 7,
        "pool_size": 40,
        "provider_id": "",
        "model": "",
        "prompt_template": "",
        "last_generated_at": 0,
        "last_season_key": "",
        "status": "idle",
        "error": "",
    },
    "users": {
        "default_user": "",
        "api_keys": {},
        "profiles": {},
    },
    "system_prompt": (
        "You are HASSAI, an autonomous Home Assistant copilot running as the HASSAI Bridge add-on.\n\n"
        "Scope\n"
        "- Do not suggest smart home actions, automations, or device changes unless the user explicitly asked.\n"
        "- For casual chat or general questions, answer normally — do not volunteer home control.\n\n"
        "Execution\n"
        "- When a task needs it, use tools to inspect and change the home, this add-on, and long-term memory.\n"
        "- Chain tool calls until the job is fully done; do not stop after a single lookup.\n"
        "- Tool narration and reasoning stay internal — the user should not see step-by-step "
        "“let me check…” unless they asked for an explanation.\n\n"
        "Memory\n"
        "- When memory context about the user is attached to the message, use it to personalize naturally.\n"
        "- Do not quote or list memories unless the user asks what you remember.\n\n"
        "Responses\n"
        "- Match the user's language (Romanian or English).\n"
        "- After a successful home command, reply with one short confirmation only, e.g. "
        "“Am aprins lumina din living.” / “I turned on the living room light.” — no extra tips, "
        "no follow-up suggestions, no smart-home ideas unless asked.\n"
        "- For read-only questions (status, explain, list), answer clearly in plain language; "
        "keep it as short as reasonable.\n\n"
        "Tone: direct, helpful, concise."
    ),
    "ha_agent_prompt": "",
    "bridge_tools": {
        "memory": True,
        "status": True,
        "control": True,
        "media": True,
    },
    "ha_tools": {
        "entities": True,
        "control": True,
        "registry": True,
        "automations": True,
        "integrations": True,
        "calendar": True,
        "helpers": True,
        "dashboards": True,
        "config_files": True,
        "custom_code": False,
        "diagnostics": True,
        "backups": True,
        "addons": True,
        "updates": True,
        "restart": True,
        "network": True,
        "upload": True,
        "zigbee": True,
        "hacs": True,
    },
}


def load_config() -> dict:
    global _config_cache, _config_mtime, _config_last_check
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Debounced: skip stat() if checked recently (#12)
    now = time.time()
    if _config_cache is not None and (now - _config_last_check) < _CONFIG_CHECK_INTERVAL:
        return _config_cache

    _config_last_check = now

    # Return cache if file hasn't changed
    if _config_cache is not None and CONFIG_FILE.exists():
        mtime = CONFIG_FILE.stat().st_mtime
        if mtime == _config_mtime:
            return _config_cache

    if CONFIG_FILE.exists():
        mtime = CONFIG_FILE.stat().st_mtime
        with open(CONFIG_FILE, "r") as f:
            saved = json.load(f)
        cfg = _deep_merge(DEFAULT_CONFIG, saved)
    else:
        cfg = _deep_merge(DEFAULT_CONFIG, {})
        mtime = 0.0

    # Apply environment variable overrides
    _apply_env_overrides(cfg)

    # Auto-generate API key if missing
    if not cfg.get("api_key"):
        cfg["api_key"] = _generate_api_key()
        save_config(cfg)
        return cfg  # save_config updates cache

    # Migrate: if old lmstudio config exists but no providers, create one
    if not cfg.get("providers") and cfg.get("lmstudio", {}).get("base_url"):
        lm = cfg["lmstudio"]
        cfg["providers"] = [{
            "id": "local_default",
            "name": "LM Studio",
            "type": "local",
            "base_url": lm.get("base_url", "http://localhost:1234"),
            "api_key": "",
            "model": lm.get("model", "default"),
            "timeout": lm.get("timeout", 120),
            "max_tokens": lm.get("max_tokens", 2048),
            "temperature": lm.get("temperature", 0.7),
        }]
        cfg["active_provider"] = "local_default"
        save_config(cfg)
        return cfg

    _config_cache = cfg
    _config_mtime = mtime
    return cfg


def _apply_env_overrides(cfg: dict):
    """Override config values with environment variables (HASSAI_ prefix)."""
    env_map = {
        "HASSAI_API_KEY": ("api_key",),
        "HASSAI_PORT": ("port",),
        "HASSAI_LMSTUDIO_URL": ("lmstudio", "base_url"),
        "HASSAI_LMSTUDIO_MODEL": ("lmstudio", "model"),
        "HASSAI_LMSTUDIO_TIMEOUT": ("lmstudio", "timeout"),
        "HASSAI_LMSTUDIO_MAX_TOKENS": ("lmstudio", "max_tokens"),
        "HASSAI_SEARXNG_ENABLED": ("searxng", "enabled"),
        "HASSAI_SEARXNG_URL": ("searxng", "base_url"),
        "HASSAI_MEMORY_ENABLED": ("memory", "enabled"),
        "HASSAI_VOICE_ENABLED": ("voice", "enabled"),
        "HASSAI_GOOGLE_VOICE_KEY": ("voice", "google_api_key"),
        "HASSAI_SYSTEM_PROMPT": ("system_prompt",),
        "HASSAI_KNOWLEDGE_CUTOFF": ("knowledge_cutoff",),
    }
    for env_var, path in env_map.items():
        val = os.environ.get(env_var)
        if val is None:
            continue
        # Navigate to nested key
        target = cfg
        for key in path[:-1]:
            target = target.setdefault(key, {})
        final_key = path[-1]
        # Type coercion based on existing value type
        existing = target.get(final_key)
        if isinstance(existing, bool):
            target[final_key] = val.lower() in ("true", "1", "yes")
        elif isinstance(existing, int):
            try:
                target[final_key] = int(val)
            except ValueError:
                pass
        elif isinstance(existing, float):
            try:
                target[final_key] = float(val)
            except ValueError:
                pass
        else:
            target[final_key] = val


def save_config(config: dict):
    global _config_cache, _config_mtime
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
    # Restrict file permissions (owner-only read/write)
    try:
        os.chmod(CONFIG_FILE, 0o600)
    except OSError:
        pass  # Windows or permission issue
    _config_cache = config
    _config_mtime = CONFIG_FILE.stat().st_mtime


def _deep_merge(defaults: dict, overrides: dict) -> dict:
    result = dict(defaults)
    for k, v in overrides.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result