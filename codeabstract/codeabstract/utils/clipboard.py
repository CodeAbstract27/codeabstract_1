"""
Clipboard Operations

Provides a safe wrapper around pyperclip for copying
abstract code to the system clipboard.
"""

from typing import Optional


def copy_to_clipboard(text: str) -> bool:
    """
    Copy text to the system clipboard.

    Args:
        text: String to copy.

    Returns:
        True on success, False on failure.
    """
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False


def paste_from_clipboard() -> Optional[str]:
    """
    Paste text from the system clipboard.

    Returns:
        Clipboard contents, or None on failure.
    """
    try:
        import pyperclip
        return pyperclip.paste()
    except Exception:
        return None
