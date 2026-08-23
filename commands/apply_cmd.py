"""
CLI Command: apply

Implements 'codeabstract apply <session-id>' (Phase 1).

Recovers code suggestions from an LLM response, restores the original
identifiers, and offers to write a whole-file rewrite back to disk after
showing a unified diff.
"""

from pathlib import Path
from typing import Optional

import typer
from rich.box import ROUNDED
from rich.panel import Panel
from rich.syntax import Syntax

from algorithms.apply_fix import build_diff, recover_fixes
from storage.session_manager import load_session
from ui.console import get_console
from utils.file_io import read_file, write_file


def run_apply(
    session_id: str,
    text: Optional[str] = None,
    file: Optional[str] = None,
    output: Optional[str] = None,
    yes: bool = False,
):
    """Execute the apply command."""
    console = get_console()

    if not text and not file:
        console.print("[error]✗ Provide either response text or --file[/error]")
        raise typer.Exit(1)

    # ── Load the LLM response ────────────────────────
    if file:
        try:
            llm_response = read_file(Path(file))
        except Exception as e:
            console.print(f"[error]✗ Failed to read file: {e}[/error]")
            raise typer.Exit(1)
    else:
        llm_response = text

    # ── Load the session ─────────────────────────────
    try:
        session = load_session(session_id)
    except Exception as e:
        console.print(f"[error]✗ {e}[/error]")
        console.print("[info]💡 Check: codeabstract sessions list[/info]")
        raise typer.Exit(1)

    source_path = Path(session['source_file_path'])
    try:
        original_source = read_file(source_path)
    except Exception as e:
        console.print(f"[error]✗ Cannot read original file {source_path}: {e}[/error]")
        raise typer.Exit(1)

    # ── Recover suggestions ──────────────────────────
    try:
        fixes = recover_fixes(
            llm_response=llm_response,
            encrypted_mapping=session['encrypted_mapping'],
            encryption_key=session['encryption_key'],
            original_source=original_source,
        )
    except ValueError as e:
        console.print(f"[error]✗ {e}[/error]")
        raise typer.Exit(1)

    if not fixes:
        console.print("[warning]⚠ No Python code blocks found in the response.[/warning]")
        raise typer.Exit(0)

    console.print(
        f"\n[success]✓ Recovered {len(fixes)} code block"
        f"{'s' if len(fixes) != 1 else ''} from the response[/success]\n"
    )

    applicable = [fix for fix in fixes if fix.applicable]

    # ── Report every block ───────────────────────────
    for fix in fixes:
        status = []
        status.append("parses" if fix.parses else "[error]does not parse[/error]")
        if fix.is_whole_file:
            status.append("whole file")
        else:
            status.append("fragment")
        if fix.unresolved_tokens:
            status.append(
                f"[warning]{len(fix.unresolved_tokens)} unresolved token(s)[/warning]"
            )

        console.print(
            f"[header]Block {fix.index + 1}[/header] — "
            f"{fix.tokens_restored} identifier(s) restored — " + ", ".join(status)
        )
        console.print(
            Panel(
                Syntax(fix.restored_code.strip(), "python", theme="monokai",
                       line_numbers=False, word_wrap=False),
                border_style="#d77757",
                box=ROUNDED,
                expand=False,
            )
        )

    # ── Write out if asked ───────────────────────────
    if output:
        combined = "\n\n".join(fix.restored_code.strip() for fix in fixes)
        try:
            write_file(Path(output), combined + "\n")
            console.print(f"[success]💾 Restored code saved to: {output}[/success]")
        except Exception as e:
            console.print(f"[error]✗ Failed to save: {e}[/error]")

    if not applicable:
        console.print(
            "\n[info]No block is a complete, fully-resolved rewrite of "
            f"{source_path.name}, so nothing can be applied automatically.[/info]"
        )
        console.print(
            "[info]The restored code above is ready to paste in by hand.[/info]"
        )
        raise typer.Exit(0)

    # ── Diff and confirm ─────────────────────────────
    fix = applicable[0]
    diff = build_diff(original_source, fix.restored_code, source_path.name)

    if not diff:
        console.print("[info]The suggestion is identical to the current file.[/info]")
        raise typer.Exit(0)

    console.print(f"\n[header]Proposed changes to {source_path}[/header]")
    console.print(
        Panel(
            Syntax(diff, "diff", theme="monokai", line_numbers=False),
            border_style="#d77757",
            box=ROUNDED,
            expand=False,
        )
    )

    if not yes:
        confirmed = typer.confirm(
            f"Apply these changes to {source_path.name}?", default=False
        )
        if not confirmed:
            console.print("[info]Not applied.[/info]")
            raise typer.Exit(0)

    try:
        write_file(source_path, fix.restored_code)
    except Exception as e:
        console.print(f"[error]✗ Failed to write {source_path}: {e}[/error]")
        raise typer.Exit(1)

    console.print(f"[success]✓ Applied to {source_path}[/success]")
