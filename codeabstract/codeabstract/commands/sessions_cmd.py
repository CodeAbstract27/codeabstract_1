"""
CLI Command: sessions

Implements session management sub-commands:
list, show, delete, export.
"""

import typer
from rich.panel import Panel

from codeabstract.storage.session_manager import (
    list_sessions, load_session, delete_session,
)
from codeabstract.storage.mapping_store import export_session_data
from codeabstract.utils.file_io import write_file
from codeabstract.ui.console import get_console
from codeabstract.ui.formatters import print_session_table, print_abstraction_stats

from pathlib import Path


def run_sessions_list(limit: int = 20):
    """List recent sessions."""
    console = get_console()
    sessions = list_sessions(limit=limit)
    if not sessions:
        console.print("[info]No sessions found.[/info]")
        return
    print_session_table(sessions)


def run_sessions_show(session_id: str):
    """Show details of a specific session."""
    console = get_console()
    try:
        session = load_session(session_id)
    except Exception as e:
        console.print(f"[error]✗ {e}[/error]")
        raise typer.Exit(1)

    content = (
        f"[session_id]Session ID:[/session_id]  {session['session_id']}\n"
        f"[info]Source file:[/info]  {session['source_file_path']}\n"
        f"[info]Created:[/info]      {session['created_at']}\n"
        f"[info]Context window:[/info] {session['context_window']}"
    )
    panel = Panel(content, title="Session Details", border_style="cyan")
    console.print(panel)
    console.print()
    print_abstraction_stats(session.get('statistics', {}))


def run_sessions_delete(session_id: str, force: bool = False):
    """Delete a session."""
    console = get_console()
    if not force:
        console.print(f"[warning]⚠ About to delete session {session_id}[/warning]")
        confirm = typer.confirm("Are you sure?")
        if not confirm:
            console.print("[info]Cancelled.[/info]")
            return

    try:
        deleted = delete_session(session_id)
    except Exception as e:
        console.print(f"[error]✗ {e}[/error]")
        raise typer.Exit(1)

    if deleted:
        console.print(f"[success]✓ Session deleted.[/success]")
    else:
        console.print(f"[warning]Session not found: {session_id}[/warning]")


def run_sessions_export(session_id: str, output: str):
    """Export session metadata to a file."""
    console = get_console()
    try:
        session = load_session(session_id)
    except Exception as e:
        console.print(f"[error]✗ {e}[/error]")
        raise typer.Exit(1)

    data = export_session_data(session)
    try:
        write_file(Path(output), data)
        console.print(f"[success]✓ Exported to: {output}[/success]")
    except Exception as e:
        console.print(f"[error]✗ Failed to export: {e}[/error]")
