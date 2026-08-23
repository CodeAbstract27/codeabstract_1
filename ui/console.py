"""
Rich Console Setup

Provides a shared Rich console instance with a consistent
theme for all terminal output.
"""

import os
import sys

from rich.console import Console
from rich.theme import Theme

# ═══════════════════════════════════════════════════════════
# Custom theme for CodeAbstract
# ═══════════════════════════════════════════════════════════

CODEABSTRACT_THEME = Theme({
    "info": "white",
    "brand": "bold #d77757",
    "accent": "#d77757",
    "success": "bold green",
    "warning": "#ffb74d",
    "error": "bold red",
    "highlight": "bold #d77757",
    "muted": "grey50",
    "header": "bold #d77757",
    "session_id": "bold #d77757",
    "secret": "bold red",
    "value": "#d77757",
    "identifier": "bold white",
})

def ensure_utf8_stdout() -> None:
    """
    Force UTF-8 output on Windows to avoid charmap encoding errors.

    Phase 0 / D6: the evaluation runner builds its own Rich console and so
    never imported this module, which is why writing the final "✓ report
    saved" lines crashed with ``UnicodeEncodeError`` on a cp1252 console —
    after the reports had already been written, making the failure look
    worse than it was.  Any entry point that prints non-ASCII should call
    this first.

    Safe to call repeatedly and on non-Windows platforms, where it is a
    no-op.
    """
    if sys.platform != "win32":
        return

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


ensure_utf8_stdout()

# Shared console singleton — force_terminal=True enables ANSI on Windows
console = Console(theme=CODEABSTRACT_THEME, force_terminal=True, safe_box=True)


def get_console() -> Console:
    """Return the shared Rich console instance."""
    return console

