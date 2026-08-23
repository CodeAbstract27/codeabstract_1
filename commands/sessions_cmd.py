"""
CLI Command: sessions

Implements session management sub-commands:
list, show, delete, export.
"""

import typer
from rich.panel import Panel

from storage.session_manager import (
    list_sessions, load_session, delete_session,
)
from storage.mapping_store import export_session_data
from utils.file_io import write_file
from ui.console import get_console
from ui.formatters import print_session_table, print_abstraction_stats

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
    from rich.box import ROUNDED
    panel = Panel(content, title="Session Details", border_style="#d77757", box=ROUNDED)
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


def run_sessions_migrate_keys(backend: str = None):
    """
    Move keys of pre-Phase-4 sessions out of the database (Phase 4).

    Sessions written before the key store existed hold their Fernet key in
    the same row as the ciphertext, which means the database file alone
    decrypts them.  This copies each key into the OS keychain (or the key
    directory) and blanks the column.

    Not automatic: rewriting a user's session database as a side effect of
    an unrelated command is how data gets lost quietly.
    """
    console = get_console()

    from storage.key_store import KeyStoreError, get_key_store, migrate_legacy_keys

    try:
        store = get_key_store(backend)
    except KeyStoreError as exc:
        console.print(f"[error]✗ {exc}[/error]")
        raise typer.Exit(1)

    console.print(f"[info]Migrating session keys to the '{store.backend}' store…[/info]")

    try:
        migrated, failures = migrate_legacy_keys(backend)
    except Exception as exc:
        console.print(f"[error]✗ Migration failed: {exc}[/error]")
        raise typer.Exit(1)

    if migrated:
        console.print(
            f"[success]✓ {migrated} session key(s) moved out of the database."
            f"[/success]"
        )
    else:
        console.print("[info]No sessions were holding a key in the database.[/info]")

    for failure in failures:
        console.print(f"[warning]⚠ {failure}[/warning]")

    if failures:
        raise typer.Exit(1)


def run_sessions_keys_status():
    """Report where session keys are stored (Phase 4)."""
    console = get_console()

    from storage.database import get_connection
    from storage.key_store import get_key_store, keyring_available

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT
              COUNT(*) AS total,
              SUM(CASE WHEN key_ref != '' THEN 1 ELSE 0 END) AS in_store,
              SUM(CASE WHEN LENGTH(encryption_key) > 0 THEN 1 ELSE 0 END) AS in_db
            FROM sessions
            """
        ).fetchone()
    finally:
        conn.close()

    total = rows['total'] or 0
    in_store = rows['in_store'] or 0
    in_db = rows['in_db'] or 0

    backend = get_key_store().backend
    console.print(
        f"[info]Sessions:[/info] {total}\n"
        f"[info]Keys in the key store:[/info] {in_store}\n"
        f"[info]Keys still in the database:[/info] {in_db}\n"
        f"[info]Active backend:[/info] {backend}"
        + ("" if keyring_available() else "  [warning](no OS keychain available)[/warning]")
    )

    if in_db:
        console.print(
            f"[warning]⚠ {in_db} session(s) can be decrypted from the database "
            f"alone. Run:[/warning] [accent]codeabstract sessions migrate-keys[/accent]"
        )
    elif total:
        console.print(
            "[success]✓ The database alone decrypts nothing — every key is "
            "in the key store.[/success]"
        )
