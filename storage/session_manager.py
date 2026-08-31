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


def _owner_clause(user_id: Optional[int], prefix: str = "WHERE") -> tuple:
    """
    A ``WHERE``/``AND`` fragment that always scopes by ownership.

    ``user_id=None`` means "the anonymous web visitor, or the CLI" and
    filters to ``user_id IS NULL`` — *never* "every session regardless of
    owner". Every session the CLI has ever written has a NULL owner, so a
    CLI-only database sees the same rows either way; what this actually
    changes is that a signed-out web visitor can no longer see a signed-in
    account's sessions by asking for "no owner" and getting everyone's.
    That gap was caught by hand-testing the login feature end to end: a
    logged-out ``/api/sessions`` call returned another account's session.

    Args:
        prefix: ``"WHERE"`` for a fresh clause, ``"AND"`` to append to one
            that already has a ``WHERE session_id = ?`` in it.
    """
    if user_id is None:
        return f"{prefix} user_id IS NULL", ()
    return f"{prefix} user_id = ?", (user_id,)


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
    user_id: Optional[int] = None,
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
        user_id: Owning web account, if any. The CLI never passes one, so
            its sessions are stored with no owner — visible to any other
            caller that also passes no ``user_id`` (see :func:`_owner_clause`),
            never to a signed-in web account.

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
                 line_map_json, key_ref, language, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                user_id,
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


def load_session(session_id: str, user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Load a session by its ID (supports prefix matching).

    Args:
        session_id: Full or prefix of the session UUID.
        user_id: When given, the session must belong to this account or it
            is treated as not found — a web caller must never learn that a
            session belonging to a *different* account exists, so a
            cross-user lookup raises the same error as a missing one
            rather than a distinguishable "not yours" error.

    Returns:
        Dict with keys: session_id, source_file_path, created_at,
        context_window, encrypted_mapping, encryption_key, statistics,
        line_map.

    Raises:
        ValueError: If no matching session is found (or none owned by
            ``user_id``, when given).
        ValueError: If the prefix is ambiguous (matches multiple sessions).
    """
    conn = get_connection()
    try:
        owner_clause, owner_params = _owner_clause(user_id, prefix="AND")

        # Try exact match first
        row = conn.execute(
            f"SELECT * FROM sessions WHERE session_id = ? {owner_clause}",
            (session_id, *owner_params),
        ).fetchone()

        if row is None:
            # Try prefix match
            rows = conn.execute(
                f"SELECT * FROM sessions WHERE session_id LIKE ? {owner_clause}",
                (f"{session_id}%", *owner_params),
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


def list_sessions(limit: int = 20, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    List recent sessions, ordered by creation time (newest first).

    Args:
        limit: Maximum number of sessions to return.
        user_id: When given, only this account's sessions; otherwise only
            sessions with no owner (every CLI-written session, and any web
            session created while signed out).

    Returns:
        List of session summary dicts.
    """
    conn = get_connection()
    try:
        owner_clause, owner_params = _owner_clause(user_id)
        rows = conn.execute(
            f"""
            SELECT session_id, source_file_path, created_at,
                   context_window, statistics_json, language
            FROM sessions
            {owner_clause}
            ORDER BY created_at DESC, rowid DESC
            LIMIT ?
            """,
            (*owner_params, limit),
        ).fetchall()

        return [
            {
                'session_id': row['session_id'],
                'source_file_path': row['source_file_path'],
                'created_at': row['created_at'],
                'context_window': row['context_window'],
                'statistics': json.loads(row['statistics_json'] or '{}'),
                'language': _column(row, 'language', 'python'),
            }
            for row in rows
        ]
    finally:
        conn.close()


def delete_session(session_id: str, user_id: Optional[int] = None) -> bool:
    """
    Delete a session by ID (supports prefix matching).

    Args:
        session_id: Full or prefix UUID.
        user_id: When given, only a session owned by this account may be
            deleted; anything else is reported as not found (see
            :func:`load_session` for why that error is not distinguishable
            from "does not exist").

    Returns:
        True if a session was deleted, False otherwise.

    Raises:
        ValueError: If the prefix is ambiguous.
    """
    conn = get_connection()
    try:
        owner_clause, owner_params = _owner_clause(user_id, prefix="AND")

        # Resolve to exactly one session first, so that the key and the row
        # are removed together.  Phase 4: deleting the row alone would leave
        # the key behind in the OS keychain forever.
        rows = conn.execute(
            f"SELECT session_id, key_ref FROM sessions WHERE session_id = ? {owner_clause}",
            (session_id, *owner_params),
        ).fetchall()

        if not rows:
            rows = conn.execute(
                f"SELECT session_id, key_ref FROM sessions WHERE session_id LIKE ? {owner_clause}",
                (f"{session_id}%", *owner_params),
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


def get_session_count(user_id: Optional[int] = None) -> int:
    """Return the total number of sessions stored (optionally, for one account)."""
    conn = get_connection()
    try:
        owner_clause, owner_params = _owner_clause(user_id)
        row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM sessions {owner_clause}", owner_params
        ).fetchone()
        return row['cnt']
    finally:
        conn.close()


def get_stats_summary(user_id: Optional[int] = None) -> Dict[str, Any]:
    """
    Return aggregate statistics across sessions (optionally, for one account).

    Returns:
        Dict with total_sessions, total_secrets_found, total_values_found,
        total_abstractions, earliest_session, latest_session.
    """
    conn = get_connection()
    try:
        owner_clause, owner_params = _owner_clause(user_id)
        row = conn.execute(
            f"""
            SELECT
                COUNT(*) as total_sessions,
                MIN(created_at) as earliest,
                MAX(created_at) as latest
            FROM sessions
            {owner_clause}
            """,
            owner_params,
        ).fetchone()

        # Aggregate stats from statistics_json
        rows = conn.execute(
            f"SELECT statistics_json FROM sessions {owner_clause}", owner_params
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


def list_sessions_for_stats(user_id: Optional[int] = None) -> List[Dict[str, Any]]:
    """
    Every session's language, creation timestamp and statistics.

    Unlike :func:`list_sessions` this has no ``limit`` — the Dashboard
    needs the full history to bucket activity by day and language, not
    just the most recent page of it.
    """
    conn = get_connection()
    try:
        owner_clause, owner_params = _owner_clause(user_id)
        rows = conn.execute(
            f"""
            SELECT created_at, language, statistics_json, context_window
            FROM sessions
            {owner_clause}
            ORDER BY created_at ASC
            """,
            owner_params,
        ).fetchall()
        return [
            {
                'created_at': row['created_at'],
                'language': _column(row, 'language', 'python'),
                'statistics': json.loads(row['statistics_json'] or '{}'),
                'context_window': row['context_window'],
            }
            for row in rows
        ]
    finally:
        conn.close()
