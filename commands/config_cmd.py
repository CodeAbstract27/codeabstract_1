"""
CLI Command: config

Implements 'codeabstract config show|set' commands.

Stored API keys are masked on the way out. A tool whose entire premise is
that credentials do not leave the machine should not be the thing that
prints one: ``config show`` is what a user runs when something is wrong and
pastes into a bug report, and ``config set`` echoes into shell history and
CI logs. ``--reveal`` prints the value in full for the case where checking
a key character by character is the actual task.
"""

from typing import Optional

import typer
from rich.panel import Panel
from rich.table import Table

from config.settings import get_config
from core.privacy_report import mask_secret
from ui.console import get_console

# Config keys whose values are credentials. Matched as a substring so that
# a provider added later -- ``mistral_api_key`` -- is covered the day it is
# introduced rather than the day someone remembers to list it here.
SECRET_KEY_MARKERS = ('api_key', 'token', 'secret', 'password', 'credential')


def is_secret_key(key: str) -> bool:
    """True if *key* names a stored credential rather than a preference."""
    lowered = key.lower()
    return any(marker in lowered for marker in SECRET_KEY_MARKERS)


def display_value(key: str, value, reveal: bool = False) -> str:
    """Render one config value, masking it if it is a credential."""
    if not reveal and is_secret_key(key) and value not in (None, ''):
        return mask_secret(str(value))
    return str(value)


def run_config_show(reveal: bool = False):
    """Display current configuration."""
    console = get_console()
    cfg = get_config()

    from rich.box import ROUNDED
    table = Table(title="Configuration", border_style="dim", show_header=True, header_style="bold #d77757", box=ROUNDED)
    table.add_column("Key", style="white")
    table.add_column("Value", style="accent")

    masked_any = False
    for key, value in sorted(cfg.all().items()):
        rendered = display_value(key, value, reveal)
        if rendered != str(value):
            masked_any = True
        table.add_row(key, rendered)

    console.print(table)

    if masked_any:
        console.print(
            "[dim]Credentials are masked. Use "
            "[/dim][accent]config show --reveal[/accent][dim] to print them "
            "in full.[/dim]"
        )


def run_config_set(key: str, value: str):
    """Set a configuration value."""
    console = get_console()
    cfg = get_config()

    # Type coercion
    if value.lower() in ('true', 'false'):
        typed_value = value.lower() == 'true'
    elif value.isdigit():
        typed_value = int(value)
    else:
        typed_value = value

    cfg.set(key, typed_value)
    # Echo the masked form: confirming the key was stored does not require
    # reprinting it into the terminal's scrollback.
    console.print(
        f"[success]✓ Set {key} = {display_value(key, typed_value)}[/success]"
    )
