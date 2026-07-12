"""
CLI Command: stats

Displays aggregate usage statistics across all sessions.
"""

from rich.panel import Panel

from storage.session_manager import get_stats_summary
from ui.console import get_console


def run_stats():
    """Display usage statistics."""
    console = get_console()
    stats = get_stats_summary()

    content = (
        f"[info]Total sessions:[/info]       {stats['total_sessions']}\n"
        f"[info]Earliest session:[/info]     {stats['earliest_session'] or '—'}\n"
        f"[info]Latest session:[/info]       {stats['latest_session'] or '—'}\n"
        f"[secret]Total secrets found:[/secret]  {stats['total_secrets_found']}\n"
        f"[value]Total values found:[/value]   {stats['total_values_found']}\n"
        f"[success]Total abstractions:[/success]  {stats['total_abstractions']}"
    )

    from rich.box import ROUNDED
    panel = Panel(
        content,
        title="[header]CodeAbstract Usage Statistics[/header]",
        border_style="#d77757",
        box=ROUNDED,
        expand=False,
    )
    console.print(panel)
