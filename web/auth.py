"""
Authentication — login, signup, logout.

Session-based auth using Flask's own signed-cookie session (backed by
itsdangerous, already a Flask dependency) rather than pulling in
Flask-Login: the only things this app needs from a session are "which
account, if any" and "log out clears it", and that fits in one cookie
value. The cookie itself is HttpOnly and SameSite=Lax (set in
``web/app.py``), so it is not readable from a script and is not sent on a
cross-site navigation that could act on it.

Mutating requests here follow the same JSON-only rule as ``web/routes.py``:
a login or signup that a browser could submit as a plain HTML form post
would be a CSRF-shaped request the moment either one has a side effect
worth forging (creating an account, establishing a session). Requiring
``Content-Type: application/json`` forces a real cross-origin request into
a CORS preflight, which this app answers with no ``Access-Control-*``
headers at all.
"""

import threading
import time
from collections import defaultdict
from functools import wraps
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, redirect, render_template, request, session, url_for

from storage import user_manager
from web.service import WebServiceError

auth_ui = Blueprint('auth_ui', __name__)
auth_api = Blueprint('auth_api', __name__, url_prefix='/api/auth')


# ═══════════════════════════════════════════════════════════
# Rate limiting
# ═══════════════════════════════════════════════════════════

class _SlidingWindowLimiter:
    """
    A minimal in-process sliding-window limiter for login and signup.

    In-memory and per-process: it resets on restart and does not share
    state across multiple worker processes. That is a real limitation for
    a production deployment behind a multi-worker WSGI server, and a
    non-issue for the single-process ``codeabstract web`` this app is
    actually shipped as (see ``web/app.py``'s module docstring on the
    localhost-only binding model this whole app assumes). A real
    multi-worker deployment would need this backed by something shared
    (Redis, the session database) instead.
    """

    def __init__(self, threshold: int, window_seconds: float):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._attempts: Dict[str, List[float]] = defaultdict(list)
        self._lock = threading.Lock()

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            now = time.time()
            recent = [t for t in self._attempts[key] if now - t < self.window_seconds]
            self._attempts[key] = recent
            return len(recent) >= self.threshold

    def record(self, key: str) -> None:
        with self._lock:
            self._attempts[key].append(time.time())

    def clear(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


# Keyed by (client address, account) rather than the account alone: keying
# by account alone would let one attacker lock a stranger's account out of
# their own logins by deliberately failing against it from anywhere.
# Keying by (address, account) still stops the realistic threat -- one
# machine credential-stuffing one account -- without handing out that
# denial-of-service lever.
_login_limiter = _SlidingWindowLimiter(threshold=5, window_seconds=15 * 60)

# Keyed by client address alone: there is no account yet to pair it with,
# and the thing worth throttling is scripted mass account creation from one
# machine.
_signup_limiter = _SlidingWindowLimiter(threshold=10, window_seconds=60 * 60)


def _client_address() -> str:
    return request.remote_addr or 'unknown'


def _login_key(email: str) -> str:
    return f"{_client_address()}:{(email or '').strip().lower()}"


def reset_rate_limiters() -> None:
    """
    Clear all limiter state.

    Both limiters are module-level singletons, so their state persists
    across every Flask app built in the same process — harmless for the
    real ``codeabstract web`` (one process, one run), but it means a test
    suite that builds many short-lived apps in one process needs a way to
    stop one test's signup/login volume from tripping another's
    assertions. Not called anywhere in application code.
    """
    _login_limiter._attempts.clear()
    _signup_limiter._attempts.clear()


# ═══════════════════════════════════════════════════════════
# Session helpers
# ═══════════════════════════════════════════════════════════

def current_user_id() -> Optional[int]:
    """The signed-in account's id, or None."""
    return session.get('user_id')


def current_user_email() -> Optional[str]:
    return session.get('email')


def _establish_session(user: Dict[str, Any]) -> None:
    session.clear()
    session['user_id'] = user['id']
    session['email'] = user['email']
    session.permanent = True


def login_required(view):
    """
    Gate a ``ui`` or ``api`` route behind an active session.

    An API call without one gets a 401 it can act on programmatically; a
    page request is redirected to the login page with its original
    destination preserved, so signing in returns the visitor to what they
    asked for.
    """
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user_id() is None:
            if request.path.startswith('/api/'):
                return jsonify({'error': 'Sign in required.'}), 401
            return redirect(url_for('auth_ui.login_page', next=request.path))
        return view(*args, **kwargs)

    return wrapped


# ═══════════════════════════════════════════════════════════
# Pages
# ═══════════════════════════════════════════════════════════

@auth_ui.get('/login')
def login_page():
    if current_user_id() is not None:
        return redirect(url_for('ui.dashboard'))
    return render_template('login.html', next=request.args.get('next', ''))


@auth_ui.get('/signup')
def signup_page():
    if current_user_id() is not None:
        return redirect(url_for('ui.dashboard'))
    return render_template('signup.html')


@auth_ui.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth_ui.login_page'))


# ═══════════════════════════════════════════════════════════
# API
# ═══════════════════════════════════════════════════════════

@auth_api.before_request
def require_json():
    if not request.is_json:
        return jsonify({
            'error': "Requests must send Content-Type: application/json.",
        }), 415
    return None


def _body() -> Dict[str, Any]:
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        raise WebServiceError("Expected a JSON object in the request body.")
    return payload


@auth_api.post('/signup')
def api_signup():
    if _signup_limiter.is_blocked(_client_address()):
        return jsonify({
            'error': 'Too many accounts created from this address. Try again later.',
        }), 429

    payload = _body()
    email = str(payload.get('email', ''))
    password = str(payload.get('password', ''))

    try:
        user = user_manager.create_user(email, password)
    except user_manager.UserError as exc:
        return jsonify({'error': str(exc)}), 400

    _signup_limiter.record(_client_address())
    _establish_session(user)
    return jsonify({'ok': True, 'redirect': url_for('ui.dashboard')})


@auth_api.post('/login')
def api_login():
    payload = _body()
    email = str(payload.get('email', ''))
    password = str(payload.get('password', ''))

    key = _login_key(email)
    if _login_limiter.is_blocked(key):
        return jsonify({
            'error': 'Too many failed attempts for this account. Try again in a few minutes.',
        }), 429

    user = user_manager.authenticate(email, password)
    if user is None:
        _login_limiter.record(key)
        return jsonify({'error': 'Incorrect email or password.'}), 401

    _login_limiter.clear(key)
    _establish_session(user)
    next_path = str(payload.get('next') or '').strip()
    # Only ever redirect somewhere inside this app: a next= value from the
    # client is untrusted input, and an absolute or protocol-relative URL
    # there would make this an open redirect.
    safe_next = next_path if next_path.startswith('/') and not next_path.startswith('//') else None
    return jsonify({'ok': True, 'redirect': safe_next or url_for('ui.dashboard')})
