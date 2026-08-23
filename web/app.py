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

from typing import Any, Dict, Optional

from flask import Flask

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
    )
    if config:
        app.config.update(config)

    from web.routes import api, error_response, ui

    app.register_blueprint(ui)
    app.register_blueprint(api)

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
