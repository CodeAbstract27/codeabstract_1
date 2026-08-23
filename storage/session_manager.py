"""
Session Manager

CRUD operations for session persistence: save, load, list, delete, export.
Each session stores the encrypted mapping table and key alongside metadata.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from storage.database import get_connection
from storage.key_store import (
    KeyStoreError,
    delete_session_key,
    load_session_key,
    store_session_key,
)


def _column(row: sqlite3.Row, name: str, default=None):
    """
    Read a column that may predate the migration which added it.

    ``sqlite3.Row`` raises rather than returning None for an unknown key,
    and a database created before Phase 1 or Phase 4 genuinely lacks these
    columns until :func:`storage.database.get_connection` migrates it.
    """
    try:
        value = row[name]
    except (IndexError, KeyError):
        return default
    return default if value is None else value


def _resolve_key(row: sqlite3.Row) -> bytes:
    """
    Return a session's Fernet key, from the key store or the legacy column.

    Phase 4 moved keys out of the database (see :mod:`storage.key_store`).
    Sessions written before that still carry theirs in ``encryption_key``
    and are read from there, so upgrading does not strand existing work.
    """
    reference = _column(row, 'key_ref', '')
    if reference:
        return load_session_key(reference)

    legacy = _column(row, 'encryption_key', b'')
    if legacy:
        return bytes(legacy)

    raise KeyStoreError(
        f"session {_column(row, 'session_id', '?')[:12]} has no key: it is "
        "neither in the key store nor in the database. The mapping table "
        "cannot be decrypted."
    )


def _load_line_map(row: sqlite3.Row) -> Dict[int, int]:
    """
    Read the line index off a session row.

    Sessions saved before Phase 1 have no ``line_map_json`` column value;
    they return an empty index, and RECONSTRUCT falls back to leaving line
    citations untouched.
    """
    try:
        raw = row['line_map_json']
    except (IndexError, KeyError):
        return {}

    if not raw:
        return {}

    try:
        return {int(k): int(v) for k, v in json.loads(raw).items()}
    except (ValueError, TypeError, AttributeError):
        return {}


def save_session(
    session_id: str,
    source_file_path: str,
    context_window: int,
    encrypted_mapping: bytes,
    encryption_key: bytes,
    statistics: Dict[str, Any] = None,
    line_map: Dict[int, int] = None,
    language: str = "python",
) -> None:
    """
    Persist a new session to the database.

    Phase 4: the Fernet key is written to the OS keychain (or the key
    directory) and the row keeps only a reference to it. ``encryption_key``
    is stored empty, so the database on its own decrypts nothing.

    Args:
        session_id: UUID string identifying the session.
        source_file_path: Path to the original source file.
        context_window: Context window size used.
        encrypted_mapping: Encrypted mapping table bytes.
        encryption_key: Fernet key bytes.
        statistics: Optional dict of abstraction statistics.
        line_map: Optional abstract-to-original line index (Phase 1), used
            by RECONSTRUCT to translate the LLM's line citations.
        language: Language adapter that produced the abstraction (Phase 4).

    Raises:
        KeyStoreError: If the key cannot be stored. The session is *not*
            written in that case — a session whose key was silently dropped
            back into the database would quietly undo the guarantee.
    """
    stats_json = json.dumps(statistics or {})
    line_map_json = json.dumps(line_map or {})

    # Store the key first: if this fails, nothing has been written yet.
    key_ref = store_session_key(session_id, encryption_key)

    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO sessions
                (session_id, source_file_path, context_window,
                 encrypted_mapping, encryption_key, statistics_json,
                 line_map_json, key_ref, language)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                source_file_path,
                context_window,
                encrypted_mapping,
                b'',          # Phase 4: the key lives in the key store
                stats_json,
                line_map_json,
                key_ref,
                language,
            ),
        )
        conn.commit()
    except Exception:
        # Do not leave an orphaned key behind for a session that was never
        # written.
        delete_session_key(key_ref)
        raise
    finally:
        conn.close()


def load_session(session_id: str) -> Dict[str, Any]:
    """
    Load a session by its ID (supports prefix matching).

    Args:
        session_id: Full or prefix of the session UUID.

    Returns:
        Dict with keys: session_id, source_file_path, created_at,
        context_window, encrypted_mapping, encryption_key, statistics,
        line_map.

    Raises:
        ValueError: If no matching session is found.
        ValueError: If the prefix is ambiguous (matches multiple sessions).
    """
    conn = get_connection()
    try:
        # Try exact match first
        row = conn.execute(
            "SELECT * FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()

        if row is None:
            # Try prefix match
            rows = conn.execute(
                "SELECT * FROM sessions WHERE session_id LIKE ?",
                (f"{session_id}%",),
            ).fetchall()

            if len(rows) == 0:
                raise ValueError(f"No session found matching '{session_id}'")
            elif len(rows) > 1:
                ids = [r['session_id'][:12] for r in rows]
                raise ValueError(
                    f"Ambiguous prefix '{session_id}' matches: {', '.join(ids)}"
                )
            row = rows[0]

        return {
            'session_id': row['session_id'],
            'source_file_path': row['source_file_path'],
            'created_at': row['created_at'],
            'context_window': row['context_window'],
            'encrypted_mapping': row['encrypted_mapping'],
            # Resolved from the key store for Phase 4 sessions and from the
            # legacy column for older ones; callers see one field either way.
            'encryption_key': _resolve_key(row),
            'key_ref': _column(row, 'key_ref', ''),
            'language': _column(row, 'language', 'python'),
            'statistics': json.loads(row['statistics_json'] or '{}'),
            'line_map': _load_line_map(row),
        }
    finally:
        conn.close()


def list_sessions(limit: int = 20) -> List[Dict[str, Any]]:
    """
    List recent sessions, ordered by creation time (newest first).

    Args:
        limit: Maximum number of sessions to return.

    Returns:
        List of session summary dicts.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT session_id, source_file_path, created_at,
                   context_window, statistics_json
            FROM sessions
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            {
                'session_id': row['session_id'],
                'source_file_path': row['source_file_path'],
                'created_at': row['created_at'],
                'context_window': row['context_window'],
                'statistics': json.loads(row['statistics_json'] or '{}'),
            }
            for row in rows
        ]
    finally:
        conn.close()


def delete_session(session_id: str) -> bool:
    """
    Delete a session by ID (supports prefix matching).

    Args:
        session_id: Full or prefix UUID.

    Returns:
        True if a session was deleted, False otherwise.

    Raises:
        ValueError: If the prefix is ambiguous.
    """
    conn = get_connection()
    try:
        # Resolve to exactly one session first, so that the key and the row
        # are removed together.  Phase 4: deleting the row alone would leave
        # the key behind in the OS keychain forever.
        rows = conn.execute(
            "SELECT session_id, key_ref FROM sessions WHERE session_id = ?",
            (session_id,),
        ).fetchall()

        if not rows:
            rows = conn.execute(
                "SELECT session_id, key_ref FROM sessions WHERE session_id LIKE ?",
                (f"{session_id}%",),
            ).fetchall()

        if len(rows) == 0:
            return False
        elif len(rows) > 1:
            ids = [r['session_id'][:12] for r in rows]
            raise ValueError(
                f"Ambiguous prefix '{session_id}' matches: {', '.join(ids)}"
            )

        target = rows[0]
        conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (target['session_id'],),
        )
        conn.commit()
        delete_session_key(_column(target, 'key_ref', ''))
        return True
    finally:
        conn.close()


def get_session_count() -> int:
    """Return the total number of sessions stored."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT COUNT(*) as cnt FROM sessions").fetchone()
        return row['cnt']
    finally:
        conn.close()


def get_stats_summary() -> Dict[str, Any]:
    """
    Return aggregate statistics across all sessions.

    Returns:
        Dict with total_sessions, total_secrets_found, total_values_found,
        total_abstractions, earliest_session, latest_session.
    """
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                COUNT(*) as total_sessions,
                MIN(created_at) as earliest,
                MAX(created_at) as latest
            FROM sessions
            """
        ).fetchone()

        # Aggregate stats from statistics_json
        rows = conn.execute(
            "SELECT statistics_json FROM sessions"
        ).fetchall()

        total_secrets = 0
        total_values = 0
        total_abstractions = 0

        for r in rows:
            stats = json.loads(r['statistics_json'] or '{}')
            total_secrets += stats.get('secrets_found', 0)
            total_values += stats.get('values_found', 0)
            total_abstractions += stats.get('abstracted_nodes', 0)

        return {
            'total_sessions': row['total_sessions'],
            'earliest_session': row['earliest'],
            'latest_session': row['latest'],
            'total_secrets_found': total_secrets,
            'total_values_found': total_values,
            'total_abstractions': total_abstractions,
        }
    finally:
        conn.close()
