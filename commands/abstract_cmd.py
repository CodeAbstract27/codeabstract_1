"""
CLI Command: abstract

Implements 'codeabstract abstract <file>' command.
Runs ABSTRACT(S, k) on the given source file.

Phase 4 additions: the language is chosen from the file extension rather
than assumed to be Python, every run emits a privacy report, and every run
appends an audit entry.
"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from algorithms.abstract_source import abstract_file
from config.ignore_rules import load_rules
from core.languages import detect_language, registered_languages
from core.privacy_report import report_for_result
from storage import audit_log
from storage.session_manager import save_session
from ui.console import get_console
from ui.formatters import (
    print_abstract_code,
    print_abstraction_stats,
    print_next_steps,
    print_privacy_report,
)
from utils.clipboard import copy_to_clipboard
from utils.file_io import read_file, write_file


def run_abstract(
    file: str,
    privacy: str = "high",
    context_window: int = 3,
    output: str = None,
    copy: bool = False,
    show_mapping: bool = False,
    keep_comments: bool = False,
    privacy_report: bool = False,
    report_json: Optional[str] = None,
    reveal: bool = False,
):
    """Execute the abstract command."""
    console = get_console()
    file_path = Path(file)

    if not file_path.exists():
        console.print(f"[error]✗ File not found: {file}[/error]")
        raise typer.Exit(1)

    # A directory "exists" too, and has no suffix -- without this check it
    # fell through to language detection and failed there with "No language
    # adapter for ''", which points the user at the wrong problem entirely.
    if file_path.is_dir():
        console.print(f"[error]✗ '{file}' is a directory, not a file.[/error]")
        raise typer.Exit(1)

    # Phase 4: the extension picks the engine.  An unknown extension is an
    # error rather than a Python assumption -- abstracting a JavaScript file
    # with the Python parser produces a file that looks abstracted and is not.
    language = detect_language(file_path)
    if language is None:
        console.print(
            f"[error]✗ No language adapter for '{file_path.suffix}'.[/error]\n"
            f"[info]Supported: {', '.join(registered_languages())}[/info]"
        )
        raise typer.Exit(1)

    # Read source
    try:
        source_code = read_file(file_path)
    except Exception as e:
        console.print(f"[error]✗ Failed to read file: {e}[/error]")
        raise typer.Exit(1)

    # Phase 1: project overrides, searched upward from the source file
    rules = load_rules(file_path)
    if rules:
        console.print(
            f"[info]Applying {rules.summary()} from {rules.source_path}[/info]"
        )

    # Run abstraction
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Running ABSTRACT(S, k) [{language}]…", total=None)
        try:
            result = abstract_file(
                path=file_path,
                source_code=source_code,
                context_window=context_window,
                privacy_level=privacy,
                overrides=rules,
                keep_comments=keep_comments,
            )
        except ValueError as e:
            console.print(f"\n[error]✗ Abstraction failed: {e}[/error]")
            raise typer.Exit(1)
        except Exception as e:  # missing grammar, unreadable file, …
            console.print(f"\n[error]✗ Abstraction failed: {e}[/error]")
            raise typer.Exit(1)
        progress.update(task, description="✓ Abstraction complete")

    # Save session
    try:
        save_session(
            session_id=result.session_id,
            source_file_path=str(file_path.resolve()),
            context_window=context_window,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key,
            statistics=result.statistics,
            line_map=result.line_map,
            language=result.language,
        )
    except Exception as e:
        console.print(f"[error]✗ Failed to save session: {e}[/error]")
        raise typer.Exit(1)

    # Phase 4: record the run.  A failure to log is reported, not fatal --
    # losing the abstraction because the audit file is read-only would push
    # people to turn logging off, which is worse for compliance.
    if audit_log.logging_enabled():
        try:
            audit_log.record_abstraction(
                session_id=result.session_id,
                source_file=str(file_path.resolve()),
                privacy_level=privacy,
                statistics=result.statistics,
                language=result.language,
            )
        except OSError as e:
            console.print(f"[warning]⚠ Audit log not written: {e}[/warning]")

    # Output
    console.print("\n[success]✓ Code abstracted successfully![/success]")
    console.print(f"[session_id]🔑 Session ID:[/session_id] {result.session_id}\n")

    if show_mapping:
        print_abstraction_stats(result.statistics)
        console.print()

    # Phase 4: the privacy report.  The one-line headline is always shown;
    # the tables are opt-in, because a forty-row table after every run is
    # noise and noise is what stops being read.
    report = report_for_result(
        result,
        source_file=str(file_path),
        privacy_level=privacy,
        reveal=reveal,
    )
    if privacy_report:
        print_privacy_report(report, detail=show_mapping)
        console.print()
    else:
        console.print(f"[muted]🔒 {report.headline()}[/muted]")
        console.print(
            "[muted]   Run with --privacy-report to see what was kept "
            "readable.[/muted]\n"
        )

    if report_json:
        try:
            # Always masked on disk, whatever --reveal says for the
            # terminal: a report file quoting live credentials is a second
            # copy of the leak this run exists to prevent.
            on_disk = report_for_result(
                result,
                source_file=str(file_path),
                privacy_level=privacy,
                reveal=False,
            )
            write_file(
                Path(report_json),
                json.dumps(on_disk.to_dict(), indent=2, ensure_ascii=False),
            )
            console.print(f"[success]💾 Privacy report: {report_json}[/success]")
        except Exception as e:
            console.print(f"[error]✗ Failed to save privacy report: {e}[/error]")

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

    print_abstract_code(result.abstract_code, language=result.language)
    print_next_steps(result.session_id)
