"""
CodeAbstract Evaluation Runner

Entry point to run the full evaluation suite across all 5 metric pillars.

Usage:
    python evaluation/run_eval.py
    python evaluation/run_eval.py --privacy-level medium
    python evaluation/run_eval.py --output results/
    python evaluation/run_eval.py --no-terminal   # JSON + Markdown only
"""

import argparse
import os
import sys
import time

# Ensure project root is in path when run directly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(
        description="CodeAbstract Evaluation Suite — measures PIR, RF, F1, CSP, and Performance",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python evaluation/run_eval.py
  python evaluation/run_eval.py --privacy-level medium
  python evaluation/run_eval.py --output results/
  python evaluation/run_eval.py --no-terminal --output paper_data/
        """,
    )
    parser.add_argument(
        "--privacy-level",
        choices=["low", "medium", "high", "critical"],
        default="high",
        help="Abstraction privacy level to evaluate (default: high)",
    )
    parser.add_argument(
        "--output",
        default="evaluation_output",
        metavar="DIR",
        help="Directory to save JSON and Markdown reports (default: evaluation_output/)",
    )
    parser.add_argument(
        "--no-terminal",
        action="store_true",
        help="Skip terminal Rich output; only save files",
    )
    parser.add_argument(
        "--skip-performance",
        action="store_true",
        help="Skip performance benchmarks (faster run for quick checks)",
    )
    args = parser.parse_args()

    privacy_level = args.privacy_level
    output_dir = args.output
    os.makedirs(output_dir, exist_ok=True)

    # ── Import all metric modules ──────────────────────────────────
    from rich.console import Console
    from rich.progress import Progress, SpinnerColumn, TextColumn
    import io

    console = Console(highlight=False, emoji=False)

    if not args.no_terminal:
        console.print("\n[bold cyan]CodeAbstract Evaluation Suite[/bold cyan]")
        console.print(f"[dim]Privacy level: {privacy_level}[/dim]\n")

    total_start = time.perf_counter()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
        transient=True,
    ) as progress:

        # Pillar 1 — Privacy
        task = progress.add_task("Running Pillar 1: Privacy Leakage...", total=None)
        from evaluation.metrics.privacy import run_privacy_suite
        privacy_result = run_privacy_suite(privacy_level=privacy_level)
        progress.remove_task(task)
        console.print("[green]DONE[/green] Pillar 1 - Privacy Leakage complete")

        # Pillar 2 — Reconstruction
        task = progress.add_task("Running Pillar 2: Reconstruction Fidelity...", total=None)
        from evaluation.metrics.reconstruction import run_reconstruction_suite
        reconstruction_result = run_reconstruction_suite(privacy_level=privacy_level)
        progress.remove_task(task)
        console.print("[green]DONE[/green] Pillar 2 - Reconstruction Fidelity complete")

        # Pillar 3 — Classification
        task = progress.add_task("Running Pillar 3: Classification Accuracy (F1)...", total=None)
        from evaluation.metrics.classification import run_classification_evaluation
        classification_result = run_classification_evaluation()
        progress.remove_task(task)
        console.print("[green]DONE[/green] Pillar 3 - Classification Accuracy complete")

        # Pillar 4 — Structure
        task = progress.add_task("Running Pillar 4: Code Structure Preservation...", total=None)
        from evaluation.metrics.structure import run_structure_suite
        structure_result = run_structure_suite(privacy_level=privacy_level)
        progress.remove_task(task)
        console.print("[green]DONE[/green] Pillar 4 - Code Structure Preservation complete")

        # Pillar 5 — Performance
        if args.skip_performance:
            from evaluation.metrics.performance import PerformanceSuiteResult
            performance_result = PerformanceSuiteResult()
            console.print("[dim]SKIP  Pillar 5 - Performance skipped[/dim]")
        else:
            task = progress.add_task("Running Pillar 5: Performance Benchmarks...", total=None)
            from evaluation.metrics.performance import run_performance_suite
            performance_result = run_performance_suite(privacy_level=privacy_level)
            progress.remove_task(task)
            console.print("[green]DONE[/green] Pillar 5 - Performance Benchmarks complete")

    total_elapsed = round(time.perf_counter() - total_start, 2)
    console.print(f"\n[dim]Evaluation completed in {total_elapsed}s[/dim]\n")

    # ── Render Reports ─────────────────────────────────────────────
    from evaluation.report import (
        render_terminal_report,
        save_json_report,
        save_markdown_report,
    )

    if not args.no_terminal:
        render_terminal_report(
            privacy=privacy_result,
            reconstruction=reconstruction_result,
            classification=classification_result,
            structure=structure_result,
            performance=performance_result,
            privacy_level=privacy_level,
        )

    json_path = save_json_report(
        privacy=privacy_result,
        reconstruction=reconstruction_result,
        classification=classification_result,
        structure=structure_result,
        performance=performance_result,
        output_path=output_dir,
        privacy_level=privacy_level,
    )

    md_path = save_markdown_report(
        privacy=privacy_result,
        reconstruction=reconstruction_result,
        classification=classification_result,
        structure=structure_result,
        performance=performance_result,
        output_path=output_dir,
        privacy_level=privacy_level,
    )

    console.print(f"[green]✓[/green] JSON report saved: [cyan]{json_path}[/cyan]")
    console.print(f"[green]✓[/green] Markdown report saved: [cyan]{md_path}[/cyan]\n")


if __name__ == "__main__":
    main()
