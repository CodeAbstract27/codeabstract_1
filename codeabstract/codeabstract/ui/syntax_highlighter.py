"""
Syntax Highlighter

Provides Pygments-based syntax highlighting utilities
for displaying Python source code in the terminal.
"""

from pygments import highlight
from pygments.formatters import TerminalTrueColorFormatter
from pygments.lexers import PythonLexer


def highlight_python(code: str) -> str:
    """
    Apply Pygments syntax highlighting to Python code.

    Args:
        code: Python source code string.

    Returns:
        ANSI-colored string for terminal display.
    """
    lexer = PythonLexer()
    formatter = TerminalTrueColorFormatter(style='monokai')
    return highlight(code, lexer, formatter)
