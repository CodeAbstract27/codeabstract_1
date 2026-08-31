"""
Regression: a corrupted or non-SQLite database file must fail with a
clear, actionable message, not a bare "file is not a database".

Found by direct failure-injection testing: pointing ``get_connection()``
at a file that exists but is not a valid SQLite database (truncated,
overwritten, or simply garbage bytes) raised
``sqlite3.DatabaseError: file is not a database`` with no indication of
*which* file, or what a user should do about it -- and because every
session-touching command (``sessions list``, ``stats``, ``abstract`` when
saving a session, etc.) goes through this one function, the same terse
message surfaced everywhere.
"""

import sqlite3

import pytest

from storage.database import get_connection


class TestCorruptedDatabaseFailsClearly:

    def test_non_sqlite_file_raises_actionable_message(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        db_path.write_bytes(b"not a sqlite database, just garbage bytes")

        with pytest.raises(sqlite3.DatabaseError) as excinfo:
            get_connection(db_path=db_path)

        message = str(excinfo.value)
        assert str(db_path) in message
        assert "restore" in message.lower()

    def test_valid_database_is_unaffected(self, tmp_path):
        """Regression guard: the new try/except must not interfere with
        an ordinary, valid database."""
        db_path = tmp_path / "sessions.db"
        conn = get_connection(db_path=db_path)
        conn.execute("SELECT 1")
        conn.close()
