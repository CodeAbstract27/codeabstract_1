"""
Evaluation Report Generator

Consumes results from all 6 metric pillars and produces:
  1. Rich terminal table (human-readable, coloured)
  2. JSON file (machine-readable, for paper tables)
  3. Markdown report (for paper appendix / documentation)
"""

import json
import os
from datetime import datetime
from typing import Optional

from evaluation.metrics.classification import ClassificationResult
from evaluation.adversary import AdversarySuiteResult
from evaluation.metrics.mapping import MappingSuiteResult
from evaluation.metrics.performance import PerformanceSuiteResult
from evaluation.metrics.privacy import PrivacySuiteResult
from evaluation.metrics.reconstruction import ReconstructionSuiteResult
from evaluation.metrics.structure import StructureSuiteResult


# ═══════════════════════════════════════════════════════════════════
# Rich Terminal Report
# ═══════════════════════════════════════════════════════════════════

def render_terminal_report(
    privacy: PrivacySuiteResult,
    reconstruction: ReconstructionSuiteResult,
    classification: ClassificationResult,
    structure: StructureSuiteResult,
    performance: PerformanceSuiteResult,
    privacy_level: str = "high",
    mapping: Optional[MappingSuiteResult] = None,
    adversary: Optional[AdversarySuiteResult] = None,
) -> None:
    """Render a Rich-formatted terminal evaluation report."""
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.columns import Columns
    from rich import box
    from rich.text import Text

    console = Console()

    console.print()
    console.print(Panel.fit(
        "[bold cyan]CodeAbstract — Evaluation Report[/bold cyan]\n"
        f"[dim]Privacy level: {privacy_level} | "
        f"Corpus: {privacy.files_evaluated} files | "
        f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]",
        border_style="cyan",
    ))

    # ── Pillar 1: Privacy ──────────────────────────────────────────
    console.print("\n[bold yellow]▶ Pillar 1 — Privacy Leakage (PIR)[/bold yellow]")
    t = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t.add_column("File", style="cyan", min_width=24)
    t.add_column("SECRET Leakage", justify="right")
    t.add_column("VALUE Leakage", justify="right")
    t.add_column("Overall PIR", justify="right")
    t.add_column("✓", justify="center")

    for r in privacy.per_file:
        pir_color = "green" if r.overall_pir <= 0.05 else ("yellow" if r.overall_pir <= 0.20 else "red")
        t.add_row(
            r.file_name,
            f"{r.secret_leakage_rate:.1%}",
            f"{r.value_leakage_rate:.1%}",
            f"[{pir_color}]{r.overall_pir:.4f}[/{pir_color}]",
            "✓" if r.overall_pir <= 0.05 else "⚠",
        )

    t.add_section()
    avg_color = "green" if privacy.mean_pir <= 0.05 else "yellow"
    t.add_row(
        "[bold]MEAN[/bold]",
        f"[bold]{privacy.mean_secret_leakage:.1%}[/bold]",
        f"[bold]{privacy.mean_value_leakage:.1%}[/bold]",
        f"[bold][{avg_color}]{privacy.mean_pir:.4f}[/{avg_color}][/bold]",
        "",
    )
    console.print(t)
    console.print(f"  Syntax validity rate: [green]{privacy.syntax_validity_rate:.1%}[/green]")

    # ── Pillar 2: Reconstruction ───────────────────────────────────
    console.print("\n[bold yellow]▶ Pillar 2 — Reconstruction Fidelity (RF)[/bold yellow]")
    t2 = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t2.add_column("File", style="cyan", min_width=24)
    t2.add_column("Tokens", justify="right")
    t2.add_column("Hit Rate", justify="right")
    t2.add_column("Roundtrip Fidelity", justify="right")
    t2.add_column("Context Blocks", justify="center")

    for r in reconstruction.per_file:
        hr_color = "green" if r.token_hit_rate >= 0.95 else "yellow"
        t2.add_row(
            r.file_name,
            str(r.tokens_in_simulated_response),
            f"[{hr_color}]{r.token_hit_rate:.1%}[/{hr_color}]",
            f"{r.roundtrip_fidelity:.4f}",
            "✓" if r.has_context_blocks else "–",
        )

    t2.add_section()
    t2.add_row(
        "[bold]MEAN[/bold]",
        "–",
        f"[bold]{reconstruction.mean_token_hit_rate:.1%}[/bold]",
        f"[bold]{reconstruction.mean_roundtrip_fidelity:.4f}[/bold]",
        f"[bold]{reconstruction.context_block_rate:.1%}[/bold]",
    )
    console.print(t2)

    # ── Pillar 3: Classification ───────────────────────────────────
    console.print("\n[bold yellow]▶ Pillar 3 — Classification Accuracy (F1)[/bold yellow]")
    t3 = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t3.add_column("Class", style="cyan")
    t3.add_column("Precision", justify="right")
    t3.add_column("Recall", justify="right")
    t3.add_column("F1", justify="right")
    t3.add_column("Support", justify="right")

    for cls, metrics in classification.per_class.items():
        f1_color = "green" if metrics.f1 >= 0.85 else ("yellow" if metrics.f1 >= 0.70 else "red")
        t3.add_row(
            cls,
            f"{metrics.precision:.4f}",
            f"{metrics.recall:.4f}",
            f"[{f1_color}]{metrics.f1:.4f}[/{f1_color}]",
            str(metrics.support),
        )

    t3.add_section()
    macro_color = "green" if classification.macro_f1 >= 0.85 else "yellow"
    t3.add_row(
        "[bold]MACRO[/bold]",
        f"[bold]{classification.macro_precision:.4f}[/bold]",
        f"[bold]{classification.macro_recall:.4f}[/bold]",
        f"[bold][{macro_color}]{classification.macro_f1:.4f}[/{macro_color}][/bold]",
        str(classification.total_nodes),
    )
    console.print(t3)
    console.print(
        f"  Overall accuracy: [bold]{classification.overall_accuracy:.1%}[/bold]  "
        f"({classification.correctly_classified}/{classification.total_nodes} nodes correct)"
    )

    # Confusion matrix
    console.print("\n  [dim]Confusion Matrix (rows=true, cols=predicted):[/dim]")
    cm_table = Table(box=box.SIMPLE, show_header=True, header_style="dim")
    cm_table.add_column("True \\ Pred", style="dim")
    for cls in ["SECRET", "VALUE", "IDENTIFIER"]:
        cm_table.add_column(cls[:6], justify="right")
    for true_cls in ["SECRET", "VALUE", "IDENTIFIER"]:
        row = [true_cls]
        for pred_cls in ["SECRET", "VALUE", "IDENTIFIER"]:
            val = classification.confusion_matrix[true_cls][pred_cls]
            if true_cls == pred_cls:
                row.append(f"[green]{val}[/green]")
            else:
                row.append(f"[red]{val}[/red]" if val > 0 else "0")
        cm_table.add_row(*row)
    console.print(cm_table)

    # ── Pillar 4: Structure ────────────────────────────────────────
    console.print("\n[bold yellow]▶ Pillar 4 — Code Structure Preservation[/bold yellow]")
    t4 = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t4.add_column("File", style="cyan", min_width=24)
    t4.add_column("Syntax Valid", justify="center")
    t4.add_column("AST Isom.", justify="right")
    t4.add_column("CC Delta", justify="right")
    t4.add_column("Abstr. Density", justify="right")

    for r in structure.per_file:
        t4.add_row(
            r.file_name,
            "[green]✓[/green]" if r.syntax_valid else "[red]✗[/red]",
            f"{r.ast_isomorphism_score:.4f}",
            f"[green]{r.cyclomatic_complexity_delta}[/green]" if r.cyclomatic_complexity_delta == 0 else f"[yellow]{r.cyclomatic_complexity_delta}[/yellow]",
            f"{r.abstraction_density:.1%}",
        )

    t4.add_section()
    t4.add_row(
        "[bold]MEAN[/bold]",
        f"[bold]{structure.syntax_validity_rate:.1%}[/bold]",
        f"[bold]{structure.mean_ast_isomorphism:.4f}[/bold]",
        f"[bold]{structure.mean_complexity_delta:.2f}[/bold]",
        f"[bold]{structure.mean_abstraction_density:.1%}[/bold]",
    )
    console.print(t4)

    # ── Pillar 5: Performance ──────────────────────────────────────
    console.print("\n[bold yellow]▶ Pillar 5 — Performance[/bold yellow]")
    t5 = Table(box=box.SIMPLE_HEAVY, show_header=True, header_style="bold")
    t5.add_column("File", style="cyan", min_width=24)
    t5.add_column("LOC", justify="right")
    t5.add_column("Abstract (ms)", justify="right")
    t5.add_column("Reconstruct (ms)", justify="right")
    t5.add_column("Encrypt RT (ms)", justify="right")
    t5.add_column("Throughput (LOC/s)", justify="right")

    for r in performance.per_file:
        t5.add_row(
            r.file_name,
            str(r.loc),
            f"{r.abstraction_time_ms:.1f}",
            f"{r.reconstruction_time_ms:.1f}",
            f"{r.encryption_time_ms:.1f}",
            f"{r.throughput_loc_per_sec:,.0f}",
        )

    t5.add_section()
    t5.add_row(
        "[bold]MEAN[/bold]",
        "–",
        f"[bold]{performance.mean_abstraction_time_ms:.1f}[/bold]",
        f"[bold]{performance.mean_reconstruction_time_ms:.1f}[/bold]",
        f"[bold]{performance.mean_encryption_time_ms:.1f}[/bold]",
        f"[bold]{performance.mean_throughput_loc_per_sec:,.0f}[/bold]",
    )
    console.print(t5)

    # Scaling curve
    console.print("\n  [dim]Scaling Curve (LOC → Abstraction Time):[/dim]")
    for pt in performance.scaling_curve:
        bar_len = min(30, int(pt.abstraction_time_ms / 2))
        bar = "█" * bar_len
        console.print(
            f"  {pt.loc:>5} LOC │ {bar:<30} {pt.abstraction_time_ms:>7.1f} ms  "
            f"({pt.throughput_loc_per_sec:,.0f} LOC/s)"
        )

    # ── Summary Panel ──────────────────────────────────────────────
    console.print()
    summary_lines = [
        f"[bold]Privacy (PIR @ {privacy_level}):[/bold]  {_pir_badge(privacy.mean_pir)}",
        f"[bold]Reconstruction Fidelity:[/bold]   {_rf_badge(reconstruction.mean_token_hit_rate)}",
        f"[bold]Classification Macro-F1:[/bold]   {_f1_badge(classification.macro_f1)}",
        f"[bold]AST Isomorphism:[/bold]           {structure.mean_ast_isomorphism:.4f}  ({'✓ Perfect' if structure.mean_ast_isomorphism >= 1.0 else 'Near perfect'})",
        f"[bold]Syntax Validity:[/bold]           {structure.syntax_validity_rate:.1%}",
        f"[bold]Throughput:[/bold]                {performance.mean_throughput_loc_per_sec:,.0f} LOC/sec",
    ]
    console.print(Panel(
        "\n".join(summary_lines),
        title="[bold]Summary[/bold]",
        border_style="green",
    ))
    console.print()


def _pir_badge(pir: float) -> str:
    if pir <= 0.05:
        return f"[green]{pir:.4f} ✓ Excellent[/green]"
    elif pir <= 0.15:
        return f"[yellow]{pir:.4f} ⚠ Acceptable[/yellow]"
    return f"[red]{pir:.4f} ✗ Poor[/red]"


def _rf_badge(rf: float) -> str:
    if rf >= 0.95:
        return f"[green]{rf:.1%} ✓ Excellent[/green]"
    elif rf >= 0.80:
        return f"[yellow]{rf:.1%} ⚠ Acceptable[/yellow]"
    return f"[red]{rf:.1%} ✗ Poor[/red]"


def _f1_badge(f1: float) -> str:
    if f1 >= 0.85:
        return f"[green]{f1:.4f} ✓ Excellent[/green]"
    elif f1 >= 0.70:
        return f"[yellow]{f1:.4f} ⚠ Acceptable[/yellow]"
    return f"[red]{f1:.4f} ✗ Needs improvement[/red]"


# ═══════════════════════════════════════════════════════════════════
# JSON Report
# ═══════════════════════════════════════════════════════════════════

def save_json_report(
    privacy: PrivacySuiteResult,
    reconstruction: ReconstructionSuiteResult,
    classification: ClassificationResult,
    structure: StructureSuiteResult,
    performance: PerformanceSuiteResult,
    output_path: str,
    privacy_level: str = "high",
    mapping: Optional[MappingSuiteResult] = None,
    adversary: Optional[AdversarySuiteResult] = None,
) -> str:
    """Serialize all results to a JSON file and return the path."""
    report = {
        "meta": {
            "timestamp": datetime.now().isoformat(),
            "privacy_level": privacy_level,
            "files_evaluated": privacy.files_evaluated,
        },
        "pillar_1_privacy": {
            "mean_pir": privacy.mean_pir,
            "mean_secret_leakage_rate": privacy.mean_secret_leakage,
            "mean_value_leakage_rate": privacy.mean_value_leakage,
            "mean_identifier_leakage_rate": privacy.mean_identifier_leakage,
            "syntax_validity_rate": privacy.syntax_validity_rate,
            "per_file": [
                {
                    "file": r.file_name,
                    "overall_pir": r.overall_pir,
                    "secret_leakage_rate": r.secret_leakage_rate,
                    "value_leakage_rate": r.value_leakage_rate,
                    "secret_total": r.secret_total,
                    "secret_abstracted": r.secret_abstracted,
                    "value_total": r.value_total,
                    "value_abstracted": r.value_abstracted,
                }
                for r in privacy.per_file
            ],
        },
        "pillar_2_reconstruction": {
            "mean_token_hit_rate": reconstruction.mean_token_hit_rate,
            "mean_replacement_accuracy": reconstruction.mean_replacement_accuracy,
            "mean_roundtrip_fidelity": reconstruction.mean_roundtrip_fidelity,
            "context_block_rate": reconstruction.context_block_rate,
            "mean_reconstruction_rate": reconstruction.mean_reconstruction_rate,
            "per_file": [
                {
                    "file": r.file_name,
                    "tokens_generated": r.total_tokens_generated,
                    "token_hit_rate": r.token_hit_rate,
                    "roundtrip_fidelity": r.roundtrip_fidelity,
                    "has_context_blocks": r.has_context_blocks,
                }
                for r in reconstruction.per_file
            ],
        },
        "pillar_3_classification": {
            "overall_accuracy": classification.overall_accuracy,
            "macro_f1": classification.macro_f1,
            "macro_precision": classification.macro_precision,
            "macro_recall": classification.macro_recall,
            "total_nodes": classification.total_nodes,
            "correctly_classified": classification.correctly_classified,
            "per_class": {
                cls: {
                    "precision": m.precision,
                    "recall": m.recall,
                    "f1": m.f1,
                    "support": m.support,
                    "true_positives": m.true_positives,
                    "false_positives": m.false_positives,
                    "false_negatives": m.false_negatives,
                }
                for cls, m in classification.per_class.items()
            },
            "confusion_matrix": classification.confusion_matrix,
            "domain_accuracy": classification.domain_accuracy,
        },
        "pillar_4_structure": {
            "syntax_validity_rate": structure.syntax_validity_rate,
            "mean_ast_isomorphism": structure.mean_ast_isomorphism,
            "mean_complexity_delta": structure.mean_complexity_delta,
            "mean_token_ratio": structure.mean_token_ratio,
            "mean_abstraction_density": structure.mean_abstraction_density,
            "per_file": [
                {
                    "file": r.file_name,
                    "syntax_valid": r.syntax_valid,
                    "ast_isomorphism_score": r.ast_isomorphism_score,
                    "cyclomatic_complexity_delta": r.cyclomatic_complexity_delta,
                    "abstraction_density": r.abstraction_density,
                }
                for r in structure.per_file
            ],
        },
        "pillar_6_mapping": ({
            "mean_mapping_accuracy": mapping.mean_mapping_accuracy,
            "mean_definition_accuracy": mapping.mean_definition_accuracy,
            "mean_occurrence_accuracy": mapping.mean_occurrence_accuracy,
            "mean_shadow_resolution": mapping.mean_shadow_resolution,
            "mean_line_map_accuracy": mapping.mean_line_map_accuracy,
            "total_shadowed_names": mapping.total_shadowed_names,
            "per_file": [
                {
                    "file_name": r.file_name,
                    "definition_accuracy": r.definition_accuracy,
                    "occurrence_accuracy": r.occurrence_accuracy,
                    "shadow_resolution": r.shadow_resolution,
                    "line_map_accuracy": r.line_map_accuracy,
                    "mapping_accuracy": r.mapping_accuracy,
                }
                for r in mapping.per_file
            ],
        } if mapping is not None else None),
        "pillar_5_performance": {
            "mean_abstraction_time_ms": performance.mean_abstraction_time_ms,
            "mean_reconstruction_time_ms": performance.mean_reconstruction_time_ms,
            "mean_encryption_time_ms": performance.mean_encryption_time_ms,
            "mean_pipeline_time_ms": performance.mean_pipeline_time_ms,
            "mean_throughput_loc_per_sec": performance.mean_throughput_loc_per_sec,
            "peak_throughput_loc_per_sec": performance.peak_throughput_loc_per_sec,
            "scaling_curve": [
                {"loc": p.loc, "abstraction_time_ms": p.abstraction_time_ms,
                 "throughput_loc_per_sec": p.throughput_loc_per_sec}
                for p in performance.scaling_curve
            ],
            "per_file": [
                {
                    "file": r.file_name,
                    "loc": r.loc,
                    "abstraction_time_ms": r.abstraction_time_ms,
                    "reconstruction_time_ms": r.reconstruction_time_ms,
                    "throughput_loc_per_sec": r.throughput_loc_per_sec,
                }
                for r in performance.per_file
            ],
        },
    }

    json_path = os.path.join(output_path, "evaluation_results.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)
    return json_path


# ═══════════════════════════════════════════════════════════════════
# Markdown Report
# ═══════════════════════════════════════════════════════════════════

def _dataset_integrity_markdown() -> list:
    """
    Render the dataset-integrity section (Phase 2).

    Placed directly under the classification pillar so that nobody reads
    the macro-F1 without also reading how much of it the patterns under
    test already determine.
    """
    try:
        from evaluation.benchmarks.annotation import (
            circularity_report, load_legacy_dataset,
        )
        audit = circularity_report(load_legacy_dataset())
    except Exception:
        return []

    lines = ["\n---\n", "## Dataset Integrity (Pillar 3 caveat)\n"]
    lines.append(
        "The classification F1 above is computed on a dataset whose labels "
        "were derived from the same patterns it grades. These figures "
        "measure how far that compromises the result.\n"
    )
    lines.append("| Check | Value | Reading |")
    lines.append("|-------|-------|---------|")
    lines.append(
        f"| Regex baseline accuracy | {audit.baseline_accuracy:.4f} | "
        f"the score any name-regex achieves by construction |"
    )
    lines.append(
        f"| Discriminative power | {audit.discriminative_power:.4f} | "
        f"only {audit.discriminative_items} of {audit.n_items} items can "
        f"separate two detectors |"
    )
    lines.append(
        f"| Rationale leakage | {audit.rationale_leakage:.4f} | "
        f"share of labels justified by quoting the pattern list |"
    )
    lines.append(
        f"| Annotated blind | {audit.blind_fraction:.4f} | "
        f"share labelled without sight of the patterns |"
    )
    lines.append(
        f"| Provenance recorded | {audit.sourced_fraction:.4f} | "
        f"share traceable to real-world code |"
    )
    lines.append(
        f"\n**Usable for detector comparison:** "
        f"{'yes' if audit.is_usable else 'no'}\n"
    )
    for note in audit.notes:
        lines.append(f"- {note}")
    return lines


def _adversary_markdown(adversary) -> list:
    """Render the Pillar 7 section (Phase 3)."""
    if adversary is None:
        return []

    lines = ["\n---\n", "## Pillar 7 - Adversarial Re-identification\n"]
    lines.append(
        "An attacker holding the original files and one abstracted file "
        "tries to say which file it came from. Structure survives "
        "abstraction by design, so this measures what that design costs.\n"
    )
    lines.append(
        "| Privacy level | Top-1 | Top-3 | MRR | CPE | Advantage over chance | Identifiers surviving |"
    )
    lines.append("|---|---|---|---|---|---|---|")
    for level, report in adversary.per_level.items():
        lines.append(
            f"| `{level}` | {report.top1_accuracy:.3f} | {report.top3_accuracy:.3f} | "
            f"{report.mean_reciprocal_rank:.3f} | {report.code_privacy_entropy:.4f} | "
            f"{report.advantage:.3f} | "
            f"{adversary.mean_survival_rate.get(level, 0):.3f} |"
        )

    any_report = next(iter(adversary.per_level.values()), None)
    if any_report is not None:
        lines.append(
            f"\nRandom-guess baseline: {any_report.random_baseline:.4f} "
            f"({any_report.n_files} candidates). "
            f"CPE 1.0 = attacker learned nothing; 0.0 = attacker is certain.\n"
        )
        lines.append(f"**Verdict:** {any_report.verdict()}\n")

    lines.append(
        "The token scheme also labels its own findings: `SECRET_n` marks "
        "where a credential sat, which the original identifier may not have "
        "revealed. Mean SECRET tokens per file, by level:\n"
    )
    for level, count in adversary.mean_secret_positions.items():
        lines.append(f"- `{level}`: {count:.1f}")
    return lines


def _mapping_markdown(mapping) -> list:
    """Render the Pillar 6 section (Phase 1)."""
    if mapping is None:
        return []

    lines = ["\n---\n", "## Pillar 6 — Mapping Accuracy\n"]
    lines.append(f"**Mean Mapping Accuracy**: {mapping.mean_mapping_accuracy:.4f}  ")
    lines.append(f"**Definition-Site Accuracy**: {mapping.mean_definition_accuracy:.4f}  ")
    lines.append(f"**Occurrence Accuracy**: {mapping.mean_occurrence_accuracy:.4f}  ")
    lines.append(f"**Shadow Resolution**: {mapping.mean_shadow_resolution:.4f}  ")
    lines.append(f"**Line-Map Accuracy**: {mapping.mean_line_map_accuracy:.4f}\n")
    lines.append("| File | Definition | Occurrence | Shadow | Line Map | Overall |")
    lines.append("|------|-----------|-----------|--------|----------|---------|")
    for r in mapping.per_file:
        lines.append(
            f"| {r.file_name} | {r.definition_accuracy:.3f} | {r.occurrence_accuracy:.3f} | "
            f"{r.shadow_resolution:.3f} | {r.line_map_accuracy:.3f} | {r.mapping_accuracy:.3f} |"
        )
    return lines


def save_markdown_report(
    privacy: PrivacySuiteResult,
    reconstruction: ReconstructionSuiteResult,
    classification: ClassificationResult,
    structure: StructureSuiteResult,
    performance: PerformanceSuiteResult,
    output_path: str,
    privacy_level: str = "high",
    mapping: Optional[MappingSuiteResult] = None,
    adversary: Optional[AdversarySuiteResult] = None,
) -> str:
    """Save a full Markdown evaluation report and return the path."""
    lines = []

    lines.append("# CodeAbstract — Evaluation Report")
    lines.append(f"\n> Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ")
    lines.append(f"> Privacy Level: `{privacy_level}`  ")
    lines.append(f"> Corpus: {privacy.files_evaluated} files | Labeled dataset: {classification.total_nodes} nodes\n")

    lines.append("---\n")
    lines.append("## Summary\n")
    lines.append("| Metric | Value | Target | Status |")
    lines.append("|--------|-------|--------|--------|")
    lines.append(f"| Privacy Information Ratio (PIR) | {privacy.mean_pir:.4f} | ≤ 0.05 | {'✅' if privacy.mean_pir <= 0.05 else '⚠️'} |")
    lines.append(f"| Token Hit Rate (Reconstruction) | {reconstruction.mean_token_hit_rate:.1%} | ≥ 95% | {'✅' if reconstruction.mean_token_hit_rate >= 0.95 else '⚠️'} |")
    lines.append(f"| Classification Macro-F1 | {classification.macro_f1:.4f} | ≥ 0.85 | {'✅' if classification.macro_f1 >= 0.85 else '⚠️'} |")
    lines.append(f"| AST Isomorphism Score | {structure.mean_ast_isomorphism:.4f} | 1.00 | {'✅' if structure.mean_ast_isomorphism >= 0.99 else '⚠️'} |")
    lines.append(f"| Syntax Validity Rate | {structure.syntax_validity_rate:.1%} | 100% | {'✅' if structure.syntax_validity_rate == 1.0 else '❌'} |")
    lines.append(f"| Throughput (LOC/sec) | {performance.mean_throughput_loc_per_sec:,.0f} | ≥ 1,000 | {'✅' if performance.mean_throughput_loc_per_sec >= 1000 else '⚠️'} |")
    if mapping is not None:
        lines.append(f"| Mapping Accuracy | {mapping.mean_mapping_accuracy:.4f} | ≥ 0.85 | {'✅' if mapping.mean_mapping_accuracy >= 0.85 else '⚠️'} |")

    lines.append("\n---\n")
    lines.append("## Pillar 1 — Privacy Leakage (PIR)\n")
    lines.append("| File | SECRET Leakage | VALUE Leakage | PIR |")
    lines.append("|------|---------------|--------------|-----|")
    for r in privacy.per_file:
        lines.append(f"| {r.file_name} | {r.secret_leakage_rate:.1%} | {r.value_leakage_rate:.1%} | {r.overall_pir:.4f} |")
    lines.append(f"| **Mean** | **{privacy.mean_secret_leakage:.1%}** | **{privacy.mean_value_leakage:.1%}** | **{privacy.mean_pir:.4f}** |")

    lines.append("\n---\n")
    lines.append("## Pillar 2 — Reconstruction Fidelity\n")
    lines.append("| File | Tokens | Hit Rate | Roundtrip Fidelity |")
    lines.append("|------|--------|----------|--------------------|")
    for r in reconstruction.per_file:
        lines.append(f"| {r.file_name} | {r.total_tokens_generated} | {r.token_hit_rate:.1%} | {r.roundtrip_fidelity:.4f} |")
    lines.append(f"| **Mean** | – | **{reconstruction.mean_token_hit_rate:.1%}** | **{reconstruction.mean_roundtrip_fidelity:.4f}** |")

    lines.append("\n---\n")
    lines.append("## Pillar 3 — Classification Accuracy\n")
    lines.append(f"**Overall Accuracy**: {classification.overall_accuracy:.1%}  ({classification.correctly_classified}/{classification.total_nodes} nodes)  ")
    lines.append(f"**Macro F1**: {classification.macro_f1:.4f}\n")
    lines.append("| Class | Precision | Recall | F1 | Support |")
    lines.append("|-------|-----------|--------|----|---------|")
    for cls, m in classification.per_class.items():
        lines.append(f"| {cls} | {m.precision:.4f} | {m.recall:.4f} | {m.f1:.4f} | {m.support} |")
    lines.append(f"| **Macro** | **{classification.macro_precision:.4f}** | **{classification.macro_recall:.4f}** | **{classification.macro_f1:.4f}** | {classification.total_nodes} |")

    lines.append("\n### Confusion Matrix\n")
    lines.append("| True \\ Predicted | SECRET | VALUE | IDENTIFIER |")
    lines.append("|-----------------|--------|-------|------------|")
    for true_cls in ["SECRET", "VALUE", "IDENTIFIER"]:
        row = " | ".join(
            str(classification.confusion_matrix[true_cls][pred_cls])
            for pred_cls in ["SECRET", "VALUE", "IDENTIFIER"]
        )
        lines.append(f"| {true_cls} | {row} |")

    lines.append("\n---\n")
    lines.append("## Pillar 4 — Code Structure Preservation\n")
    lines.append(f"**Syntax Validity Rate**: {structure.syntax_validity_rate:.1%}  ")
    lines.append(f"**Mean AST Isomorphism**: {structure.mean_ast_isomorphism:.4f}  ")
    lines.append(f"**Mean Cyclomatic Complexity Delta**: {structure.mean_complexity_delta:.2f}\n")
    lines.append("| File | Syntax Valid | AST Isom. | CC Delta | Abstr. Density |")
    lines.append("|------|-------------|-----------|----------|----------------|")
    for r in structure.per_file:
        lines.append(
            f"| {r.file_name} | {'✅' if r.syntax_valid else '❌'} "
            f"| {r.ast_isomorphism_score:.4f} "
            f"| {r.cyclomatic_complexity_delta} "
            f"| {r.abstraction_density:.1%} |"
        )

    lines.append("\n---\n")
    lines.append("## Pillar 5 — Performance\n")
    lines.append(f"**Mean Throughput**: {performance.mean_throughput_loc_per_sec:,.0f} LOC/sec  ")
    lines.append(f"**Mean Abstraction Time**: {performance.mean_abstraction_time_ms:.1f} ms  ")
    lines.append(f"**Mean Encryption Round-trip**: {performance.mean_encryption_time_ms:.1f} ms\n")
    lines.append("| File | LOC | Abstract (ms) | Reconstruct (ms) | Throughput (LOC/s) |")
    lines.append("|------|-----|--------------|-----------------|-------------------|")
    for r in performance.per_file:
        lines.append(
            f"| {r.file_name} | {r.loc} "
            f"| {r.abstraction_time_ms:.1f} "
            f"| {r.reconstruction_time_ms:.1f} "
            f"| {r.throughput_loc_per_sec:,.0f} |"
        )

    lines.append("\n### Scaling Curve\n")
    lines.append("| LOC | Abstraction Time (ms) | Throughput (LOC/s) |")
    lines.append("|-----|----------------------|-------------------|")
    for pt in performance.scaling_curve:
        lines.append(f"| {pt.loc} | {pt.abstraction_time_ms:.1f} | {pt.throughput_loc_per_sec:,.0f} |")

    lines.extend(_mapping_markdown(mapping))
    lines.extend(_adversary_markdown(adversary))
    lines.extend(_dataset_integrity_markdown())

    md_path = os.path.join(output_path, "evaluation_report.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return md_path
