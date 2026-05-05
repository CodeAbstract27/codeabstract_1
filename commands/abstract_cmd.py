"""
CLI Command: abstract

Implements 'codeabstract abstract <file>' command.
Runs ABSTRACT(S, k) on the given Python source file.
"""

import typer
from pathlib import Path
from rich.progress import Progress, SpinnerColumn, TextColumn

from algorithms.abstract import abstract
from storage.session_manager import save_session
from utils.file_io import read_file, write_file
from utils.clipboard import copy_to_clipboard
from ui.console import get_console
from ui.formatters import (
    print_abstraction_stats,
    print_abstract_code,
    print_next_steps,
)


def run_abstract(
    file: str,
    privacy: str = "medium",
    context_window: int = 3,
    output: str = None,
    copy: bool = False,
    show_mapping: bool = False,
):
    """Execute the abstract command."""
    console = get_console()
    file_path = Path(file)

    if not file_path.exists():
        console.print(f"[error]✗ File not found: {file}[/error]")
        raise typer.Exit(1)

    if not file.endswith('.py'):
        console.print("[warning]⚠ Warning: File may not be Python source[/warning]")

    # Read source
    try:
        source_code = read_file(file_path)
    except Exception as e:
        console.print(f"[error]✗ Failed to read file: {e}[/error]")
        raise typer.Exit(1)

    # Run abstraction
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Running ABSTRACT(S, k)…", total=None)
        try:
            result = abstract(
                source_code=source_code,
                context_window=context_window,
                privacy_level=privacy,
            )
        except ValueError as e:
            console.print(f"\n[error]✗ Abstraction failed: {e}[/error]")
            raise typer.Exit(1)
        progress.update(task, description="✓ Abstraction complete")

    # Save session
    save_session(
        session_id=result.session_id,
        source_file_path=str(file_path.resolve()),
        context_window=context_window,
        encrypted_mapping=result.encrypted_mapping,
        encryption_key=result.encryption_key,
        statistics=result.statistics,
    )

    # Output
    console.print("\n[success]✓ Code abstracted successfully![/success]")
    console.print(f"[session_id]🔑 Session ID:[/session_id] {result.session_id}\n")

    if show_mapping:
        print_abstraction_stats(result.statistics)
        console.print()

    if copy:
        if copy_to_clipboard(result.abstract_code):
            console.print("[success]📋 Abstract code copied to clipboard[/success]")
        else:
            console.print("[warning]⚠ Could not copy to clipboard[/warning]")

    if output:
        try:
            write_file(Path(output), result.abstract_code)
            console.print(f"[success]💾 Saved to: {output}[/success]")
        except Exception as e:
            console.print(f"[error]✗ Failed to save: {e}[/error]")

    print_abstract_code(result.abstract_code)
    print_next_steps(result.session_id)
