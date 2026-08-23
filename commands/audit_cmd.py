"""
Audit Command Handler

Executes PrivacyAnalyzer to inspect code for sensitive patterns and display
the Privacy Exposure Score dashboard with risk metrics and line findings.
"""

from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box
from core.analyzer import PrivacyAnalyzer, RiskLevel
from utils.file_io import read_file
from utils.validators import validate_python_file

console = Console()


def run_audit(file_path: str):
    """Run privacy risk audit on a Python source file."""
    try:
        path = validate_python_file(file_path)
        code = read_file(path)
    except Exception as e:
        console.print(f"[bold red]Error:[/] {e}")
        return

    analyzer = PrivacyAnalyzer(code)
    try:
        report = analyzer.analyze()
    except Exception as e:
        console.print(f"[bold red]Audit Failed:[/] {e}")
        return

    # Determine status color
    if report.risk_level == RiskLevel.LOW:
        color = "green"
    elif report.risk_level == RiskLevel.MEDIUM:
        color = "yellow"
    elif report.risk_level == RiskLevel.HIGH:
        color = "red"
    else:
        color = "bold magenta"

    # Visual exposure meter
    meter_len = 20
    filled = int((report.exposure_score / 100.0) * meter_len)
    meter = f"[{color}]" + "█" * filled + "░" * (meter_len - filled) + f"[/] {report.exposure_score:.1f}%"

    summary_text = (
        f"[bold]File Scanned:[/] {path.name}\n"
        f"[bold]Exposure Score:[/] {meter}\n"
        f"[bold]Risk Assessment:[/] [{color}]{report.risk_level.value}[/]\n"
        f"[bold]Total Nodes Scanned:[/] {report.total_nodes}\n"
        f"[bold]Secrets Detected:[/] {report.secret_count}\n"
        f"[bold]Business Values Detected:[/] {report.value_count}"
    )

    console.print(
        Panel(
            summary_text,
            title="[bold blue]CodeAbstract — Privacy Risk Audit Report[/]",
            expand=False,
            border_style="blue",
        )
    )

    if report.findings:
        table = Table(
            title="[bold yellow]Detected Privacy Risk Findings[/]",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )
        table.add_column("Line", justify="right", style="dim")
        table.add_column("Category", style="bold")
        table.add_column("Node / Secret Match")
        table.add_column("Pattern Type")

        for f in report.findings:
            cat_color = "red" if f.category == "SECRET" else "yellow"
            table.add_row(
                str(f.line_number),
                f"[{cat_color}]{f.category}[/]",
                f.node_name,
                f.pattern_matched,
            )

        console.print(table)
    else:
        console.print("[bold green]✓ No sensitive secrets or high-risk identifiers detected.[/]")
