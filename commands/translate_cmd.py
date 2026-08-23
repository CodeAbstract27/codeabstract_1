"""
CLI Command: translate

Implements 'codeabstract translate <session-id>' command.
Runs RECONSTRUCT(R, M̃, K) on an LLM response.
"""

import typer
from pathlib import Path
from rich.panel import Panel

from algorithms.encrypt import decrypt_mapping, encrypt_mapping
from algorithms.reconstruct import reconstruct
from core.privacy_report import display_mapping
from storage.session_manager import load_session
from utils.file_io import read_file, write_file
from ui.console import get_console


def run_translate(
    session_id: str,
    text: str = None,
    file: str = None,
    output: str = None,
    format: str = "text",
    reveal: bool = False,
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
            # Reconstruct against the *masked* table, not the raw session
            # mapping. RECONSTRUCT's "Source Context" blocks include +/-k
            # lines of the *original* source per symbol, and the line that
            # bound a credential contains the credential -- so without
            # this, the terminal printed the live secret value regardless
            # of any flag, on every translate. Same fix, same reasoning,
            # as the web interface's `run_translate` (web/service.py).
            mapping_table = decrypt_mapping(
                session['encrypted_mapping'], session['encryption_key'],
            )
            view = display_mapping(mapping_table, reveal=reveal)
            encrypted_view, view_key = encrypt_mapping(view)

            translated = reconstruct(
                llm_response=llm_response,
                encrypted_mapping=encrypted_view,
                encryption_key=view_key,
                line_map=session.get('line_map'),
            )
        except Exception as e:
            console.print(f"\n[error]✗ Reconstruction failed: {e}[/error]")
            raise typer.Exit(1)

    console.print("[success]✓ Response translated successfully![/success]\n")
    if not reveal:
        console.print(
            "[info]Secret values are masked. Pass --reveal to show them "
            "in the terminal.[/info]\n"
        )

    if output:
        try:
            write_file(Path(output), translated)
            console.print(f"[success]💾 Saved to: {output}[/success]\n")
        except Exception as e:
            console.print(f"[error]✗ Failed to save: {e}[/error]\n")

    from rich.box import ROUNDED
    panel = Panel(
        translated,
        title="[bold]Translated Feedback[/bold]",
        title_align="left",
        border_style="#d77757",
        box=ROUNDED,
        expand=False,
    )
    console.print(panel)
