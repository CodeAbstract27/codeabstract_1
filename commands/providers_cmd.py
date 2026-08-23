"""
CLI Command: providers

Phase 4. Shows which LLM providers are ready to use, and runs the same file
through several of them for comparison.

``providers list`` reports installation and key presence separately: "no
package" and "no key" need different fixes, and a single "unavailable"
column sends the user looking in the wrong place.
"""

import json
from pathlib import Path
from typing import List, Optional

import typer
from rich.box import ROUNDED
from rich.table import Table

from ui.console import get_console
from utils.file_io import read_file, write_file


def run_providers_list():
    """Show every provider's readiness."""
    from llm import PROVIDER_NAMES, provider_status

    console = get_console()
    statuses = provider_status()

    table = Table(
        title="LLM providers",
        show_header=True, header_style="bold #d77757",
        border_style="dim", box=ROUNDED,
    )
    table.add_column("Provider", style="accent")
    table.add_column("Package")
    table.add_column("API key")
    table.add_column("Model", style="white")
    table.add_column("Environment variable", style="muted")

    for status in statuses:
        table.add_row(
            status['provider'] + (" (default)" if status['is_default'] else ""),
            "[success]installed[/success]" if status['installed']
            else f"[warning]pip install 'codeabstract[{status['extra']}]'[/warning]",
            "[success]found[/success]" if status['has_key']
            else "[warning]not set[/warning]",
            status['model'],
            " / ".join(status['env_vars']),
        )

    console.print(table)

    ready = [s['provider'] for s in statuses if s['installed'] and s['has_key']]
    if not ready:
        console.print(
            "[warning]No provider is ready. Install one and set its key.[/warning]"
        )
    elif len(ready) > 1:
        console.print(
            f"[info]Ready: {', '.join(ready)}. Pick one per run with "
            f"--provider, or set a default:[/info]\n"
            f"  [accent]codeabstract config set default_provider <name>[/accent]"
        )
    else:
        console.print(f"[success]✓ Ready: {ready[0]}[/success]")

    console.print(f"[muted]Supported: {', '.join(PROVIDER_NAMES)}[/muted]")


def run_providers_compare(
    file: str,
    providers: Optional[str] = None,
    task: str = "review",
    privacy: str = "high",
    query: Optional[str] = None,
    output: Optional[str] = None,
):
    """
    Review one file through several providers and compare the answers.

    Args:
        file: Source file to review.
        providers: Comma-separated provider names; every ready provider if
            omitted.
        task: Preset task name.
        privacy: Privacy level.
        query: Free-form question instead of a preset.
        output: Write the full comparison to this JSON file.
    """
    from evaluation.providers import compare_providers
    from llm import ProviderError, available_providers, create_client

    console = get_console()

    file_path = Path(file)
    if not file_path.exists():
        console.print(f"[error]✗ File not found: {file}[/error]")
        raise typer.Exit(1)

    if file_path.is_dir():
        console.print(f"[error]✗ '{file}' is a directory, not a file.[/error]")
        raise typer.Exit(1)

    from core.languages import detect_language
    language = detect_language(file_path)
    if language is None:
        console.print(f"[error]✗ No language adapter for '{file_path.suffix}'[/error]")
        raise typer.Exit(1)

    names: List[str] = (
        [p.strip() for p in providers.split(',') if p.strip()]
        if providers else available_providers()
    )
    if not names:
        console.print(
            "[error]✗ No provider is ready.[/error] "
            "Run [accent]codeabstract providers list[/accent] to see why."
        )
        raise typer.Exit(1)

    clients = []
    for name in names:
        try:
            clients.append(create_client(provider=name))
        except ProviderError as exc:
            console.print(f"[warning]⚠ Skipping {name}: {exc}[/warning]")

    if not clients:
        console.print("[error]✗ No usable providers.[/error]")
        raise typer.Exit(1)

    console.print(
        f"[info]Reviewing {file} through "
        f"{', '.join(c.provider for c in clients)}…[/info]"
    )

    corpus = [{
        'name': file_path.name,
        'code': read_file(file_path),
        'language': language,
    }]

    comparison = compare_providers(
        files=corpus, clients=clients, task=task,
        privacy_level=privacy, query=query,
    )

    table = Table(
        title=f"Provider comparison — {file_path.name} ({privacy})",
        show_header=True, header_style="bold #d77757",
        border_style="dim", box=ROUNDED,
    )
    table.add_column("Provider", style="accent")
    table.add_column("Model", style="white")
    table.add_column("OK", justify="right")
    table.add_column("Token fidelity", justify="right")
    table.add_column("Lines resolvable", justify="right")
    table.add_column("Seconds", justify="right")
    table.add_column("Tokens in/out", justify="right")

    for scores in comparison.per_provider:
        usage = (
            f"{scores.total_prompt_tokens}/{scores.total_completion_tokens}"
            if scores.tokens_reported else "not reported"
        )
        table.add_row(
            scores.provider, scores.model,
            f"{scores.successes}/{scores.files}",
            f"{scores.token_fidelity:.2f}",
            f"{scores.line_resolvability:.2f}",
            f"{scores.mean_response_time:.1f}",
            usage,
        )

    console.print(table)

    if comparison.finding_agreement:
        agreement = Table(
            title="Agreement between providers",
            show_header=True, header_style="bold #d77757",
            border_style="dim", box=ROUNDED,
        )
        agreement.add_column("Pair", style="accent")
        agreement.add_column("Issue terms", justify="right")
        agreement.add_column("Cited lines", justify="right")
        for pair, value in comparison.finding_agreement.items():
            agreement.add_row(
                pair.replace('|', ' vs '),
                f"{value:.2f}",
                f"{comparison.line_agreement.get(pair, 0.0):.2f}",
            )
        console.print(agreement)

    console.print(f"[muted]{comparison.caveat()}[/muted]")

    for result in comparison.results:
        if not result.success:
            console.print(
                f"[warning]⚠ {result.provider} failed: {result.error}[/warning]"
            )

    if output:
        try:
            write_file(
                Path(output),
                json.dumps(comparison.to_dict(), indent=2, ensure_ascii=False),
            )
            console.print(f"[success]💾 Comparison saved: {output}[/success]")
        except Exception as exc:
            console.print(f"[error]✗ Failed to save comparison: {exc}[/error]")


def run_languages_list():
    """Show which language adapters are usable on this machine."""
    from core.languages import adapter_info

    console = get_console()

    table = Table(
        title="Language adapters",
        show_header=True, header_style="bold #d77757",
        border_style="dim", box=ROUNDED,
    )
    table.add_column("Language", style="accent")
    table.add_column("Extensions", style="white")
    table.add_column("Status")

    for info in adapter_info():
        table.add_row(
            info.language,
            " ".join(info.extensions),
            "[success]available[/success]" if info.available
            else f"[warning]{info.reason}[/warning]",
        )

    console.print(table)
