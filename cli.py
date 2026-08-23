"""
CodeAbstract CLI — Main Entry Point

Typer application that registers all commands and sub-command groups.
"""

from typing import Optional
import typer

app = typer.Typer(
    name="codeabstract",
    help="Privacy-Preserving CLI for Secure LLM Code Consultation",
    add_completion=False,
    rich_markup_mode="rich",
)

sessions_app = typer.Typer(help="Session management commands")
config_app = typer.Typer(help="Configuration commands")
# Phase 4: providers, and the compliance record of what left the machine.
providers_app = typer.Typer(help="LLM provider commands")
audit_app = typer.Typer(help="Audit log commands")

app.add_typer(sessions_app, name="sessions")
app.add_typer(config_app, name="config")
app.add_typer(providers_app, name="providers")
app.add_typer(audit_app, name="audit")


# ═══════════════════════════════════════════════════════════
# Primary commands
# ═══════════════════════════════════════════════════════════

@app.command()
def abstract(
    file: str = typer.Argument(
        ..., help="Path to a Python or JavaScript/TypeScript source file"),
    privacy: str = typer.Option("high", help="Privacy level: low|medium|high|critical"),
    context_window: int = typer.Option(
        3, "--context-window", "-k", min=0,
        help="Context window size (lines of surrounding source per mapped "
             "identifier; must be >= 0)",
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save abstract code to file"),
    copy: bool = typer.Option(False, "--copy", "-c", help="Copy to clipboard"),
    show_mapping: bool = typer.Option(False, "--show-mapping", "-m", help="Show mapping statistics"),
    keep_comments: bool = typer.Option(
        False, "--keep-comments",
        help="Re-inject screened comments (stripped by default)",
    ),
    privacy_report: bool = typer.Option(
        False, "--privacy-report", "-r",
        help="Show what was hidden, kept readable, and uncertain",
    ),
    report_json: Optional[str] = typer.Option(
        None, "--privacy-report-json",
        help="Write the privacy report to JSON (secrets always masked)",
    ),
    reveal: bool = typer.Option(
        False, "--reveal",
        help="Show secret values unmasked in the terminal report",
    ),
):
    """Abstract source code for safe LLM consultation."""
    from commands.abstract_cmd import run_abstract
    run_abstract(
        file, privacy, context_window, output, copy, show_mapping,
        keep_comments, privacy_report, report_json, reveal,
    )


@app.command()
def translate(
    session_id: str = typer.Argument(..., help="Session ID (or prefix)"),
    text: Optional[str] = typer.Argument(None, help="LLM response text"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Read LLM response from file"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save translated response"),
    format: str = typer.Option("text", "--format", help="Output format: text|markdown|html"),
    reveal: bool = typer.Option(
        False, "--reveal",
        help="Show secret values unmasked in the translated text and its "
             "source-context blocks. Off by default.",
    ),
):
    """Translate abstract LLM response back to readable code."""
    from commands.translate_cmd import run_translate
    run_translate(session_id, text, file, output, format, reveal)


@app.command()
def apply(
    session_id: str = typer.Argument(..., help="Session ID (or prefix)"),
    text: Optional[str] = typer.Argument(None, help="LLM response text"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Read LLM response from file"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save restored code to a file"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Apply without confirmation"),
):
    """Restore identifiers in an LLM's code suggestion and apply it."""
    from commands.apply_cmd import run_apply
    run_apply(session_id, text, file, output, yes)


@app.command()
def interactive():
    """Interactive guided workflow."""
    from commands.interactive_cmd import run_interactive
    run_interactive()


@app.command()
def review(
    file: str = typer.Argument(..., help="Source file to review"),
    task: str = typer.Option("review", "--task", "-t",
        help="debug | review | optimize | security | explain"),
    query: Optional[str] = typer.Option(
        None, "--query", "-q",
        help="Ask your own question instead of a preset. The question is "
             "abstracted with the same mapping as the code.",
    ),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    show_abstract: bool = typer.Option(False, "--show-abstract"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-P", help="gemini | openai | anthropic"),
    model: Optional[str] = typer.Option(
        None, "--model", "-M", help="Model identifier for the provider"),
    privacy: str = typer.Option("high", help="Privacy level: low|medium|high|critical"),
    privacy_report: bool = typer.Option(
        False, "--privacy-report", "-r",
        help="Show what was hidden, kept readable, and uncertain"),
    report_json: Optional[str] = typer.Option(
        None, "--privacy-report-json", help="Write the privacy report to JSON"),
):
    """Auto review: Abstract -> LLM -> Reconstruct"""
    from commands.review_cmd import run_review
    run_review(
        file=file,
        task=task,
        output=output,
        show_abstract=show_abstract,
        api_key=api_key,
        privacy=privacy,
        provider=provider,
        model=model,
        query=query,
        privacy_report=privacy_report,
        report_json=report_json,
    )


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind"),
    port: int = typer.Option(5000, "--port", "-p", help="Port to listen on"),
    debug: bool = typer.Option(False, "--debug", help="Flask debug mode"),
    no_save: bool = typer.Option(
        False, "--no-save", help="Do not persist sessions (stateless server)"),
    allow_reveal: bool = typer.Option(
        False, "--allow-reveal",
        help="Permit the UI to unmask secret values (off by default)"),
    expose: bool = typer.Option(
        False, "--expose",
        help="Acknowledge binding to a non-loopback interface"),
):
    """Serve the web interface (Phase 5)."""
    from commands.web_cmd import run_web
    run_web(host, port, debug, no_save, allow_reveal, expose)


@app.command()
def stats():
    """Display usage statistics."""
    from commands.stats_cmd import run_stats
    run_stats()


@app.command()
def evaluate(
    privacy: str = typer.Option(
        "high",
        "--privacy-level", "-p",
        help="Privacy level to evaluate: low|medium|high|critical",
    ),
    output: str = typer.Option(
        "evaluation_output",
        "--output", "-o",
        help="Directory to save JSON and Markdown reports",
    ),
    no_terminal: bool = typer.Option(
        False, "--no-terminal",
        help="Skip terminal display; only save report files",
    ),
    skip_performance: bool = typer.Option(
        False, "--skip-performance",
        help="Skip performance benchmarks for a faster run",
    ),
):
    """
    Run the full evaluation suite across all 5 metric pillars.

    Measures: PIR (privacy), RF (reconstruction), F1 (classification),
    CSP (structure), and Performance. Saves JSON + Markdown reports.
    """
    import sys, os
    sys.argv = [
        "run_eval.py",
        "--privacy-level", privacy,
        "--output", output,
    ]
    if no_terminal:
        sys.argv.append("--no-terminal")
    if skip_performance:
        sys.argv.append("--skip-performance")

    from evaluation.run_eval import main as run_eval_main
    run_eval_main()


# ═══════════════════════════════════════════════════════════
# Sessions sub-commands
# ═══════════════════════════════════════════════════════════

@sessions_app.command("list")
def sessions_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Max sessions to show"),
):
    """List recent sessions."""
    from commands.sessions_cmd import run_sessions_list
    run_sessions_list(limit)


@sessions_app.command("show")
def sessions_show(
    session_id: str = typer.Argument(..., help="Session ID (or prefix)"),
):
    """Show details of a session."""
    from commands.sessions_cmd import run_sessions_show
    run_sessions_show(session_id)


@sessions_app.command("delete")
def sessions_delete(
    session_id: str = typer.Argument(..., help="Session ID (or prefix)"),
    force: bool = typer.Option(False, "--force", "-f", help="Skip confirmation"),
):
    """Delete a session."""
    from commands.sessions_cmd import run_sessions_delete
    run_sessions_delete(session_id, force)


@sessions_app.command("export")
def sessions_export(
    session_id: str = typer.Argument(..., help="Session ID (or prefix)"),
    output: str = typer.Option(..., "--output", "-o", help="Output file path"),
):
    """Export session metadata to a file."""
    from commands.sessions_cmd import run_sessions_export
    run_sessions_export(session_id, output)


@sessions_app.command("migrate-keys")
def sessions_migrate_keys(
    backend: Optional[str] = typer.Option(
        None, "--backend", help="auto | keyring | file"),
):
    """Move pre-Phase-4 session keys out of the database."""
    from commands.sessions_cmd import run_sessions_migrate_keys
    run_sessions_migrate_keys(backend)


@sessions_app.command("keys")
def sessions_keys():
    """Report where session encryption keys are stored."""
    from commands.sessions_cmd import run_sessions_keys_status
    run_sessions_keys_status()


# ═══════════════════════════════════════════════════════════
# Providers sub-commands (Phase 4)
# ═══════════════════════════════════════════════════════════

@providers_app.command("list")
def providers_list():
    """Show which LLM providers are installed and configured."""
    from commands.providers_cmd import run_providers_list
    run_providers_list()


@providers_app.command("compare")
def providers_compare(
    file: str = typer.Argument(..., help="Source file to review"),
    providers: Optional[str] = typer.Option(
        None, "--providers", help="Comma-separated names; all ready ones by default"),
    task: str = typer.Option("review", "--task", "-t"),
    query: Optional[str] = typer.Option(None, "--query", "-q"),
    privacy: str = typer.Option("high", "--privacy"),
    output: Optional[str] = typer.Option(
        None, "--output", "-o", help="Write the full comparison to JSON"),
):
    """Review the same file through several providers and compare them."""
    from commands.providers_cmd import run_providers_compare
    run_providers_compare(file, providers, task, privacy, query, output)


@app.command()
def languages():
    """Show which language adapters are available."""
    from commands.providers_cmd import run_languages_list
    run_languages_list()


# ═══════════════════════════════════════════════════════════
# Audit sub-commands (Phase 4)
# ═══════════════════════════════════════════════════════════

@audit_app.command("list")
def audit_list(
    limit: int = typer.Option(20, "--limit", "-n", help="Max entries to show"),
    event: Optional[str] = typer.Option(
        None, "--event", help="Filter: abstract | request"),
):
    """Show recent audit entries."""
    from commands.audit_cmd import run_audit_list
    run_audit_list(limit, event)


@audit_app.command("show")
def audit_show(
    seq: int = typer.Argument(..., help="Sequence number of the entry"),
):
    """Show one audit entry in full."""
    from commands.audit_cmd import run_audit_show
    run_audit_show(seq)


@audit_app.command("verify")
def audit_verify():
    """Verify the audit log's hash chain."""
    from commands.audit_cmd import run_audit_verify
    run_audit_verify()


@audit_app.command("export")
def audit_export(
    output: str = typer.Option(..., "--output", "-o", help="Output file path"),
    format: str = typer.Option("json", "--format", help="json | csv"),
):
    """Export the audit log."""
    from commands.audit_cmd import run_audit_export
    run_audit_export(output, format)


# ═══════════════════════════════════════════════════════════
# Config sub-commands
# ═══════════════════════════════════════════════════════════

@config_app.command("show")
def config_show(
    reveal: bool = typer.Option(
        False, "--reveal",
        help="Print stored API keys in full instead of masking them",
    ),
):
    """Show current configuration."""
    from commands.config_cmd import run_config_show
    run_config_show(reveal)


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key"),
    value: str = typer.Argument(..., help="Configuration value"),
):
    """Set a configuration value."""
    from commands.config_cmd import run_config_set
    run_config_set(key, value)


# ═══════════════════════════════════════════════════════════
# Version callback
# ═══════════════════════════════════════════════════════════

def version_callback(value: bool):
    if value:
        from config.settings import __version__
        typer.echo(f"CodeAbstract v{__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", callback=version_callback, is_eager=True,
        help="Show version and exit",
    ),
):
    """CodeAbstract — Privacy-Preserving CLI for Secure LLM Code Consultation"""
    pass


if __name__ == "__main__":
    app()
