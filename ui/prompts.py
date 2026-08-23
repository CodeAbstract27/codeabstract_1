"""
Interactive Prompts

Uses questionary to provide guided, interactive prompts
for the interactive command workflow.
"""

from pathlib import Path
from typing import Optional

import questionary
from questionary import Style

# ═══════════════════════════════════════════════════════════
# Custom prompt style
# ═══════════════════════════════════════════════════════════

PROMPT_STYLE = Style([
    ('qmark', 'fg:#d77757 bold'),       # Claude Orange question mark
    ('question', 'bold'),                # Bold question text
    ('answer', 'fg:#d77757 bold'),       # Orange answers
    ('pointer', 'fg:#d77757 bold'),      # Orange selection pointer
    ('highlighted', 'fg:#ffffff bold bg:#d77757'),  # White text on Orange background
    ('selected', 'fg:#d77757'),          # Orange selected option
    ('separator', 'fg:#d77757'),         # Orange separator
    ('instruction', 'fg:#808080'),       # Grey instructions
])


def ask_file_path() -> Optional[str]:
    """Prompt the user for a Python source file path."""
    result = questionary.path(
        "Path to Python source file:",
        style=PROMPT_STYLE,
        only_directories=False,
    ).ask()
    return result


def ask_privacy_level() -> str:
    """Prompt the user to select a privacy level."""
    choices = [
        questionary.Choice("Low — Only secrets (API keys, passwords)", value="low"),
        questionary.Choice("Medium — Secrets + business values [recommended]", value="medium"),
        questionary.Choice("High — All identifiers abstracted", value="high"),
        questionary.Choice("Critical — Everything abstracted", value="critical"),
    ]
    result = questionary.select(
        "Select privacy level:",
        choices=choices,
        default=choices[1],
        style=PROMPT_STYLE,
    ).ask()
    return result or "medium"


def ask_context_window() -> int:
    """Prompt the user for the context window size."""
    result = questionary.text(
        "Context window size (±N lines, default 3):",
        default="3",
        style=PROMPT_STYLE,
    ).ask()
    try:
        # A negative window flows straight into get_context()'s start/end
        # line arithmetic, which assumes k >= 0; it doesn't crash, but it
        # produces an inverted range and a silently empty context snippet.
        # The `abstract` CLI command enforces the same floor via `min=0`.
        return max(0, int(result))
    except (ValueError, TypeError):
        return 3


def ask_copy_to_clipboard() -> bool:
    """Ask whether to copy abstract code to clipboard."""
    result = questionary.confirm(
        "Copy abstract code to clipboard?",
        default=True,
        style=PROMPT_STYLE,
    ).ask()
    return result if result is not None else True


def ask_llm_response() -> Optional[str]:
    """Prompt the user to paste the LLM response."""
    result = questionary.text(
        "Paste the LLM's response (or type 'file:path' to read from file):",
        multiline=True,
        style=PROMPT_STYLE,
    ).ask()
    return result


def ask_session_id(sessions: list) -> Optional[str]:
    """Prompt the user to select a session."""
    if not sessions:
        return None

    choices = [
        questionary.Choice(
            f"{s['session_id'][:12]}… — {s.get('source_file_path', '?')} "
            f"({s.get('created_at', '?')})",
            value=s['session_id'],
        )
        for s in sessions
    ]

    result = questionary.select(
        "Select a session:",
        choices=choices,
        style=PROMPT_STYLE,
    ).ask()
    return result


def ask_confirm_delete(session_id: str) -> bool:
    """Confirm session deletion."""
    result = questionary.confirm(
        f"Delete session {session_id[:12]}…?",
        default=False,
        style=PROMPT_STYLE,
    ).ask()
    return result if result is not None else False
