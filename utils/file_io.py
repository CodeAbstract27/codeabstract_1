"""
File I/O Utilities

Provides safe file read/write operations with encoding handling.
"""

from pathlib import Path


def read_file(file_path: Path) -> str:
    """Read a text file and return its contents."""
    file_path = Path(file_path)
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")
    if not file_path.is_file():
        raise IOError(f"Not a file: {file_path}")
    try:
        return file_path.read_text(encoding='utf-8')
    except UnicodeDecodeError:
        return file_path.read_text(encoding='latin-1')


def write_file(file_path: Path, content: str) -> None:
    """Write content to a text file, creating parent dirs as needed."""
    file_path = Path(file_path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(content, encoding='utf-8')
