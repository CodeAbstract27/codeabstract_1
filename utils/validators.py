"""Input validation utilities."""

from pathlib import Path


def validate_python_file(file_path: str) -> Path:
    """Validate that a file exists and is a Python file."""
    p = Path(file_path)
    if not p.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not p.is_file():
        raise ValueError(f"Not a file: {file_path}")
    return p


def validate_session_id(session_id: str) -> str:
    """Validate session ID format (at least 4 hex chars)."""
    if not session_id or len(session_id) < 4:
        raise ValueError("Session ID must be at least 4 characters")
    return session_id.strip()


def validate_privacy_level(level: str) -> str:
    """Validate privacy level value."""
    valid = {"low", "medium", "high", "critical"}
    level = level.lower().strip()
    if level not in valid:
        raise ValueError(f"Invalid privacy level: {level}. Must be one of: {valid}")
    return level
