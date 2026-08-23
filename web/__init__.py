"""
CodeAbstract Web Interface (Phase 5).

The proposal's Option B: the pipeline the CLI runs, with the original and
abstracted code side by side, the privacy report inline, and the model's
suggestions mapped back onto the developer's own names.

Layout:

===================  ==========================================================
:mod:`web.service`   The pipeline. No Flask, so it can be tested directly.
:mod:`web.highlight` Escaping and marking for the panes.
:mod:`web.routes`    Pages and the JSON API.
:mod:`web.app`       The application factory.
===================  ==========================================================

``create_app`` is imported lazily so that ``import web.service`` works
without Flask installed — the evaluation suite and the tests for the
pipeline itself have no use for the web extra.
"""

from typing import Any, Dict, Optional

__all__ = ['create_app']


def create_app(config: Optional[Dict[str, Any]] = None):
    """
    Build the Flask app. See :func:`web.app.create_app`.

    Raises:
        RuntimeError: If Flask is not installed, naming the extra that
            installs it rather than surfacing a bare ImportError.
    """
    try:
        from web.app import create_app as _create_app
    except ImportError as exc:                       # pragma: no cover - env
        raise RuntimeError(
            "The web interface needs Flask: pip install 'codeabstract[web]'"
        ) from exc
    return _create_app(config)
