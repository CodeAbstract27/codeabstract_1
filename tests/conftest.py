"""
Shared pytest fixtures for the CodeAbstract test suite.

Provides:
- tmp_db: patches storage.session_manager.get_connection so all calls
  within a test share one persistent in-memory SQLite connection.
- sample_py_file: writes SAMPLE_PAYMENT_CODE to a real temp .py file.
- abstract_result: runs abstract() on SAMPLE_PAYMENT_CODE once.
"""

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from algorithms.abstract import abstract
from tests.fixtures.sample_code import SAMPLE_PAYMENT_CODE


# ═══════════════════════════════════════════════════════════
# In-memory database fixture
# ═══════════════════════════════════════════════════════════

def _create_schema(conn):
    """Create the sessions table in the given real sqlite3 connection."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sessions (
            session_id          TEXT PRIMARY KEY,
            source_file_path    TEXT NOT NULL,
            created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
            context_window      INTEGER DEFAULT 3,
            encrypted_mapping   BLOB NOT NULL,
            encryption_key      BLOB NOT NULL,
            statistics_json     TEXT DEFAULT '{}'
        )
        """
    )
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
