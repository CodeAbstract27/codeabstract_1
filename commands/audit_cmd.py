"""
CLI Command: audit

Phase 4. Reads the append-only audit log that every abstraction and every
outbound request writes to.

Three sub-commands, matching the three questions a compliance reviewer
actually asks: what has this tool sent, has the record been tampered with,
and can I have it as a file.
"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.box import MINIMAL, ROUNDED
from rich.panel import Panel
from rich.table import Table

from storage import audit_log
from ui.console import get_console
from utils.file_io import write_file


def run_audit_list(limit: int = 20, event: Optional[str] = None):
    """Show recent audit entries."""
    console = get_console()
    entries = audit_log.read_entries()

    if event:
        entries = [e for e in entries if e.get('event') == event]

    if not entries:
        console.print(
            f"[info]No audit entries yet.[/info]\n"
            f"[muted]Log: {audit_log.audit_log_path()}[/muted]"
        )
        return

    shown = entries[-limit:]

    table = Table(
        title=f"Audit log — {len(shown)} of {len(entries)} entries",
        show_header=True, header_style="bold #d77757",
        border_style="dim", box=ROUNDED,
    )
    table.add_column("#", justify="right", style="muted")
    table.add_column("When", style="muted", no_wrap=True)
    table.add_column("Event")
    table.add_column("File", style="white")
    table.add_column("Level")
    table.add_column("Provider / model", style="accent")
    table.add_column("Tokens", justify="right")

    for entry in shown:
        tokens = entry.get('tokens') or {}
        if tokens.get('reported'):
            token_cell = f"{tokens.get('total_tokens', 0)}"
        elif entry.get('event') == 'request':
            token_cell = "not reported"
        else:
            token_cell = "—"

        provider = entry.get('provider')
        model = entry.get('model')
        provider_cell = f"{provider}/{model}" if provider else "—"

        source = entry.get('source_file', '—')
        table.add_row(
            str(entry.get('seq', '?')),
            str(entry.get('timestamp', '—')).replace('T', ' ').replace('+00:00', 'Z'),
            str(entry.get('event', '—')),
            Path(source).name if source != '—' else '—',
            str(entry.get('privacy_level', '—')),
            provider_cell,
            token_cell,
        )

    console.print(table)
    console.print(f"[muted]{audit_log.audit_log_path()}[/muted]")


def run_audit_verify():
    """Check the hash chain."""
    console = get_console()
    verification = audit_log.verify_chain()

    if verification.entries == 0:
        console.print("[info]No audit entries to verify.[/info]")
        return

    if verification.ok:
        console.print(Panel(
            f"[success]✓ {verification.summary()}[/success]\n"
            f"[muted]Every entry hashes to its recorded value and links to "
            f"the one before it.[/muted]",
            title="[header]Audit chain[/header]",
            border_style="green", box=ROUNDED, expand=False,
        ))
        return

    console.print(Panel(
        "\n".join(f"[error]✗ {problem}[/error]" for problem in verification.problems),
        title=f"[error]Audit chain — {verification.summary()}[/error]",
        border_style="red", box=ROUNDED, expand=False,
    ))
    console.print(
        "[muted]The chain detects edits and deletions, not a wholesale "
        "rewrite by someone with write access — see storage/audit_log.py.[/muted]"
    )
    raise typer.Exit(1)


def run_audit_export(output: str, format: str = "json"):
    """Write the log to a file as JSON or CSV."""
    console = get_console()
    entries = audit_log.read_entries()

    if not entries:
        console.print("[warning]Nothing to export — the audit log is empty.[/warning]")
        raise typer.Exit(1)

    if format == "csv":
        columns = [
            'seq', 'timestamp', 'event', 'source_file', 'language',
            'privacy_level', 'provider', 'model', 'task', 'free_form_query',
            'payload_sha256', 'success', 'detector_version', 'tool_version',
        ]
        rows = [",".join(columns)]
        for entry in entries:
            values = []
            for column in columns:
                value = entry.get(column, '')
                text = '' if value is None else str(value)
                needs_quoting = any(c in text for c in (',', '"', '\n', '\r'))
                if needs_quoting:
                    text = f'"{text.replace(chr(34), chr(34) * 2)}"'
                values.append(text)
            rows.append(",".join(values))
        payload = "\n".join(rows) + "\n"
    else:
        payload = json.dumps(entries, indent=2, ensure_ascii=False)

    try:
        write_file(Path(output), payload)
    except Exception as exc:
        console.print(f"[error]✗ Failed to export: {exc}[/error]")
        raise typer.Exit(1)

    console.print(
        f"[success]✓ {len(entries)} entries exported to {output}[/success]"
    )


def run_audit_show(seq: int):
    """Show one entry in full."""
    console = get_console()
    for entry in audit_log.read_entries():
        if entry.get('seq') == seq:
            console.print(Panel(
                json.dumps(entry, indent=2, ensure_ascii=False),
                title=f"[header]Audit entry {seq}[/header]",
                border_style="#d77757", box=MINIMAL, expand=False,
            ))
            return

    console.print(f"[warning]No audit entry with sequence number {seq}.[/warning]")
    raise typer.Exit(1)
