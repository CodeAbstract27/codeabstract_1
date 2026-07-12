import os
import typer
from pathlib import Path
from typing import Optional
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from algorithms.abstract import abstract
from algorithms.reconstruct import reconstruct
from llm import create_client
from utils.file_io import read_file, write_file
from ui.console import get_console
from config.settings import get_api_key

console = get_console()

def run_review(
    file: str,
    task: str = "review",
    output: Optional[str] = None,
    show_abstract: bool = False,
    api_key: Optional[str] = None,
    privacy: str = "high",
):
    # ── Get API key ──────────────────────────────────
    resolved_key = api_key or os.environ.get("GEMINI_API_KEY") or get_api_key("gemini")
    
    if not resolved_key:
        console.print("[red]✗ No Gemini API key found[/red]")
        console.print("[yellow]Set it: export GEMINI_API_KEY=your_key or in .env file[/yellow]")
        raise typer.Exit(1)


    file_path = Path(file)
    if not file_path.exists():
        console.print(f"[red]✗ File not found: {file}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold cyan]CodeAbstract Review[/bold cyan]\n"
        f"[dim]{file} → Gemini → Reconstructed[/dim]"
    ))

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console
    ) as progress:

        # Step 1: Read
        t = progress.add_task("[1/4] Reading file...", total=None)
        source_code = read_file(file_path)
        progress.update(t, description=f"[green]✓ File read[/green]")

        # Step 2: Abstract
        t = progress.add_task("[2/4] Abstracting code...", total=None)
        result = abstract(source_code=source_code, privacy_level=privacy)
        count = result.statistics['abstracted_nodes']
        progress.update(t, description=f"[green]✓ {count} identifiers abstracted[/green]")

        # Show abstract code if requested
        if show_abstract:
            progress.stop()
            console.print("\n[bold]Abstract code sent to Gemini:[/bold]")
            console.print("─" * 50)
            console.print(result.abstract_code)
            console.print("─" * 50 + "\n")
            progress.start()

        # Step 3: Send to Gemini
        t = progress.add_task("[3/4] Sending to Gemini...", total=None)
        client = create_client(api_key=resolved_key)
        llm_response = client.send(
            abstract_code=result.abstract_code,
            task=task
        )

        if not llm_response.success:
            console.print(f"\n[red]✗ Gemini error: {llm_response.error}[/red]")
            raise typer.Exit(1)

        progress.update(
            t,
            description=f"[green]✓ Gemini responded ({llm_response.response_time:.1f}s)[/green]"
        )

        # Step 4: Reconstruct
        t = progress.add_task("[4/4] Reconstructing...", total=None)
        final = reconstruct(
            llm_response=llm_response.content,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key
        )
        progress.update(t, description="[green]✓ Done[/green]")

    # ── Display result ───────────────────────────────
    console.print()
    console.print("─" * 60)
    console.print(f"[bold] RESULTS: {file}[/bold]")
    console.print("─" * 60)
    console.print(final)
    console.print("─" * 60)
    console.print(
        f"\n[green]🔒 {count} identifiers were protected "
        f"from Gemini[/green]\n"
    )

    # ── Save if needed ───────────────────────────────
    if output:
        write_file(Path(output), final)
        console.print(f"[green]💾 Saved: {output}[/green]")
