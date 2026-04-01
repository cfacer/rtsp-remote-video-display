"""Configuration loader with deep-merge defaults."""
import os
import logging
import re
import yaml

logger = logging.getLogger(__name__)

DEFAULTS: dict = {
    "device_id": "rtsp_display_1",
    "mqtt": {
        "host": "localhost",
        "port": 1883,
        "username": None,
        "password": None,
        "base_topic": "rtsp_display",
        "heartbeat_interval": 30,
    },
    "display": {
        "fullscreen": True,
        "background_color": "#0a0a0a",
        "accent_color": "#00d4ff",
    },
    "feeds": {
        "rtsp_transport": "tcp",
        "reconnect_delay": 5,
        "stall_timeout": 30,
        "ffplay_extra_args": [],
    },
    "presets": {},
}


def _load_env_file(path: str) -> dict:
    """Parse a .env file and return a dict of variable names to values.

    Supports:
      KEY=value
      KEY="value with spaces"
      KEY='value'
      # comments and blank lines ignored
    """
    env: dict = {}
    if not os.path.exists(path):
        return env
    with open(path, "r") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                value = value[1:-1]
            env[key] = value
    return env


def _interpolate(obj, env: dict):
    """Recursively replace ``${VAR}`` placeholders in all string values."""
    if isinstance(obj, str):
        def _sub(m):
            var = m.group(1)
            if var not in env:
                logger.warning("Config references undefined env var: %s", var)
            return env.get(var, m.group(0))
        return re.sub(r"\$\{([^}]+)\}", _sub, obj)
    if isinstance(obj, dict):
        return {k: _interpolate(v, env) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate(item, env) for item in obj]
    return obj


class Config:
    """Loads and merges YAML config over built-in defaults."""

    def __init__(self, path: str = "config.yaml") -> None:
        import copy

        self._data: dict = copy.deepcopy(DEFAULTS)
        if os.path.exists(path):
            with open(path, "r") as fh:
                user = yaml.safe_load(fh) or {}
            self._deep_merge(self._data, user)
            logger.info("Loaded config from %s", path)
        else:
            logger.warning("Config file %s not found — using defaults.", path)

        # Load .env from the same directory as config.yaml and interpolate
        env_path = os.path.join(os.path.dirname(os.path.abspath(path)), ".env")
        env = _load_env_file(env_path)
        if env:
            logger.info("Loaded %d credential(s) from %s", len(env), env_path)
        self._data = _interpolate(self._data, env)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def get(self, *keys, default=None):
        """Drill into nested dict keys. Returns *default* if any key is missing."""
        node = self._data
        for key in keys:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def __getitem__(self, key):
        return self._data[key]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _deep_merge(self, base: dict, override: dict) -> None:
        for key, val in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(val, dict):
                self._deep_merge(base[key], val)
            else:
                base[key] = val
