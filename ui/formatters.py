"""
Output Formatters

Provides formatting utilities for displaying abstraction results,
context blocks, statistics panels, and session listings.
"""

from typing import Any, Dict, List

from rich.box import ROUNDED, MINIMAL
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from ui.console import get_console


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
        border_style="#d77757",
        box=ROUNDED,
        expand=False,
    )
    console.print(panel)


def print_session_table(sessions: List[Dict]) -> None:
    """Display sessions in a rich table."""
    console = get_console()

    table = Table(
        title="Sessions",
        show_header=True,
        header_style="bold #d77757",
        border_style="dim",
        box=ROUNDED,
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


def print_abstract_code(
    code: str,
    theme: str = "monokai",
    language: str = "python",
) -> None:
    """
    Display abstract code with syntax highlighting.

    Args:
        code: The abstract code.
        theme: Pygments theme name.
        language: Lexer to highlight with (Phase 4 — the tool is no longer
            Python-only, and highlighting JavaScript as Python makes the
            preview harder to read than no highlighting at all).
    """
    console = get_console()

    syntax = Syntax(
        code,
        language,
        theme=theme,
        line_numbers=True,
        word_wrap=True,
        background_color="default",
    )
    panel = Panel(
        syntax,
        title="[bold #d77757]Abstract Code Preview[/bold #d77757]",
        title_align="left",
        border_style="#d77757",
        box=ROUNDED,
        padding=(0, 1),
    )
    console.print(panel)


def print_next_steps(session_id: str) -> None:
    """Print the 'what to do next' guidance."""
    console = get_console()
    short_id = session_id[:8]

    console.print("\n[bold #d77757]💡 Next steps:[/bold #d77757]")
    console.print("  1. Paste the abstract code into your LLM")
    console.print("  2. Ask for debugging / optimization / review help")
    console.print("  3. Copy the LLM's response")
    console.print(
        f"  4. Run: [accent]codeabstract translate {short_id}[/accent]\n"
    )


# ═══════════════════════════════════════════════════════════
# Phase 4 — privacy report
# ═══════════════════════════════════════════════════════════

def print_privacy_report(report, detail: bool = False, max_rows: int = 20) -> None:
    """
    Display a :class:`core.privacy_report.PrivacyReport`.

    Kept names come first and uncertain decisions second, because those are
    the two lists a user can act on: one is the exposure they are about to
    accept, the other is where the detector is guessing. The hidden count —
    the number the tool used to lead with — is a summary line at the end.

    Args:
        report: The report to display.
        detail: Show every hidden symbol as well as the summary.
        max_rows: Rows per table before truncating. Truncation is stated
            explicitly; a silently shortened privacy report would be worse
            than none.
    """
    console = get_console()

    console.print(Panel(
        f"[info]File:[/info] {report.source_file or '—'}\n"
        f"[info]Level:[/info] {report.privacy_level}   "
        f"[info]Language:[/info] {report.language}   "
        f"[info]Detector:[/info] {report.detector_version}\n"
        f"[muted]{report.headline()}[/muted]",
        title="[header]Privacy Report[/header]",
        border_style="#d77757",
        box=ROUNDED,
        expand=False,
    ))

    # ── What is still readable in the outbound payload ──
    if report.kept:
        table = Table(
            title="Kept readable — sent to the provider as-is",
            show_header=True, header_style="bold #d77757",
            border_style="dim", box=MINIMAL,
        )
        table.add_column("Name", style="identifier")
        table.add_column("Why", style="muted")
        table.add_column("Line", justify="right")
        table.add_column("Uses", justify="right")

        for item in report.kept[:max_rows]:
            table.add_row(
                item.name if len(item.name) <= 48 else item.name[:45] + "…",
                item.reason,
                str(item.lineno),
                str(item.occurrences),
            )
        console.print(table)
        if len(report.kept) > max_rows:
            console.print(
                f"[muted]  … and {len(report.kept) - max_rows} more "
                f"(use --privacy-report-json for the full list)[/muted]"
            )
    else:
        console.print("[success]✓ Nothing kept readable at this level.[/success]")

    # ── Where the detector was unsure ──
    if report.uncertain:
        table = Table(
            title="Unsure — below the review threshold",
            show_header=True, header_style="bold #ffb74d",
            border_style="dim", box=MINIMAL,
        )
        table.add_column("Token", style="accent")
        table.add_column("Name", style="identifier")
        table.add_column("Label")
        table.add_column("Conf.", justify="right")
        table.add_column("Detector", style="muted")

        for item in report.uncertain[:max_rows]:
            table.add_row(
                item.token, item.name, item.label,
                f"{item.confidence:.2f}", item.detector,
            )
        console.print(table)
        if len(report.uncertain) > max_rows:
            console.print(
                f"[muted]  … and {len(report.uncertain) - max_rows} more[/muted]"
            )

    # ── What was hidden ──
    summary = Table(
        title="Hidden", show_header=True, header_style="bold green",
        border_style="dim", box=MINIMAL,
    )
    summary.add_column("Label")
    summary.add_column("Count", justify="right")
    summary.add_column("Detector", style="muted")
    summary.add_column("Count", justify="right")

    labels = sorted(report.hidden_by_label.items())
    detectors = sorted(report.hidden_by_detector.items(), key=lambda kv: -kv[1])
    for index in range(max(len(labels), len(detectors))):
        label_cell, label_count = labels[index] if index < len(labels) else ("", "")
        det_cell, det_count = detectors[index] if index < len(detectors) else ("", "")
        summary.add_row(label_cell, str(label_count), det_cell, str(det_count))
    console.print(summary)

    if detail and report.hidden:
        table = Table(
            title="Hidden — every symbol", show_header=True,
            header_style="bold green", border_style="dim", box=MINIMAL,
        )
        table.add_column("Token", style="accent")
        table.add_column("Name", style="identifier")
        table.add_column("Label")
        table.add_column("Line", justify="right")
        table.add_column("Uses", justify="right")
        for item in report.hidden[:max_rows * 3]:
            table.add_row(
                item.token, item.name, item.label,
                str(item.lineno), str(item.occurrences),
            )
        console.print(table)

    if report.secrets_masked:
        console.print(
            "[muted]Secret values are masked. Pass --reveal to show them "
            "in the terminal.[/muted]"
        )
