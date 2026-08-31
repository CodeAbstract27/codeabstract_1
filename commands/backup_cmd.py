"""
CLI Command: backup / restore

Everything CodeAbstract keeps locally -- sessions.db, the key directory,
audit.log and config.json -- lives under one directory (see
config.settings.get_app_dir()). Lose that directory and every session's
mapping table is gone at once: the encrypted ciphertext and the keys that
unlock it disappear together. That is the "what happens if I lose this
machine" gap these two commands close.

A backup is a plain zip of the whole application directory. It is
deliberately not a weaker copy of the data: the archive contains the same
Fernet keys that decrypt every session in it, so a copy of the backup is
exactly as sensitive as the original directory and should be handled (and
eventually deleted) with that in mind -- this module says so out loud
rather than let a user find out the hard way.
"""

import shutil
import zipfile
from pathlib import Path
from typing import Iterator, List, Tuple

import typer
from rich.box import ROUNDED
from rich.panel import Panel

from config.settings import get_app_dir
from ui.console import get_console


def run_backup(output: str) -> None:
    """Zip the whole application directory to *output*."""
    console = get_console()
    app_dir = get_app_dir().resolve()

    output_path = Path(output).expanduser()
    if output_path.suffix.lower() != '.zip':
        output_path = output_path.with_suffix(output_path.suffix + '.zip')
    output_path = output_path.resolve()

    if _is_inside(output_path, app_dir):
        console.print(
            f"[error]✗ Refusing to write the backup inside {app_dir} -- "
            "that would zip the archive into itself.[/error]"
        )
        raise typer.Exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    file_count = 0
    with zipfile.ZipFile(output_path, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in app_dir.rglob('*'):
            if path.is_file():
                archive.write(path, path.relative_to(app_dir))
                file_count += 1

    if file_count == 0:
        console.print(f"[warning]Nothing to back up -- {app_dir} is empty.[/warning]")

    size_kib = output_path.stat().st_size / 1024
    console.print(Panel(
        f"[success]Backed up {file_count} file(s) "
        f"({size_kib:.1f} KiB) to {output_path}[/success]\n\n"
        "[warning]This archive holds the keys that decrypt every session "
        "in it. Store it like a credential, not like a document -- an "
        "encrypted backup volume or a password manager's file storage, "
        "never an unencrypted USB drive or a shared folder.[/warning]",
        title="Backup complete", border_style="#d77757", box=ROUNDED,
    ))


def _is_inside(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
        return True
    except ValueError:
        return False


def _safe_members(
    archive: zipfile.ZipFile, target: Path,
) -> Iterator[Tuple[zipfile.ZipInfo, Path]]:
    """
    Yield ``(member, destination)`` pairs, refusing any entry that would
    write outside *target*.

    ``ZipFile.extractall()`` does not check this: a crafted entry named
    e.g. ``../../etc/cron.d/x`` extracts wherever its resolved path lands
    (the "Zip Slip" class of vulnerability). A backup is something a user
    might copy to another machine or receive from someone else, so by the
    time it reaches ``restore`` it is untrusted input, not just a file
    this same module wrote a moment ago.
    """
    for member in archive.infolist():
        destination = (target / member.filename).resolve()
        if not _is_inside(destination, target):
            raise ValueError(f"unsafe path in archive, refusing to restore: {member.filename!r}")
        yield member, destination


def run_restore(input: str, force: bool = False) -> None:
    """Restore the application directory from a backup made by `backup`."""
    console = get_console()
    input_path = Path(input).expanduser().resolve()

    if not input_path.is_file():
        console.print(f"[error]✗ No such file: {input_path}[/error]")
        raise typer.Exit(1)

    app_dir = get_app_dir().resolve()
    existing_files = [p for p in app_dir.rglob('*') if p.is_file()]

    if existing_files and not force:
        console.print(
            f"[warning]{app_dir} already has {len(existing_files)} file(s) in it. "
            "Restoring overwrites any file the backup also names -- sessions, "
            "keys, and the audit log alike.[/warning]"
        )
        if not typer.confirm("Continue?"):
            console.print("[info]Cancelled.[/info]")
            raise typer.Exit(0)

    try:
        with zipfile.ZipFile(input_path) as archive:
            members: List[Tuple[zipfile.ZipInfo, Path]] = list(
                _safe_members(archive, app_dir)
            )
            for member, destination in members:
                if member.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, open(destination, 'wb') as handle:
                    shutil.copyfileobj(source, handle)
    except (zipfile.BadZipFile, ValueError) as exc:
        console.print(f"[error]✗ {exc}[/error]")
        raise typer.Exit(1)

    restored = sum(1 for member, _ in members if not member.is_dir())
    console.print(Panel(
        f"[success]Restored {restored} file(s) to {app_dir}[/success]",
        title="Restore complete", border_style="#d77757", box=ROUNDED,
    ))
