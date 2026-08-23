"""
CLI Command: web

Phase 5. Starts the local web interface.

The one decision this command makes on the user's behalf is refusing to
bind anywhere except loopback without being told to. Nothing in the web app
authenticates a caller: whoever can reach the port can abstract code, read
every stored session's vault, and delete sessions. On ``127.0.0.1`` that is
exactly the CLI's own trust boundary. On ``0.0.0.0`` it is the network's,
which is a different program than the one the user asked for — so
``--expose`` has to be typed.
"""

import ipaddress

import typer
from rich.panel import Panel

from ui.console import get_console

console = get_console()


def is_loopback(host: str) -> bool:
    """
    True if *host* can only be reached from this machine.

    Hostnames other than ``localhost`` resolve at bind time and could point
    anywhere, so anything unrecognised is treated as exposed. Erring
    towards asking is cheap; erring the other way publishes the vault.
    """
    name = (host or '').strip().lower()
    if name in ('localhost', ''):
        return True
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return False


def run_web(
    host: str = "127.0.0.1",
    port: int = 5000,
    debug: bool = False,
    no_save: bool = False,
    allow_reveal: bool = False,
    expose: bool = False,
) -> None:
    """Execute the web command."""
    try:
        from web import create_app
    except RuntimeError as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)

    if not is_loopback(host) and not expose:
        console.print(
            f"[red]✗ Refusing to bind {host}.[/red]\n"
            "[yellow]The web interface has no authentication: anyone who can "
            "reach the port can read every stored session's mapping table.\n"
            "Pass --expose if that is what you want.[/yellow]"
        )
        raise typer.Exit(1)

    if debug:
        # Werkzeug's debugger executes arbitrary code from the browser on a
        # traceback. In a process holding decrypted mapping tables, that is
        # worth one line of warning.
        console.print(
            "[yellow]⚠ Debug mode enables the interactive debugger — "
            "do not use it on a shared machine.[/yellow]"
        )

    app = create_app({
        'SAVE_SESSIONS': not no_save,
        'ALLOW_REVEAL': allow_reveal,
    })

    console.print(Panel(
        f"[bold cyan]CodeAbstract Web[/bold cyan]\n"
        f"[dim]http://{host}:{port}[/dim]\n\n"
        f"Sessions: {'not saved' if no_save else 'saved locally'}\n"
        f"Secret values: {'revealable' if allow_reveal else 'always masked'}"
    ))

    app.run(host=host, port=port, debug=debug)
