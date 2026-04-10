# Re-export from core.config for backward compatibility
from core.config import *  # noqa: F401,F403
from core.config import load_config, save_config, DEFAULT_CONFIG, DATA_DIR, CONFIG_FILE, _generate_api_key
