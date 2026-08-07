"""
Unit tests for utils/validators.py

Tests session ID format validation and Python file path verification.
"""

from pathlib import Path
import pytest
from utils.validators import validate_session_id, validate_python_file


def test_validate_session_id_full_uuid():
    """TC-VAL-01: Full 36-character UUID string should return the cleaned session string."""
    valid_uuid = "123e4567-e89b-12d3-a456-426614174000"
    assert validate_session_id(valid_uuid) == valid_uuid


def test_validate_session_id_prefix():
    """TC-VAL-02: Short valid hex prefix (>=4 chars) should return the cleaned session string."""
    assert validate_session_id("123e") == "123e"
    assert validate_session_id("a1b2c3d4") == "a1b2c3d4"


def test_validate_session_id_invalid_format():
    """TC-VAL-03: Invalid formats or short strings (<4 chars) should raise ValueError."""
    with pytest.raises(ValueError, match="Session ID must be at least 4 characters"):
        validate_session_id("abc")

    with pytest.raises(ValueError, match="Session ID must be at least 4 characters"):
        validate_session_id("")


def test_validate_python_file_success(tmp_path):
    """TC-VAL-04: Existing file should return Path object."""
    py_file = tmp_path / "sample.py"
    py_file.write_text("x = 10", encoding="utf-8")

    result = validate_python_file(py_file)
    assert isinstance(result, Path)
    assert result == py_file


def test_validate_python_file_non_existent():
    """TC-VAL-05: Non-existent file path should raise FileNotFoundError."""
    non_existent = Path("non_existent_file.py")
    with pytest.raises(FileNotFoundError, match="File not found"):
        validate_python_file(non_existent)
