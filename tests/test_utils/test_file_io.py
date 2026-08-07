"""
Unit tests for utils/file_io.py

Tests reading files, writing files, and error handling for missing files.
"""

from pathlib import Path
import pytest
from utils.file_io import read_file, write_file


def test_file_write_and_read_roundtrip(tmp_path):
    """TC-FIO-01: Writing and reading UTF-8 text file should return matching content."""
    target = tmp_path / "test_output.py"
    content = "# Safe abstract code\nFUNC_0 = 'CONST_0'"

    write_file(target, content)
    assert target.exists()

    read_back = read_file(target)
    assert read_back == content


def test_read_file_non_existent():
    """TC-FIO-02: Reading non-existent file should raise FileNotFoundError."""
    missing_path = Path("does_not_exist_file.txt")
    with pytest.raises(FileNotFoundError):
        read_file(missing_path)


def test_write_file_creates_parent_directories(tmp_path):
    """write_file should automatically create parent directories if they don't exist."""
    nested_path = tmp_path / "sub_dir" / "nested" / "output.txt"
    write_file(nested_path, "nested text")
    assert nested_path.exists()
    assert read_file(nested_path) == "nested text"
