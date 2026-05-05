"""
Output Formatters

Provides formatting utilities for displaying abstraction results,
context blocks, statistics panels, and session listings.
"""

from typing import Any, Dict, List

from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from codeabstract.ui.console import get_console


def format_context_blocks(blocks: List[Dict]) -> str:
    """
    Format a list of context blocks as a readable string.

    Each block contains:
    - name: original identifier
    - lineno: line number in original source
    - ctx: context dict with snippet, start_line, end_line, target_line

    Returns:
        Formatted string with marked-up context.
    """
    if not blocks:
        return ""

    lines = ["─── Source Context ────────────────────────────────"]

    for block in blocks:
        name = block.get('name', '???')
        lineno = block.get('lineno', '?')
        ctx = block.get('ctx', {})

        lines.append(f"\n{name} (line {lineno}):\n")

        snippet = ctx.get('snippet', '')
        start_line = ctx.get('start_line', 1)
        target_line = ctx.get('target_line', lineno)

        if snippet:
            for i, line_text in enumerate(snippet.split('\n')):
                current_lineno = start_line + i
                marker = "→" if current_lineno == target_line else " "
                lines.append(f"{marker} {current_lineno:>4} │ {line_text}")
        else:
            lines.append("  (no context available)")

        lines.append("")

    lines.append("───────────────────────────────────────────────────")
    return '\n'.join(lines)


def print_abstraction_stats(stats: Dict[str, Any]) -> None:
    """Display abstraction statistics in a styled panel."""
    console = get_console()

    content = (
        f"[info]Total AST nodes:[/info]  {stats.get('total_nodes', 0)}\n"
        f"[success]Abstracted:[/success]       {stats.get('abstracted_nodes', 0)}\n"
        f"[muted]Skipped:[/muted]          {stats.get('skipped_nodes', 0)}\n"
        f"[secret]Secrets found:[/secret]   {stats.get('secrets_found', 0)}\n"
        f"[value]Values found:[/value]    {stats.get('values_found', 0)}"
    )

    panel = Panel(
        content,
        title="[header]Abstraction Statistics[/header]",
        border_style="cyan",
        expand=False,
    )
    console.print(panel)


def print_session_table(sessions: List[Dict]) -> None:
    """Display sessions in a rich table."""
    console = get_console()

    table = Table(
        title="Sessions",
        show_header=True,
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Session ID", style="session_id", no_wrap=True, max_width=12)
    table.add_column("Source File", style="white")
    table.add_column("Created", style="muted")
    table.add_column("Nodes", justify="right")
    table.add_column("Secrets", justify="right", style="secret")

    for s in sessions:
        stats = s.get('statistics', {})
        table.add_row(
            s['session_id'][:12] + "…",
            s.get('source_file_path', '—'),
            s.get('created_at', '—'),
            str(stats.get('abstracted_nodes', '—')),
            str(stats.get('secrets_found', '—')),
        )

    console.print(table)


def print_abstract_code(code: str, theme: str = "monokai") -> None:
    """Display abstract code with syntax highlighting."""
    console = get_console()

    console.print("\n[bold]Abstract code preview:[/bold]")
    console.print("─" * 70)

    syntax = Syntax(
        code,
        "python",
        theme=theme,
        line_numbers=True,
        word_wrap=True,
    )
    console.print(syntax)
    console.print("─" * 70)


def print_next_steps(session_id: str) -> None:
    """Print the 'what to do next' guidance."""
    console = get_console()
    short_id = session_id[:8]

    console.print("\n[bold cyan]💡 Next steps:[/bold cyan]")
    console.print("  1. Paste the abstract code into ChatGPT / Claude")
    console.print("  2. Ask for debugging / optimization / review help")
    console.print("  3. Copy the LLM's response")
    console.print(
        f"  4. Run: [yellow]codeabstract translate {short_id}[/yellow]\n"
    )
