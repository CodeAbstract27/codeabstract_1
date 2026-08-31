"""
Flask application factory.

Phase 5. Flask rather than Streamlit, for two reasons that outlived the
choice being made:

* **It can be tested.** The proposal's evaluation standard — and this
  project's — is that a claim is worth what its test is worth. Flask's test
  client drives the whole pipeline in-process, so "no secret appears in any
  response body" is an assertion rather than a screenshot. A Streamlit
  script has no equivalent seam.
* **It has a request boundary.** Masking, validation and the CSRF posture
  in :mod:`web.routes` all attach to one. Streamlit's model — a script
  re-run per interaction, with widget state as the only input — has nowhere
  to put them.

The app is bound to ``127.0.0.1`` by whatever starts it. Nothing here
authenticates a caller, so exposing it on a network interface would publish
the vault and the source of anyone who used it — see the ``web`` command in
``cli.py``, which requires an explicit acknowledgement to bind elsewhere.
"""

import os
import stat
from typing import Any, Dict, Optional


def pct_class(value: float, maximum: float, axis: str = 'h') -> str:
    """
    CSS class name for a bar's height/width, snapped to the nearest 5%
    step defined in app.css's ``.pct-h-N`` / ``.pct-w-N`` rules.

    A Jinja global rather than a template writing ``style="height: N%"``
    directly: the CSP's ``style-src 'self'`` (below) blocks inline style
    attributes outright, which is exactly what flattened every dashboard
    bar to 0% height until a real-browser check caught it. Percentages are
    bucketed to fixed classes instead, so nothing here is ever an inline
    style.
    """
    pct = (value / maximum * 100) if maximum else 0
    bucket = min(100, max(0, round(pct / 5) * 5))
    return f'pct-{axis}-{int(bucket)}'

from flask import Flask

from config.settings import get_flask_secret_key_path
from web.service import WebServiceError

# Flask rejects a body larger than this before the route sees it, so a
# multi-megabyte paste cannot be buffered into memory first. Set above
# ``service.MAX_SOURCE_BYTES`` so the friendlier, source-specific message
# in the service layer is what a merely-too-large file gets.
MAX_CONTENT_LENGTH = 2 * 1024 * 1024

# Sent on every response. The pages render other people's source code, so
# the value of a policy that forbids inline script does not depend on this
# app having no XSS -- it is what makes an escaping mistake survivable.
# Kept in step with the templates: no inline <script>, no style attributes,
# no external origins.
SECURITY_HEADERS = {
    'Content-Security-Policy': (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'none'; "
        "object-src 'none'"
    ),
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
    # The vault and the source belong in this tab and nowhere else.
    'Cache-Control': 'no-store',
}


def _load_or_create_secret_key() -> bytes:
    """
    The key that signs the login-session cookie.

    Generated once and written to ``~/.codeabstract/flask_secret.key`` with
    owner-only permissions where the platform honours them (see
    ``storage/key_store.py`` for the same pattern applied to Fernet keys).
    A key regenerated on every process start would sign every existing
    visitor out each time the server restarts, which defeats the point of
    a persistent login.
    """
    path = get_flask_secret_key_path()
    if path.is_file():
        existing = path.read_bytes()
        if existing:
            return existing

    key = os.urandom(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError:
        pass  # best effort; Windows inherits ACLs instead
    return key


def create_app(config: Optional[Dict[str, Any]] = None) -> Flask:
    """
    Build the application.

    Args:
        config: Overrides applied last. The ones that matter:

            ``SAVE_SESSIONS`` (default True)
                Persist each abstraction, so a response can be translated
                later. False makes the server keep nothing.
            ``ALLOW_REVEAL`` (default False)
                Permit ``reveal`` requests to unmask secret values. Off
                means no request can, whatever it asks for.
            ``LLM_CLIENT`` (default None)
                A pre-built client for ``/api/review``, bypassing provider
                resolution. This is the seam the tests drive the review
                pipeline through without a key or a network call.
            ``SECRET_KEY`` (default: loaded from disk, generated on first
                use)
                Overridden by the test suite with a fixed value, so tests
                do not each write their own key file.

    Returns:
        A configured :class:`flask.Flask` app.
    """
    app = Flask(__name__, template_folder='templates', static_folder='static')

    app.config.update(
        MAX_CONTENT_LENGTH=MAX_CONTENT_LENGTH,
        JSON_SORT_KEYS=False,
        SAVE_SESSIONS=True,
        ALLOW_REVEAL=False,
        LLM_CLIENT=None,
        SECRET_KEY=_load_or_create_secret_key(),
        # The login cookie is read by this app alone: not by any script
        # (HttpOnly), and not sent along on a cross-site navigation or
        # form post to it (SameSite=Lax covers top-level GET navigation,
        # which is the one case Lax still allows).
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE='Lax',
    )
    if config:
        app.config.update(config)

    from web.auth import auth_api, auth_ui
    from web.routes import api, error_response, ui

    app.register_blueprint(ui)
    app.register_blueprint(api)
    app.register_blueprint(auth_ui)
    app.register_blueprint(auth_api)

    app.jinja_env.globals['pct_class'] = pct_class

    @app.context_processor
    def _inject_auth_context():
        # Every template needs to know whether to render "Dashboard /
        # Insights / user@example.com · Log out" or "Sign in / Sign up" in
        # the nav — computed once here instead of every route handler
        # passing the same two values into render_template.
        from web.auth import current_user_email, current_user_id

        return {
            'current_user_email': current_user_email(),
            'is_authenticated': current_user_id() is not None,
        }

    # ── Errors ───────────────────────────────────────────
    # One shape for every failure: JSON under /api, a page elsewhere.

    @app.errorhandler(WebServiceError)
    def _service_error(exc: WebServiceError):
        return error_response(str(exc), exc.status)

    @app.errorhandler(404)
    def _not_found(exc):
        return error_response("Not found.", 404)

    @app.errorhandler(405)
    def _not_allowed(exc):
        return error_response("Method not allowed for this endpoint.", 405)

    @app.errorhandler(413)
    def _too_large(exc):
        return error_response(
            f"Request body exceeds {MAX_CONTENT_LENGTH // 1024} KiB.", 413,
        )

    @app.errorhandler(500)
    def _server_error(exc):
        # Deliberately no traceback in the body. This process has the
        # user's source and their mapping table in memory; an exception
        # message is a poor place to find out what else it had.
        return error_response("Internal error — see the server log.", 500)

    @app.after_request
    def _headers(response):
        for header, value in SECURITY_HEADERS.items():
            response.headers.setdefault(header, value)
        return response

    return app


def main(
    host: str = '127.0.0.1',
    port: int = 5000,
    debug: bool = False,
    **config: Any,
) -> None:                                             # pragma: no cover
    """Run the development server. ``cli.py web`` is the supported entry."""
    create_app(config).run(host=host, port=port, debug=debug)


if __name__ == '__main__':                             # pragma: no cover
    main()
