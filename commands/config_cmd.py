"""
CLI Command: config

Implements 'codeabstract config show|set' commands.
"""

import typer
from rich.panel import Panel
from rich.table import Table

from config.settings import get_config
from ui.console import get_console


def run_config_show():
    """Display current configuration."""
    console = get_console()
    cfg = get_config()

    from rich.box import ROUNDED
    table = Table(title="Configuration", border_style="dim", show_header=True, header_style="bold #d77757", box=ROUNDED)
    table.add_column("Key", style="white")
    table.add_column("Value", style="accent")

    for key, value in sorted(cfg.all().items()):
        table.add_row(key, str(value))

    console.print(table)


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
    console.print(f"[success]✓ Set {key} = {typed_value}[/success]")
