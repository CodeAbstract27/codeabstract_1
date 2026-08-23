"""
SQLite Database Management

Handles schema creation, connection management, and low-level
database operations for session persistence.
"""

import sqlite3
import threading
from pathlib import Path
from typing import Optional, Set

from config.settings import get_db_path

# Paths whose schema/migrations have already been applied in this process.
# See the comment in get_connection() -- re-running that DDL on every
# connection open is what caused write contention under concurrency.
_schema_initialized: Set[str] = set()
_schema_lock = threading.Lock()

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

# ═══════════════════════════════════════════════════════════
# Migrations
# ═══════════════════════════════════════════════════════════
# Columns added after the initial release.  ``CREATE TABLE IF NOT EXISTS``
# never alters an existing table, so databases created before a column was
# introduced need it added explicitly.  Each entry is (column, definition);
# they are applied in order and skipped if already present.

MIGRATIONS = [
    # Phase 1: abstract → original line-number index, used by RECONSTRUCT
    # to translate the line citations in an LLM response.
    ("line_map_json", "TEXT DEFAULT '{}'"),
    # Phase 4: reference to the session's Fernet key in the OS keychain or
    # key directory (see storage.key_store).  The key itself no longer goes
    # in ``encryption_key`` -- a database row that carries the key that
    # unlocks it is not encrypted in any useful sense.  The old column
    # stays for sessions written before this change; both are read, only
    # this one is written.
    ("key_ref", "TEXT DEFAULT ''"),
    # Phase 4: which language adapter produced the abstraction, so that
    # RECONSTRUCT and the privacy report can tell a Python session from a
    # JavaScript one.
    ("language", "TEXT DEFAULT 'python'"),
]


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Add any columns missing from an existing sessions table."""
    existing = {
        row["name"]
        for row in conn.execute("PRAGMA table_info(sessions)").fetchall()
    }

    for column, definition in MIGRATIONS:
        if column not in existing:
            conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} {definition}")


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

    # `sqlite3.connect`'s default busy timeout is 5s. Raised as cheap
    # insurance under concurrent writers -- multiple browser tabs against
    # `codeabstract web`, or a shared `--expose`d instance -- but on its
    # own this did not fix the contention measured below; see that fix.
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")

    # Every caller in storage.session_manager opens a fresh connection per
    # operation (get_connection() is called anew for every save/load/list/
    # delete), and this used to run `executescript(SCHEMA_SQL)` -- DDL --
    # plus the migration check unconditionally on every one of those calls,
    # even though after the first call the schema is already current. DDL
    # takes a stronger lock than a row write, so N connections opening at
    # once each re-ran DDL at once. Measured: 25 threads x 20 inserts each
    # against a fresh database, sharing this DDL-per-open behaviour, lost
    # writes to `sqlite3.OperationalError: database is locked` in roughly
    # 2 of 3 trials; pre-creating the schema once before starting the same
    # 25 threads (i.e. skipping this redundant DDL on every open) took
    # that to 0 errors across 1,500 inserts in 3 trials. Applying schema
    # and migrations at most once per path per process removes the
    # redundant DDL from the hot path without changing what a fresh
    # database ends up looking like.
    resolved_path = str(db_path.resolve())
    with _schema_lock:
        if resolved_path not in _schema_initialized:
            conn.executescript(SCHEMA_SQL)
            _apply_migrations(conn)
            conn.commit()
            _schema_initialized.add(resolved_path)

    return conn


def close_connection(conn: sqlite3.Connection):
    """Close a database connection safely."""
    if conn:
        conn.close()
