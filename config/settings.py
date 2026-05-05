"""
Application Configuration for CodeAbstract

Manages default settings, paths, and runtime configuration.
Configuration is stored in ~/.codeabstract/config.json.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# ═══════════════════════════════════════════════════════════
# Default paths
# ═══════════════════════════════════════════════════════════

def get_app_dir() -> Path:
    """Get the application data directory (~/.codeabstract)."""
    app_dir = Path.home() / ".codeabstract"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_db_path() -> Path:
    """Get the path to the SQLite database."""
    return get_app_dir() / "sessions.db"


def get_config_path() -> Path:
    """Get the path to the config file."""
    return get_app_dir() / "config.json"


# ═══════════════════════════════════════════════════════════
# Default configuration values
# ═══════════════════════════════════════════════════════════

DEFAULT_CONFIG: Dict[str, Any] = {
    "default_privacy": "medium",
    "default_context_window": 3,
    "default_output_format": "text",
    "auto_copy": False,
    "show_mapping_stats": False,
    "theme": "monokai",
    "db_path": str(get_db_path()),
}

# Privacy level definitions
PRIVACY_LEVELS = {
    "low": {
        "description": "Only SECRET patterns are abstracted",
        "abstract_secrets": True,
        "abstract_values": False,
        "abstract_identifiers": False,
        "abstract_short_names": False,
    },
    "medium": {
        "description": "SECRET and VALUE patterns are abstracted",
        "abstract_secrets": True,
        "abstract_values": True,
        "abstract_identifiers": False,
        "abstract_short_names": False,
    },
    "high": {
        "description": "All multi-character identifiers are abstracted",
        "abstract_secrets": True,
        "abstract_values": True,
        "abstract_identifiers": True,
        "abstract_short_names": False,
    },
    "critical": {
        "description": "Everything is abstracted including short names",
        "abstract_secrets": True,
        "abstract_values": True,
        "abstract_identifiers": True,
        "abstract_short_names": True,
    },
}


# ═══════════════════════════════════════════════════════════
# Configuration management
# ═══════════════════════════════════════════════════════════

class Config:
    """Application configuration manager."""

    def __init__(self):
        self._config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._load()

    def _load(self):
        """Load configuration from disk."""
        config_path = get_config_path()
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._config.update(saved)
            except (json.JSONDecodeError, IOError):
                pass  # Use defaults on parse error

    def save(self):
        """Persist configuration to disk."""
        config_path = get_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, indent=2)

    def get(self, key: str, default: Any = None) -> Any:
        """Get a configuration value."""
        return self._config.get(key, default)

    def set(self, key: str, value: Any):
        """Set a configuration value and persist."""
        self._config[key] = value
        self.save()

    def all(self) -> Dict[str, Any]:
        """Return all configuration values."""
        return dict(self._config)

    def reset(self):
        """Reset configuration to defaults."""
        self._config = dict(DEFAULT_CONFIG)
        self.save()


# Singleton instance
_config_instance: Optional[Config] = None


def get_config() -> Config:
    """Get the global configuration instance."""
    global _config_instance
    if _config_instance is None:
        _config_instance = Config()
    return _config_instance
