import json
import os
import time
import uuid
from pathlib import Path

VERSION = "v0.1.8.2-beta"
DB_SCHEMA_VERSION = 2

DATA_DIR = Path(__file__).parent.parent / "data"
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
        "max_page_chars": 4000,
        "search_timeout": 15,
        "fetch_page_content": True,
        "max_pages_to_fetch": 2,
        "cache_ttl": 300,
    },
    "memory": {
        "enabled": True,
        "auto_extract": True,
        "max_memories_per_user": 500,
        "auto_consolidation": {
            "enabled": False,
            "schedule": "daily",
            "hour": 3,
        },
    },
    "performance": {
        "history_limit": 10,
        "parallel_page_fetch": True,
    },
    "skills_disabled": [],
    "knowledge_cutoff": "2024-01",
    "language": "en",
    "users": {
        "default_user": "",
        "api_keys": {},
    },
    "system_prompt": (
        "You are a helpful AI assistant integrated with Home Assistant. "
        "Answer questions clearly and concisely. When you have memory context "
        "about the user, use it to personalize your responses."
    ),
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