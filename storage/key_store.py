"""
Session Key Storage

Phase 4 — the "key handling" workstream.

Until this module existed, ``sessions.db`` held the Fernet key in the same
row as the ciphertext it unlocks:

    encrypted_mapping BLOB NOT NULL,
    encryption_key    BLOB NOT NULL,

That is encoding, not protection. Anyone who can read the database file can
decrypt every mapping table in it — which contains, by construction, every
original identifier and every value the detector redacted. The encryption
was doing no work at all.

Here the key moves out of the database and the row keeps only a *reference*
to it. Two backends:

* **OS keychain** (``keyring``) — Windows Credential Manager, macOS
  Keychain, Secret Service on Linux. The key is protected by the user's
  login session and never touches the project directory.
* **Key directory** (``~/.codeabstract/keys``) — the fallback when no
  keychain backend is available, e.g. a headless Linux box with no
  Secret Service. Files are written with owner-only permissions where the
  platform honours them.

The fallback is **weaker and says so**: anyone who can read the key
directory can decrypt the mappings, exactly as before. What it does still
buy is separation — copying, syncing or backing up ``sessions.db`` alone no
longer carries the keys with it, which is the realistic exposure path.

Sessions written before Phase 4 still have their key in the database and
keep working unchanged; :func:`migrate_legacy_keys` moves them out on
request rather than silently rewriting a user's database.
"""

import os
import stat
from pathlib import Path
from typing import List, Optional, Protocol, Tuple

from config.settings import get_config, get_key_store_dir

# Service name under which keys are filed in the OS keychain.
KEYRING_SERVICE = "codeabstract"

# A reference is "<backend>:<locator>".  Storing the backend in the
# reference means a database written on a machine with a keychain is
# readable as such on a machine without one -- it reports a missing key
# rather than looking in the wrong place and reporting corruption.
KEYRING_PREFIX = "keyring:"
FILE_PREFIX = "file:"


class KeyStoreError(RuntimeError):
    """Raised when a key cannot be stored or retrieved."""


class KeyStore(Protocol):
    """Where a session's Fernet key lives."""

    backend: str

    def store(self, session_id: str, key: bytes) -> str:
        """Save *key* and return the reference to record in the database."""
        ...

    def load(self, reference: str) -> bytes:
        """Retrieve a key by reference."""
        ...

    def delete(self, reference: str) -> bool:
        """Remove a key. True if one was removed."""
        ...


# ═══════════════════════════════════════════════════════════
# OS keychain
# ═══════════════════════════════════════════════════════════

def keyring_available() -> bool:
    """
    True if ``keyring`` is installed *and* has a backend that can store.

    The package always imports; with no platform backend it installs a
    ``fail.Keyring`` that raises on every call. Treating "installed" as
    "usable" would push that failure to the first save, after the code has
    already been abstracted.
    """
    try:
        import keyring
        from keyring.backends import fail
    except ImportError:
        return False

    try:
        return not isinstance(keyring.get_keyring(), fail.Keyring)
    except Exception:  # pragma: no cover - misconfigured backend
        return False


class KeyringKeyStore:
    """Keys in the operating system's credential store."""

    backend = "keyring"

    def store(self, session_id: str, key: bytes) -> str:
        import keyring

        try:
            keyring.set_password(KEYRING_SERVICE, session_id, key.decode('utf-8'))
        except Exception as exc:
            raise KeyStoreError(f"could not write key to the OS keychain: {exc}") from exc
        return f"{KEYRING_PREFIX}{session_id}"

    def load(self, reference: str) -> bytes:
        import keyring

        session_id = reference[len(KEYRING_PREFIX):]
        try:
            value = keyring.get_password(KEYRING_SERVICE, session_id)
        except Exception as exc:
            raise KeyStoreError(f"could not read key from the OS keychain: {exc}") from exc

        if value is None:
            raise KeyStoreError(
                f"no key in the OS keychain for session {session_id[:12]}. "
                "The database alone cannot decrypt this session."
            )
        return value.encode('utf-8')

    def delete(self, reference: str) -> bool:
        import keyring

        session_id = reference[len(KEYRING_PREFIX):]
        try:
            keyring.delete_password(KEYRING_SERVICE, session_id)
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════
# Key directory
# ═══════════════════════════════════════════════════════════

class FileKeyStore:
    """
    Keys in ``~/.codeabstract/keys``, one file per session.

    Weaker than a keychain — see the module docstring. Used when no
    keychain backend exists, and deliberately never chosen over one.
    """

    backend = "file"

    def __init__(self, directory: Optional[Path] = None):
        self.directory = Path(directory) if directory else get_key_store_dir()

    def _path(self, session_id: str) -> Path:
        # Session ids are UUIDs, but this is a filesystem path built from a
        # value that arrives from the database, so constrain it anyway.
        safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
        if not safe:
            raise KeyStoreError(f"invalid session id: {session_id!r}")
        return self.directory / f"{safe}.key"

    def store(self, session_id: str, key: bytes) -> str:
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(self.directory, stat.S_IRWXU)  # 0700
        except OSError:
            pass  # best effort; Windows inherits ACLs instead

        path = self._path(session_id)
        try:
            path.write_bytes(key)
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
        except OSError as exc:
            raise KeyStoreError(f"could not write key file: {exc}") from exc

        return f"{FILE_PREFIX}{session_id}"

    def load(self, reference: str) -> bytes:
        path = self._path(reference[len(FILE_PREFIX):])
        try:
            return path.read_bytes()
        except OSError as exc:
            raise KeyStoreError(
                f"no key file at {path}. The database alone cannot decrypt "
                f"this session."
            ) from exc

    def delete(self, reference: str) -> bool:
        path = self._path(reference[len(FILE_PREFIX):])
        try:
            path.unlink()
            return True
        except OSError:
            return False


# ═══════════════════════════════════════════════════════════
# Selection
# ═══════════════════════════════════════════════════════════

def get_key_store(backend: Optional[str] = None) -> KeyStore:
    """
    Return the key store to use.

    Args:
        backend: ``auto`` | ``keyring`` | ``file``. Falls back to the
            ``key_backend`` setting, which defaults to ``auto``.

    Returns:
        A :class:`KeyStore`.

    Raises:
        KeyStoreError: If ``keyring`` is demanded and is not usable. An
            explicit choice is honoured or refused, never downgraded
            silently — a user who asked for the keychain should not end up
            with key files without being told.
    """
    choice = (
        backend
        or os.environ.get('CODEABSTRACT_KEY_BACKEND')
        or get_config().get('key_backend')
        or 'auto'
    ).lower()

    if choice == 'keyring':
        if not keyring_available():
            raise KeyStoreError(
                "key_backend is 'keyring' but no OS keychain backend is "
                "available. Install one (pip install 'codeabstract[keyring]') "
                "or set key_backend to 'auto'."
            )
        return KeyringKeyStore()

    if choice == 'file':
        return FileKeyStore()

    return KeyringKeyStore() if keyring_available() else FileKeyStore()


def store_session_key(session_id: str, key: bytes, backend: Optional[str] = None) -> str:
    """Save a session's Fernet key and return its database reference."""
    return get_key_store(backend).store(session_id, key)


def load_session_key(reference: str) -> bytes:
    """
    Retrieve a session's Fernet key from its reference.

    Raises:
        KeyStoreError: If the reference is unrecognised or the key is gone.
    """
    if reference.startswith(KEYRING_PREFIX):
        return KeyringKeyStore().load(reference)
    if reference.startswith(FILE_PREFIX):
        return FileKeyStore().load(reference)
    raise KeyStoreError(f"unrecognised key reference: {reference!r}")


def delete_session_key(reference: str) -> bool:
    """Remove a stored key. Returns False if there was nothing to remove."""
    if not reference:
        return False
    if reference.startswith(KEYRING_PREFIX):
        return KeyringKeyStore().delete(reference)
    if reference.startswith(FILE_PREFIX):
        return FileKeyStore().delete(reference)
    return False


# ═══════════════════════════════════════════════════════════
# Migration
# ═══════════════════════════════════════════════════════════

def migrate_legacy_keys(backend: Optional[str] = None) -> Tuple[int, List[str]]:
    """
    Move keys of pre-Phase-4 sessions out of the database.

    Each session's key is copied into the key store, the reference is
    written to ``key_ref``, and only then is the ``encryption_key`` column
    blanked — so an interrupted migration leaves a session readable rather
    than orphaned.

    Returns:
        ``(migrated_count, failures)`` where each failure is a message
        naming the session it applies to.

    Note:
        Not run automatically. Rewriting a user's session database as a
        side effect of an unrelated command is the kind of surprise that
        loses data, so this is wired to ``codeabstract sessions
        migrate-keys`` and nothing else.
    """
    from storage.database import get_connection

    store = get_key_store(backend)
    migrated = 0
    failures: List[str] = []

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT session_id, encryption_key, key_ref
            FROM sessions
            WHERE encryption_key IS NOT NULL AND LENGTH(encryption_key) > 0
            """
        ).fetchall()

        for row in rows:
            session_id = row['session_id']
            if row['key_ref']:
                # Already migrated; the leftover column is the failure mode
                # this loop exists to clear.
                conn.execute(
                    "UPDATE sessions SET encryption_key = ? WHERE session_id = ?",
                    (b'', session_id),
                )
                migrated += 1
                continue

            try:
                reference = store.store(session_id, bytes(row['encryption_key']))
            except KeyStoreError as exc:
                failures.append(f"{session_id[:12]}: {exc}")
                continue

            conn.execute(
                "UPDATE sessions SET key_ref = ? WHERE session_id = ?",
                (reference, session_id),
            )
            conn.execute(
                "UPDATE sessions SET encryption_key = ? WHERE session_id = ?",
                (b'', session_id),
            )
            migrated += 1

        conn.commit()
    finally:
        conn.close()

    return migrated, failures
