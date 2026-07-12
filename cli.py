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

app.add_typer(sessions_app, name="sessions")
app.add_typer(config_app, name="config")


# ═══════════════════════════════════════════════════════════
# Primary commands
# ═══════════════════════════════════════════════════════════

@app.command()
def abstract(
    file: str = typer.Argument(..., help="Path to Python source file"),
    privacy: str = typer.Option("high", help="Privacy level: low|medium|high|critical"),
    context_window: int = typer.Option(3, "--context-window", "-k", help="Context window size"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save abstract code to file"),
    copy: bool = typer.Option(False, "--copy", "-c", help="Copy to clipboard"),
    show_mapping: bool = typer.Option(False, "--show-mapping", "-m", help="Show mapping statistics"),
):
    """Abstract source code for safe LLM consultation."""
    from commands.abstract_cmd import run_abstract
    run_abstract(file, privacy, context_window, output, copy, show_mapping)


@app.command()
def translate(
    session_id: str = typer.Argument(..., help="Session ID (or prefix)"),
    text: Optional[str] = typer.Argument(None, help="LLM response text"),
    file: Optional[str] = typer.Option(None, "--file", "-f", help="Read LLM response from file"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Save translated response"),
    format: str = typer.Option("text", "--format", help="Output format: text|markdown|html"),
):
    """Translate abstract LLM response back to readable code."""
    from commands.translate_cmd import run_translate
    run_translate(session_id, text, file, output, format)


@app.command()
def interactive():
    """Interactive guided workflow."""
    from commands.interactive_cmd import run_interactive
    run_interactive()


@app.command()
def review(
    file: str = typer.Argument(..., help="Python file to review"),
    task: str = typer.Option("review", "--task", "-t",
        help="debug | review | optimize | security | explain"),
    output: Optional[str] = typer.Option(None, "--output", "-o"),
    show_abstract: bool = typer.Option(False, "--show-abstract"),
    api_key: Optional[str] = typer.Option(None, "--api-key"),
    privacy: str = typer.Option("high", help="Privacy level: low|medium|high|critical"),
):
    """Auto review: Abstract -> Gemini -> Reconstruct"""
    from commands.review_cmd import run_review
    run_review(
        file=file,
        task=task,
        output=output,
        show_abstract=show_abstract,
        api_key=api_key,
        privacy=privacy,
    )


@app.command()
def stats():
    """Display usage statistics."""
    from commands.stats_cmd import run_stats
    run_stats()


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


# ═══════════════════════════════════════════════════════════
# Config sub-commands
# ═══════════════════════════════════════════════════════════

@config_app.command("show")
def config_show():
    """Show current configuration."""
    from commands.config_cmd import run_config_show
    run_config_show()


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
        from . import __version__
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
