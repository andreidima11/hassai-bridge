import json
import time
import uuid
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
CONFIG_FILE = DATA_DIR / "config.json"

# ── In-memory config cache ──
_config_cache: dict | None = None
_config_mtime: float = 0.0


def _generate_api_key() -> str:
    return f"hab_{uuid.uuid4().hex}"


DEFAULT_CONFIG = {
    "api_key": "",
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
    },
    "performance": {
        "history_limit": 10,
        "parallel_page_fetch": True,
    },
    "knowledge_cutoff": "2024-01",
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
    global _config_cache, _config_mtime
    DATA_DIR.mkdir(parents=True, exist_ok=True)

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

    # Auto-generate API key if missing
    if not cfg.get("api_key"):
        cfg["api_key"] = _generate_api_key()
        save_config(cfg)
        return cfg  # save_config updates cache

    _config_cache = cfg
    _config_mtime = mtime
    return cfg


def save_config(config: dict):
    global _config_cache, _config_mtime
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)
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