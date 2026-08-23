"""
Application Configuration for CodeAbstract

Manages default settings, paths, and runtime configuration.
Configuration is stored in ~/.codeabstract/config.json.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional

# Single source of truth for the application version.  Phase 0 / D6:
# cli.py used ``from . import __version__``, which cannot work while ``cli``
# is a top-level module -- ``--version`` raised ImportError on every run.
__version__ = "1.0.0"

# ═══════════════════════════════════════════════════════════
# Default paths
# ═══════════════════════════════════════════════════════════

def get_app_dir() -> Path:
    """
    Get the application data directory (``~/.codeabstract``).

    ``CODEABSTRACT_HOME`` overrides it. Phase 4 added this because the
    directory now holds three things worth isolating rather than one:
    session keys, the audit log, and the session database. A test run — or
    a CI job, or a second profile — should not write keys into the user's
    real credential store or entries into their compliance record.
    """
    override = os.environ.get("CODEABSTRACT_HOME")
    app_dir = Path(override) if override else Path.home() / ".codeabstract"
    app_dir.mkdir(parents=True, exist_ok=True)
    return app_dir


def get_db_path() -> Path:
    """Get the path to the SQLite database."""
    return get_app_dir() / "sessions.db"


def get_config_path() -> Path:
    """Get the path to the config file."""
    return get_app_dir() / "config.json"


def get_audit_log_path() -> Path:
    """Get the path to the append-only audit log (Phase 4)."""
    return get_app_dir() / "audit.log"


def get_key_store_dir() -> Path:
    """Get the directory holding session keys when no OS keychain is usable."""
    return get_app_dir() / "keys"


# ═══════════════════════════════════════════════════════════
# Detector version
# ═══════════════════════════════════════════════════════════
# Phase 4: the audit log records which detector made the decisions in each
# run.  A hand-maintained version string drifts -- someone edits a pattern
# and forgets to bump it, and every entry after that misattributes its
# decisions.  Deriving the identifier from the detection rules themselves
# means it cannot be stale: change a pattern, and the fingerprint changes.

DETECTOR_GENERATION = "p4"


def detector_version() -> str:
    """
    Return an identifier for the current detection rules.

    Format: ``p4-<8 hex>``, where the hex digest covers the SECRET and
    VALUE pattern lists and the credential formats and entropy thresholds
    in :mod:`core.secret_detector`.

    Returns:
        A short, stable identifier that changes when detection changes.
    """
    from config.patterns import SECRET_PATTERNS, VALUE_PATTERNS
    from core import secret_detector

    parts = [
        DETECTOR_GENERATION,
        "\n".join(SECRET_PATTERNS),
        "\n".join(VALUE_PATTERNS),
        "\n".join(name for name, _ in secret_detector._CREDENTIAL_PATTERNS),
        "\n".join(
            str(getattr(secret_detector, const, ''))
            for const in sorted(dir(secret_detector))
            if const.isupper()
        ),
    ]
    digest = hashlib.sha256("\x00".join(parts).encode('utf-8')).hexdigest()
    return f"{DETECTOR_GENERATION}-{digest[:8]}"


# ═══════════════════════════════════════════════════════════
# Default configuration values
# ═══════════════════════════════════════════════════════════

DEFAULT_CONFIG: Dict[str, Any] = {
    "default_privacy": "high",
    "default_context_window": 3,
    "default_output_format": "text",
    "auto_copy": False,
    "show_mapping_stats": False,
    "theme": "monokai",
    "db_path": str(get_db_path()),
    # Phase 4 — platform settings.  Empty means "not chosen": provider
    # resolution falls through to whichever provider is actually ready.
    "default_provider": "",
    "gemini_model": "",
    "openai_model": "",
    "anthropic_model": "",
    "audit_log": True,
    # auto | keyring | file — see storage.key_store.  'auto' prefers the
    # OS keychain and falls back to a permission-restricted key directory.
    "key_backend": "auto",
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


def get_api_key(provider: str) -> Optional[str]:
    """
    Get stored API key for a provider from config.

    Looks up ``{provider}_api_key`` in the config file.
    For example, ``get_api_key('openai')`` returns the value
    stored under the key ``openai_api_key``.

    Args:
        provider: Provider name (openai, anthropic, gemini).

    Returns:
        The API key string, or None if not configured.
    """
    cfg = get_config()
    return cfg.get(f"{provider}_api_key")


def load_dotenv():
    """Load environment variables from a .env file if it exists."""
    search_paths = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[1] / ".env"
    ]
    for path in search_paths:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#"):
                            continue
                        if "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip()
                            # Strip quotes
                            if len(val) >= 2 and (
                                (val.startswith('"') and val.endswith('"')) or
                                (val.startswith("'") and val.endswith("'"))
                            ):
                                val = val[1:-1]
                            if key and key not in os.environ:
                                os.environ[key] = val
            except Exception:
                pass
            break


# Load environment variables on module import
load_dotenv()


