"""
User Accounts

Backs the web login/signup pages (see web/auth.py). The CLI has no concept
of a user and never calls this module -- sessions it writes keep
``user_id`` NULL, exactly as they did before accounts existed.

Passwords are hashed with werkzeug's PBKDF2 implementation
(``generate_password_hash`` / ``check_password_hash``), already a Flask
dependency, so this adds no new package and no home-grown crypto.
"""

import re
import sqlite3
from typing import Any, Dict, Optional

from werkzeug.security import check_password_hash, generate_password_hash

from storage.database import get_connection

# Deliberately permissive -- this only rejects obvious typos ("no @", "no
# dot"), not RFC 5322 edge cases. The email is a login identifier, not a
# value anything is mailed to.
EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')

MIN_PASSWORD_LENGTH = 8


class UserError(Exception):
    """A signup/login request that cannot be honoured, with a user-facing message."""


def _normalize_email(email: str) -> str:
    return (email or '').strip().lower()


def create_user(email: str, password: str) -> Dict[str, Any]:
    """
    Register a new account.

    Args:
        email: Login identifier. Lower-cased and trimmed before storage,
            so lookups are case-insensitive without a citext extension.
        password: Plaintext password; only its hash is ever stored.

    Returns:
        ``{'id', 'email'}`` for the new account.

    Raises:
        UserError: Invalid email, too-short password, or the email is
            already registered.
    """
    normalized = _normalize_email(email)
    if not EMAIL_RE.match(normalized):
        raise UserError("Enter a valid email address.")
    if len(password or '') < MIN_PASSWORD_LENGTH:
        raise UserError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")

    conn = get_connection()
    try:
        existing = conn.execute(
            "SELECT id FROM users WHERE email = ?", (normalized,)
        ).fetchone()
        if existing is not None:
            raise UserError("An account with that email already exists.")

        password_hash = generate_password_hash(password)
        try:
            cursor = conn.execute(
                "INSERT INTO users (email, password_hash) VALUES (?, ?)",
                (normalized, password_hash),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            # A concurrent signup with the same email won the race between
            # the SELECT above and this INSERT.
            raise UserError("An account with that email already exists.")

        return {'id': cursor.lastrowid, 'email': normalized}
    finally:
        conn.close()


def authenticate(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Check credentials. Returns ``{'id', 'email'}`` or ``None``."""
    normalized = _normalize_email(email)
    if not normalized or not password:
        return None

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, email, password_hash FROM users WHERE email = ?",
            (normalized,),
        ).fetchone()
        if row is None:
            # Hash a throwaway value anyway, so a login attempt against an
            # unregistered email does not return measurably faster than
            # one against a registered email with the wrong password.
            check_password_hash(generate_password_hash('x'), password)
            return None
        if not check_password_hash(row['password_hash'], password):
            return None
        return {'id': row['id'], 'email': row['email']}
    finally:
        conn.close()


def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    """Look up an account by id, for rendering "signed in as" text."""
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, email, created_at FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return None
        return {'id': row['id'], 'email': row['email'], 'created_at': row['created_at']}
    finally:
        conn.close()
