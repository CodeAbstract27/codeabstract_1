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


def save_session(
    session_id: str,
    source_file_path: str,
    context_window: int,
    encrypted_mapping: bytes,
    encryption_key: bytes,
    statistics: Dict[str, Any] = None,
) -> None:
    """
    Persist a new session to the database.

    Args:
        session_id: UUID string identifying the session.
        source_file_path: Path to the original source file.
        context_window: Context window size used.
        encrypted_mapping: Encrypted mapping table bytes.
        encryption_key: Fernet key bytes.
        statistics: Optional dict of abstraction statistics.
    """
    stats_json = json.dumps(statistics or {})
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO sessions
                (session_id, source_file_path, context_window,
                 encrypted_mapping, encryption_key, statistics_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                source_file_path,
                context_window,
                encrypted_mapping,
                encryption_key,
                stats_json,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def load_session(session_id: str) -> Dict[str, Any]:
    """
    Load a session by its ID (supports prefix matching).

    Args:
        session_id: Full or prefix of the session UUID.

    Returns:
        Dict with keys: session_id, source_file_path, created_at,
        context_window, encrypted_mapping, encryption_key, statistics.

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
            'encryption_key': row['encryption_key'],
            'statistics': json.loads(row['statistics_json'] or '{}'),
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
        # Try exact match
        result = conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (session_id,),
        )
        if result.rowcount > 0:
            conn.commit()
            return True

        # Try prefix match
        rows = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id LIKE ?",
            (f"{session_id}%",),
        ).fetchall()

        if len(rows) == 0:
            return False
        elif len(rows) > 1:
            ids = [r['session_id'][:12] for r in rows]
            raise ValueError(
                f"Ambiguous prefix '{session_id}' matches: {', '.join(ids)}"
            )

        conn.execute(
            "DELETE FROM sessions WHERE session_id = ?",
            (rows[0]['session_id'],),
        )
        conn.commit()
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
