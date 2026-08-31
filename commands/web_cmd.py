"""
CLI Command: web

Phase 5. Starts the local web interface.

The one decision this command makes on the user's behalf is refusing to
bind anywhere except loopback without being told to. Accounts (web/auth.py)
scope one signed-in user's sessions away from another's, but they do not
gate the port: whoever can reach it can sign up their own account, abstract
code, spend the operator's configured LLM provider quota, and read any
session nobody ever signed into (every session the CLI writes, among
others). On ``127.0.0.1`` that is exactly the CLI's own trust boundary. On
``0.0.0.0`` it is the network's, which is a different program than the one
the user asked for — so ``--expose`` has to be typed, and ``--tls`` is
there for when plaintext HTTP across that network is not acceptable either.
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
    tls: bool = False,
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
            "[yellow]Signing in only protects one account's sessions from "
            "another's -- it does not stop a stranger who reaches this port "
            "from creating their own account, spending your configured LLM "
            "provider's quota, or reading any session nobody signed into "
            "(every CLI-written one included).\n"
            "Pass --expose if that is what you want.[/yellow]"
        )
        raise typer.Exit(1)

    if not is_loopback(host) and expose and not tls:
        # Refusing outright here would break the one thing --expose is
        # for: a deliberate choice already made and typed out. A warning
        # loud enough to not be scrolled past is the honest middle ground
        # -- --tls costs one more flag and turns this into an HTTPS server.
        console.print(
            "[red]⚠ Serving over plain HTTP on a non-loopback address.[/red]\n"
            "[yellow]Every login and every abstracted line of code crosses "
            "the network in the clear until this is HTTPS. Add --tls for a "
            "self-signed certificate (fine for personal/LAN use), or put a "
            "real TLS-terminating proxy in front of this port.[/yellow]"
        )

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

    scheme = 'https' if tls else 'http'
    console.print(Panel(
        f"[bold cyan]CodeAbstract Web[/bold cyan]\n"
        f"[dim]{scheme}://{host}:{port}[/dim]\n\n"
        f"Sessions: {'not saved' if no_save else 'saved locally'}\n"
        f"Secret values: {'revealable' if allow_reveal else 'always masked'}\n"
        f"Transport: {'HTTPS (self-signed)' if tls else 'HTTP'}"
    ))

    # 'adhoc' asks Werkzeug to generate a throwaway self-signed certificate
    # using `cryptography`, already a core dependency -- no new package,
    # and no certificate to provision for a personal or LAN-only server.
    # Browsers will warn about it; that warning is honest; it is not a
    # certificate a stranger's browser should ever trust silently.
    run_kwargs = {'host': host, 'port': port, 'debug': debug}
    if tls:
        run_kwargs['ssl_context'] = 'adhoc'
    app.run(**run_kwargs)
