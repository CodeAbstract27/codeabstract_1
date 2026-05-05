"""
CLI Command: translate

Implements 'codeabstract translate <session-id>' command.
Runs RECONSTRUCT(R, M̃, K) on an LLM response.
"""

import typer
from pathlib import Path
from rich.panel import Panel

from algorithms.reconstruct import reconstruct
from storage.session_manager import load_session
from utils.file_io import read_file, write_file
from ui.console import get_console


def run_translate(
    session_id: str,
    text: str = None,
    file: str = None,
    output: str = None,
    format: str = "text",
):
    """Execute the translate command."""
    console = get_console()

    # Get LLM response text
    if not text and not file:
        console.print("[error]✗ Provide either text or --file[/error]")
        raise typer.Exit(1)

    if file:
        try:
            llm_response = read_file(Path(file))
        except Exception as e:
            console.print(f"[error]✗ Failed to read file: {e}[/error]")
            raise typer.Exit(1)
    else:
        llm_response = text

    # Load session
    try:
        session = load_session(session_id)
    except Exception as e:
        console.print(f"[error]✗ {e}[/error]")
        console.print("[info]💡 Check: codeabstract sessions list[/info]")
        raise typer.Exit(1)

    # Run reconstruction
    with console.status("[bold green]Running RECONSTRUCT(R, M̃, K)…"):
        try:
            translated = reconstruct(
                llm_response=llm_response,
                encrypted_mapping=session['encrypted_mapping'],
                encryption_key=session['encryption_key'],
            )
        except Exception as e:
            console.print(f"\n[error]✗ Reconstruction failed: {e}[/error]")
            raise typer.Exit(1)

    console.print("[success]✓ Response translated successfully![/success]\n")

    if output:
        try:
            write_file(Path(output), translated)
            console.print(f"[success]💾 Saved to: {output}[/success]\n")
        except Exception as e:
            console.print(f"[error]✗ Failed to save: {e}[/error]\n")

    panel = Panel(
        translated,
        title="[bold]Translated Feedback[/bold]",
        title_align="left",
        border_style="cyan",
        expand=False,
    )
    console.print(panel)
