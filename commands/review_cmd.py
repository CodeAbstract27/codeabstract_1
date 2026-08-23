"""
CLI Command: review

Abstract → LLM → Reconstruct, in one step.

Phase 4 rewrote this command around what the audit found missing:

* any of the three providers, not Gemini behind a factory that ignored its
  own provider argument;
* a free-form ``--query``, abstracted with the same mapping as the code,
  because a question written in the user's own identifiers would hand back
  what the abstraction just removed;
* a privacy report and an audit entry on every run.
"""

import json
from pathlib import Path
from typing import Optional

import typer
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from algorithms.abstract_source import abstract_file
from algorithms.encrypt import decrypt_mapping, encrypt_mapping
from algorithms.reconstruct import reconstruct
from config.ignore_rules import load_rules
from core.languages import detect_language, registered_languages
from core.privacy_report import build_report
from core.query_abstractor import abstract_query
from llm import ProviderError, create_client
from llm.base import build_prompt
from storage import audit_log
from storage.session_manager import save_session
from ui.console import get_console
from ui.formatters import print_privacy_report
from utils.file_io import read_file, write_file

console = get_console()


def run_review(
    file: str,
    task: str = "review",
    output: Optional[str] = None,
    show_abstract: bool = False,
    api_key: Optional[str] = None,
    privacy: str = "high",
    provider: Optional[str] = None,
    model: Optional[str] = None,
    query: Optional[str] = None,
    privacy_report: bool = False,
    report_json: Optional[str] = None,
    save: bool = True,
):
    """Execute the review command."""
    file_path = Path(file)
    if not file_path.exists():
        console.print(f"[red]✗ File not found: {file}[/red]")
        raise typer.Exit(1)

    if file_path.is_dir():
        console.print(f"[red]✗ '{file}' is a directory, not a file.[/red]")
        raise typer.Exit(1)

    language = detect_language(file_path)
    if language is None:
        console.print(
            f"[red]✗ No language adapter for '{file_path.suffix}'.[/red]\n"
            f"[yellow]Supported: {', '.join(registered_languages())}[/yellow]"
        )
        raise typer.Exit(1)

    # ── Build the client before touching the file ────
    # Nothing is abstracted until we know a provider is actually reachable:
    # doing the work first and failing on a missing key wastes the user's
    # time and tells them nothing they could not have been told up front.
    try:
        client = create_client(api_key=api_key, provider=provider, model=model)
    except ProviderError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)

    console.print(Panel(
        f"[bold cyan]CodeAbstract Review[/bold cyan]\n"
        f"[dim]{file} → {client.provider}/{client.model} → Reconstructed[/dim]"
    ))

    with Progress(
        SpinnerColumn(),
        TextColumn("{task.description}"),
        console=console,
    ) as progress:

        # ── Step 1: Read ─────────────────────────────
        step = progress.add_task("[1/4] Reading file…", total=None)
        source_code = read_file(file_path)
        progress.update(step, description="[green]✓ File read[/green]")

        # ── Step 2: Abstract ─────────────────────────
        step = progress.add_task(f"[2/4] Abstracting [{language}]…", total=None)
        try:
            result = abstract_file(
                path=file_path,
                source_code=source_code,
                privacy_level=privacy,
                overrides=load_rules(file_path),
            )
        except Exception as exc:
            progress.stop()
            console.print(f"\n[red]✗ Abstraction failed: {exc}[/red]")
            raise typer.Exit(1)

        count = result.statistics['abstracted_nodes']
        progress.update(step, description=f"[green]✓ {count} identifiers abstracted[/green]")

        # ── Step 2b: Abstract the query too ──────────
        mapping_table = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
        encrypted_mapping = result.encrypted_mapping
        encryption_key = result.encryption_key
        abstracted_query = None

        if query:
            abstracted_query = abstract_query(query, mapping_table)
            if abstracted_query.mapping_additions:
                # Secrets that appear only in the question still need to
                # resolve on the way back, so they join the mapping before
                # it is re-encrypted.
                mapping_table.update(abstracted_query.mapping_additions)
                encrypted_mapping, encryption_key = encrypt_mapping(mapping_table)
            progress.update(
                step,
                description=(
                    f"[green]✓ {count} identifiers abstracted; "
                    f"query: {abstracted_query.summary()}[/green]"
                ),
            )

        if show_abstract:
            progress.stop()
            console.print(f"\n[bold]Abstract code sent to {client.provider}:[/bold]")
            console.print("─" * 50)
            console.print(result.abstract_code)
            if abstracted_query:
                console.print("─" * 50)
                console.print(f"[bold]Abstract query:[/bold] {abstracted_query.text}")
            console.print("─" * 50 + "\n")
            progress.start()

        # ── Step 3: Send ─────────────────────────────
        step = progress.add_task(f"[3/4] Sending to {client.provider}…", total=None)
        query_text = abstracted_query.text if abstracted_query else None
        llm_response = client.send(
            abstract_code=result.abstract_code,
            task=task,
            query=query_text,
            language=language,
        )

        # The payload hash goes in the audit log; the payload does not.
        payload = build_prompt(
            result.abstract_code, task=task, query=query_text, language=language,
        )
        if audit_log.logging_enabled():
            try:
                audit_log.record_request(
                    session_id=result.session_id,
                    source_file=str(file_path.resolve()),
                    provider=client.provider,
                    model=client.model,
                    privacy_level=privacy,
                    payload_sha256=audit_log.payload_digest(payload),
                    response=llm_response,
                    language=language,
                    task=None if query else task,
                    free_form_query=bool(query),
                )
            except OSError as exc:
                progress.stop()
                console.print(f"[yellow]⚠ Audit log not written: {exc}[/yellow]")
                progress.start()

        if not llm_response.success:
            progress.stop()
            console.print(
                f"\n[red]✗ {client.provider} error "
                f"(after {llm_response.attempts} attempt(s)): "
                f"{llm_response.error}[/red]"
            )
            raise typer.Exit(1)

        progress.update(
            step,
            description=(
                f"[green]✓ {client.provider} responded "
                f"({llm_response.response_time:.1f}s)[/green]"
            ),
        )

        # ── Step 4: Reconstruct ──────────────────────
        step = progress.add_task("[4/4] Reconstructing…", total=None)
        final = reconstruct(
            llm_response=llm_response.content,
            encrypted_mapping=encrypted_mapping,
            encryption_key=encryption_key,
            line_map=result.line_map,
        )
        progress.update(step, description="[green]✓ Done[/green]")

    # ── Persist the session ──────────────────────────
    # Without this the mapping is gone the moment the process exits, so
    # `codeabstract apply` has nothing to de-tokenise a follow-up against.
    if save:
        try:
            save_session(
                session_id=result.session_id,
                source_file_path=str(file_path.resolve()),
                context_window=3,
                encrypted_mapping=encrypted_mapping,
                encryption_key=encryption_key,
                statistics=result.statistics,
                line_map=result.line_map,
                language=result.language,
            )
        except Exception as exc:
            console.print(f"[yellow]⚠ Session not saved: {exc}[/yellow]")

    # ── Display ──────────────────────────────────────
    console.print()
    console.print("─" * 60)
    console.print(f"[bold] RESULTS: {file}[/bold]")
    console.print("─" * 60)
    console.print(final)
    console.print("─" * 60)

    usage = llm_response.usage
    if usage.reported:
        console.print(
            f"[dim]{client.provider}/{client.model} · "
            f"{usage.prompt_tokens} in / {usage.completion_tokens} out tokens[/dim]"
        )

    report = build_report(
        mapping_table=mapping_table,
        statistics=result.statistics,
        kept=result.kept,
        session_id=result.session_id,
        source_file=str(file_path),
        privacy_level=privacy,
        language=result.language,
    )

    if privacy_report:
        console.print()
        print_privacy_report(report)
    else:
        console.print(f"\n[green]🔒 {report.headline()}[/green]")

    console.print(f"[dim]Session: {result.session_id}[/dim]\n")

    if report_json:
        try:
            write_file(
                Path(report_json),
                json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
            )
            console.print(f"[green]💾 Privacy report: {report_json}[/green]")
        except Exception as exc:
            console.print(f"[red]✗ Failed to save privacy report: {exc}[/red]")

    if output:
        write_file(Path(output), final)
        console.print(f"[green]💾 Saved: {output}[/green]")
