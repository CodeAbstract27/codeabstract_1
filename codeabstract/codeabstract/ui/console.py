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
    "info": "cyan",
    "success": "green bold",
    "warning": "yellow",
    "error": "red bold",
    "highlight": "magenta",
    "muted": "dim",
    "header": "bold cyan underline",
    "session_id": "bold blue",
    "secret": "bold red",
    "value": "bold yellow",
    "identifier": "bold white",
})

# Force UTF-8 output on Windows to avoid charmap encoding errors
if sys.platform == "win32":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

# Shared console singleton — force_terminal=True enables ANSI on Windows
console = Console(theme=CODEABSTRACT_THEME, force_terminal=True, safe_box=True)


def get_console() -> Console:
    """Return the shared Rich console instance."""
    return console

