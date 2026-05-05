"""
SQLite Database Management

Handles schema creation, connection management, and low-level
database operations for session persistence.
"""

import sqlite3
from pathlib import Path
from typing import Optional

from codeabstract.config.settings import get_db_path

# ═══════════════════════════════════════════════════════════
# Schema definition
# ═══════════════════════════════════════════════════════════

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id       TEXT PRIMARY KEY,
    source_file_path TEXT NOT NULL,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    context_window   INTEGER DEFAULT 3,
    encrypted_mapping BLOB NOT NULL,
    encryption_key   BLOB NOT NULL,
    statistics_json  TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sessions_created_at
    ON sessions (created_at DESC);
"""


def get_connection(db_path: Optional[Path] = None) -> sqlite3.Connection:
    """
    Open a SQLite connection, creating the database and schema
    if they don't already exist.

    Args:
        db_path: Optional explicit path. Defaults to the configured path.

    Returns:
        sqlite3.Connection with row_factory set to sqlite3.Row.
    """
    if db_path is None:
        db_path = get_db_path()

    # Ensure parent directory exists
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Create tables if needed
    conn.executescript(SCHEMA_SQL)
    conn.commit()

    return conn


def close_connection(conn: sqlite3.Connection):
    """Close a database connection safely."""
    if conn:
        conn.close()
