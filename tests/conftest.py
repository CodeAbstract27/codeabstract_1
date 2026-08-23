"""
Shared pytest fixtures for the CodeAbstract test suite.

Test isolation (Phase 4). The test suite exercises commands that write to
the application data directory: sessions land in ``sessions.db``, requests
land in the audit log, and -- since keys moved out of the database --
every abstraction writes a key to the OS credential store.

Left alone, a full run would file a few hundred credentials in the
developer's Windows Credential Manager or macOS Keychain and never remove
them, and would interleave test rows into the audit log that a compliance
reviewer would later have to explain. So the whole directory is redirected
to a temporary one, and keys are forced to the file backend.

The environment is set at import time rather than in a fixture: pytest
imports ``conftest.py`` before the test modules, and some of those read the
configuration during import.

Also provides:
- tmp_db: patches storage.session_manager.get_connection so all calls
  within a test share one persistent in-memory SQLite connection.
- sample_py_file: writes SAMPLE_PAYMENT_CODE to a real temp .py file.
- abstract_result: runs abstract() on SAMPLE_PAYMENT_CODE once.
"""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from algorithms.abstract import abstract
from tests.fixtures.sample_code import SAMPLE_PAYMENT_CODE

# Redirect ~/.codeabstract for the whole session.
_TEST_HOME = Path(tempfile.mkdtemp(prefix="codeabstract-tests-"))
os.environ["CODEABSTRACT_HOME"] = str(_TEST_HOME)

# Never touch the real OS keychain from tests.
os.environ["CODEABSTRACT_KEY_BACKEND"] = "file"


@pytest.fixture(scope="session")
def test_home() -> Path:
    """The temporary application directory this run is using."""
    return _TEST_HOME


@pytest.fixture
def isolated_audit_log(tmp_path) -> Path:
    """A fresh audit log path, for tests that assert on its contents."""
    return tmp_path / "audit.log"


# ═══════════════════════════════════════════════════════════
# In-memory database fixture
# ═══════════════════════════════════════════════════════════

def _create_schema(conn):
    """
    Create the sessions table (and apply migrations) in the given real
    sqlite3 connection.

    Delegates to storage.database's own SCHEMA_SQL/_apply_migrations
    rather than a second, hand-written CREATE TABLE: a duplicated schema
    here previously fell behind the real one (missing line_map_json,
    key_ref, language -- added in Phase 1/4), so every test built on this
    fixture failed with "table sessions has no column named
    line_map_json" the moment save_session tried to write one. Reusing
    the real schema means this fixture can't drift from production again.
    """
    from storage.database import SCHEMA_SQL, _apply_migrations

    conn.executescript(SCHEMA_SQL)
    _apply_migrations(conn)
    conn.commit()


class _NoCloseConnection:
    """
    Thin proxy around a sqlite3.Connection that delegates every attribute
    access to the real connection but turns close() into a no-op.

    This is necessary because sqlite3.Connection.close is a C-level slot
    and cannot be monkey-patched directly.
    """

    def __init__(self, real_conn):
        self._real_conn = real_conn

    def close(self):
        """No-op: keep the in-memory DB alive between session_manager calls."""
        pass

    def __getattr__(self, name):
        return getattr(self._real_conn, name)


@pytest.fixture
def tmp_db():
    """
    Patch storage.session_manager.get_connection so every call returns a
    proxy around one persistent in-memory SQLite connection.

    The session_manager calls conn.close() after every operation; the proxy
    turns that into a no-op so the in-memory data survives across multiple
    calls within the same test.
    """
    real_conn = sqlite3.connect(":memory:", check_same_thread=False)
    real_conn.row_factory = sqlite3.Row
    _create_schema(real_conn)

    proxy = _NoCloseConnection(real_conn)

    with patch("storage.session_manager.get_connection", return_value=proxy):
        yield proxy

    # Genuinely close when the fixture tears down
    real_conn.close()


# ═══════════════════════════════════════════════════════════
# File fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture
def sample_py_file():
    """Write SAMPLE_PAYMENT_CODE to a real temporary .py file."""
    fd, path = tempfile.mkstemp(suffix=".py")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(SAMPLE_PAYMENT_CODE)
    yield path
    if os.path.exists(path):
        os.unlink(path)


# ═══════════════════════════════════════════════════════════
# Pre-computed algorithm result fixture
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="session")
def abstract_result():
    """
    Run abstract() on SAMPLE_PAYMENT_CODE once for the entire test session.

    Scoped to session so the expensive AST walk only happens once.
    """
    return abstract(SAMPLE_PAYMENT_CODE, privacy_level="high", context_window=3)
