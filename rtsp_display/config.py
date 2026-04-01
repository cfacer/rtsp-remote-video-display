"""Configuration loader with deep-merge defaults."""
import os
import logging
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
