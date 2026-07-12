"""
CLI Command: interactive

Guided workflow using questionary prompts.
Walks the user through: select file → abstract → copy → paste LLM response → translate.
"""

import typer
from pathlib import Path

from algorithms.abstract import abstract
from algorithms.reconstruct import reconstruct
from storage.session_manager import save_session, list_sessions
from utils.file_io import read_file
from utils.clipboard import copy_to_clipboard
from ui.console import get_console
from ui.formatters import (
    print_abstraction_stats, print_abstract_code,
)
from ui import prompts


def run_interactive():
    """Run the interactive guided workflow."""
    from rich.box import ROUNDED
    from rich.panel import Panel
    console = get_console()

    console.print()
    console.print(Panel(
        "[bold #d77757]CodeAbstract[/bold #d77757] — secure, privacy-preserving LLM code assistant\n"
        "[dim]Guided interactive workflow[/dim]",
        border_style="#d77757",
        box=ROUNDED,
        expand=False,
    ))
    console.print()

    # Step 1: Get file path
    file_path = prompts.ask_file_path()
    if not file_path:
        console.print("[error]✗ No file selected.[/error]")
        raise typer.Exit(1)

    p = Path(file_path)
    if not p.exists():
        console.print(f"[error]✗ File not found: {file_path}[/error]")
        raise typer.Exit(1)

    # Step 2: Privacy level
    privacy = prompts.ask_privacy_level()

    # Step 3: Context window
    ctx_window = prompts.ask_context_window()

    # Step 4: Read and abstract
    console.print("\n[info]Reading source file…[/info]")
    try:
        source_code = read_file(p)
    except Exception as e:
        console.print(f"[error]✗ {e}[/error]")
        raise typer.Exit(1)

    with console.status("[bold green]Running ABSTRACT(S, k)…"):
        try:
            result = abstract(source_code, ctx_window, privacy)
        except ValueError as e:
            console.print(f"[error]✗ {e}[/error]")
            raise typer.Exit(1)

    # Save session
    save_session(
        session_id=result.session_id,
        source_file_path=str(p.resolve()),
        context_window=ctx_window,
        encrypted_mapping=result.encrypted_mapping,
        encryption_key=result.encryption_key,
        statistics=result.statistics,
    )

    console.print("[success]✓ Abstraction complete![/success]\n")
    print_abstraction_stats(result.statistics)
    print_abstract_code(result.abstract_code)

    # Step 5: Copy to clipboard
    should_copy = prompts.ask_copy_to_clipboard()
    if should_copy:
        if copy_to_clipboard(result.abstract_code):
            console.print("[success]📋 Copied to clipboard![/success]")
        else:
            console.print("[warning]⚠ Clipboard unavailable[/warning]")

    # Step 6: Wait for LLM response
    console.print("\n[bold cyan]Now paste the abstract code into your LLM.[/bold cyan]")
    console.print("[bold cyan]When you have the response, paste it below.[/bold cyan]\n")

    llm_response = prompts.ask_llm_response()
    if not llm_response:
        console.print("[info]No response provided. Session saved.[/info]")
        console.print(f"[info]Session: {result.session_id[:8]}[/info]")
        return

    # Handle file: prefix
    if llm_response.strip().startswith("file:"):
        resp_path = llm_response.strip()[5:]
        try:
            llm_response = read_file(Path(resp_path))
        except Exception as e:
            console.print(f"[error]✗ {e}[/error]")
            raise typer.Exit(1)

    # Step 7: Translate
    with console.status("[bold green]Running RECONSTRUCT(R, M̃, K)…"):
        translated = reconstruct(
            llm_response, result.encrypted_mapping, result.encryption_key,
        )

    console.print("\n[success]✓ Translation complete![/success]\n")
    from rich.box import ROUNDED
    from rich.panel import Panel
    panel = Panel(translated, title="Translated Feedback", border_style="#d77757", box=ROUNDED, expand=False)
    console.print(panel)
