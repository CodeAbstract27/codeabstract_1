import os
import typer
from pathlib import Path
from typing import Optional
from rich.panel import Panel
from rich.table import Table
from rich.markdown import Markdown
from rich.text import Text
from rich.progress import Progress, SpinnerColumn, TextColumn

from algorithms.abstract import abstract
from algorithms.reconstruct import reconstruct_structured
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

        # Step 4: Reconstruct (structured)
        t = progress.add_task("[4/4] Reconstructing...", total=None)
        recon = reconstruct_structured(
            llm_response=llm_response.content,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key
        )
        progress.update(t, description="[green]✓ Done[/green]")

    # ── Display formatted results ────────────────────

    console.print()

    # ── Review Findings Panel ────────────────────────
    console.print(Panel(
        Markdown(recon.review_text),
        title="[bold]📋 Code Review[/bold]",
        title_align="left",
        subtitle=f"[dim]{file}[/dim]",
        subtitle_align="right",
        border_style="#d77757",
        padding=(1, 2),
    ))

    # ── Source References with Code Context ─────────
    if recon.references:
        # Separate key refs (show code snippets) from minor refs (compact table)
        key_prefixes = {"FUNC", "CLASS", "SECRET"}
        key_refs = [r for r in recon.references if r.get('prefix') in key_prefixes]
        minor_refs = [r for r in recon.references if r.get('prefix') not in key_prefixes]

        console.print(Panel(
            "[bold]📍 Source References[/bold]",
            border_style="#d77757",
            padding=(0, 1),
        ))

        # ── Group key refs by target line to avoid duplicate snippets ──
        grouped = {}
        for ref in key_refs:
            lineno = ref.get('lineno', '?')
            if lineno not in grouped:
                grouped[lineno] = []
            grouped[lineno].append(ref)

        for lineno, refs_at_line in grouped.items():
            # Build combined header for all identifiers at this line
            header = Text()
            for idx, ref in enumerate(refs_at_line):
                name = ref.get('name', '???')
                prefix = ref.get('prefix', 'VAR')
                type_label = ref.get('type', 'Identifier')

                if idx > 0:
                    header.append("  ,  ", style="dim")

                if prefix == 'SECRET':
                    header.append("  ⚠ " if idx == 0 else "⚠ ", style="bold red")
                    header.append(name, style="bold red")
                elif prefix == 'FUNC':
                    header.append("  ƒ " if idx == 0 else "ƒ ", style="bold cyan")
                    header.append(name, style="bold cyan")
                elif prefix == 'CLASS':
                    header.append("  ◆ " if idx == 0 else "◆ ", style="bold magenta")
                    header.append(name, style="bold magenta")
                else:
                    header.append("  " if idx == 0 else "", style="")
                    header.append(name, style="white bold")

            header.append(f"  ", style="")
            header.append(f"line {lineno}", style="yellow")

            # Show type labels
            type_labels = []
            for ref in refs_at_line:
                tl = ref.get('type', 'Identifier')
                if tl not in type_labels:
                    type_labels.append(tl)
            header.append(f"  │  ", style="dim")
            header.append(", ".join(type_labels), style="dim")

            console.print(header)

            # Show the code snippet once (use the first ref's context)
            ctx = refs_at_line[0].get('ctx', {})
            snippet = ctx.get('snippet', '')
            start_line = ctx.get('start_line', 1)
            target_line = ctx.get('target_line', lineno)

            if snippet:
                for i, line_text in enumerate(snippet.split('\n')):
                    current_lineno = start_line + i
                    is_target = (current_lineno == target_line)

                    line_out = Text()
                    if is_target:
                        line_out.append("  → ", style="bold #d77757")
                        line_out.append(f"{current_lineno:>4}", style="bold yellow")
                        line_out.append(" │ ", style="dim")
                        line_out.append(line_text, style="bold white")
                    else:
                        line_out.append("    ", style="")
                        line_out.append(f"{current_lineno:>4}", style="dim")
                        line_out.append(" │ ", style="dim")
                        line_out.append(line_text, style="dim")

                    console.print(line_out)
            else:
                console.print("    [dim](no context available)[/dim]")

            console.print()  # Blank line between snippets


        # ── Compact table for minor identifiers ───────
        if minor_refs:
            table = Table(
                title="Other Identifiers",
                title_style="dim bold",
                border_style="dim",
                show_header=True,
                header_style="bold",
                padding=(0, 1),
                show_edge=False,
            )
            table.add_column("Name", style="white", min_width=18)
            table.add_column("Line", justify="right", style="yellow", min_width=5)
            table.add_column("Type", style="dim", min_width=10)

            for ref in minor_refs:
                table.add_row(
                    ref.get('name', '???'),
                    str(ref.get('lineno', '?')),
                    ref.get('type', 'Identifier'),
                )

            console.print(table)
            console.print()

    # ── Privacy badge ────────────────────────────────
    console.print(
        f"[green]🔒 {count} identifiers were protected "
        f"from Gemini[/green]\n"
    )

    # ── Save if needed ───────────────────────────────
    if output:
        # Save the full plain-text output for file export
        plain_output = str(recon)
        write_file(Path(output), plain_output)
        console.print(f"[green]💾 Saved: {output}[/green]")

