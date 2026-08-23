"""
HTTP layer — pages and JSON API.

Phase 5. Deliberately thin. Every decision that matters — what is masked,
what is validated, what is persisted — lives in :mod:`web.service`, and
every decision about escaping lives in :mod:`web.highlight`. What is left
here is reading a JSON body, calling one function, and choosing a status
code.

**Why the API is JSON-only for writes.** This server binds to localhost by
default and holds the user's source code and their session vault. A page on
any other origin can already make the browser issue a *simple* cross-origin
POST — a form post, no preflight — and while it cannot read the response,
a write endpoint that acted on one would be a CSRF hole. Requiring
``Content-Type: application/json`` on every mutating request takes those
out of the "simple request" class, so the browser must preflight, and the
preflight fails because no CORS headers are served. DELETE is never simple
and is covered by the same rule.
"""

import html
from typing import Any, Dict, Optional

from flask import Blueprint, current_app, jsonify, render_template, request

from web import highlight, service
from web.service import WebServiceError

ui = Blueprint('ui', __name__)
api = Blueprint('api', __name__, url_prefix='/api')

# Shown in the editor on first load, so the tool demonstrates itself
# without the user having to find a file with a credential in it.
SAMPLE_CODE = '''STRIPE_API_KEY = "sk_live_abc123def456ghi789"
commission_rate = 0.029
base_url = "https://api.payment.com/v2"


def calculate_commission(amount):
    """Calculate commission for a transaction."""
    fee = amount * commission_rate
    return round(fee, 2)


def process_payment(user_id, amount):
    endpoint = base_url + "/charge"
    auth_token = STRIPE_API_KEY
    total = amount + calculate_commission(amount)
    return {"endpoint": endpoint, "total": total, "user": user_id}
'''

SAMPLE_FILENAME = 'payments.py'

_MUTATING = {'POST', 'PUT', 'PATCH', 'DELETE'}


# ═══════════════════════════════════════════════════════════
# Request helpers
# ═══════════════════════════════════════════════════════════

@api.before_request
def require_json_for_writes():
    """Reject mutating requests that are not JSON. See the module docstring."""
    if request.method in _MUTATING and not request.is_json:
        return jsonify({
            'error': "Mutating requests must send Content-Type: application/json.",
        }), 415
    return None


def body() -> Dict[str, Any]:
    """The request's JSON object, or a 400 explaining what was expected."""
    payload = request.get_json(silent=True)
    if payload is None:
        raise WebServiceError("Expected a JSON object in the request body.")
    if not isinstance(payload, dict):
        raise WebServiceError("Expected a JSON object, not a list or scalar.")
    return payload


def flag(payload: Dict[str, Any], key: str, default: bool = False) -> bool:
    """Read a boolean that may arrive as a bool, a string, or a number."""
    value = payload.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def reveal_allowed(payload: Dict[str, Any]) -> bool:
    """
    Whether this request may see secret values in the clear.

    Two gates, not one. The client asks, and the *server* has to have been
    started willing to answer: ``ALLOW_REVEAL`` is off unless the operator
    passed ``--allow-reveal``. A browser request alone cannot turn the
    masking off, which is the whole reason the masking is worth having.
    """
    return flag(payload, 'reveal') and bool(
        current_app.config.get('ALLOW_REVEAL', False)
    )


def save_sessions() -> bool:
    """Whether abstractions persist. Off makes the server stateless."""
    return bool(current_app.config.get('SAVE_SESSIONS', True))


# ═══════════════════════════════════════════════════════════
# Pages
# ═══════════════════════════════════════════════════════════

@ui.get('/')
def index():
    """The workbench: editor, controls, and the five output panes."""
    return render_template(
        'index.html',
        privacy_levels=service.privacy_options(),
        tasks=service.task_options(),
        providers=service.provider_options(),
        languages=service.language_options(),
        sample_code=SAMPLE_CODE,
        sample_filename=SAMPLE_FILENAME,
        max_source_kib=service.MAX_SOURCE_BYTES // 1024,
        max_context_window=service.MAX_CONTEXT_WINDOW,
        allow_reveal=bool(current_app.config.get('ALLOW_REVEAL', False)),
    )


@ui.get('/sessions')
def sessions_page():
    """Recent sessions, and the pane that translates a response into one."""
    return render_template('sessions.html', sessions=service.recent_sessions(50))


@ui.get('/health')
def health():
    """Liveness, plus enough capability detail to debug a bad install."""
    from config.settings import __version__, detector_version

    return jsonify({
        'status': 'ok',
        'version': __version__,
        'detector_version': detector_version(),
        'languages': [item['language'] for item in service.language_options()],
        'providers_ready': [
            item['provider'] for item in service.provider_options() if item['ready']
        ],
    })


# ═══════════════════════════════════════════════════════════
# API — the pipeline
# ═══════════════════════════════════════════════════════════

def _panes(outcome: service.AbstractionOutcome) -> Dict[str, Any]:
    """Both code panes, rendered and escaped, ready to inject."""
    original = highlight.highlight_original_code(
        outcome.original_code, outcome.view_mapping,
    )
    abstract = highlight.highlight_abstract_code(
        outcome.abstract_code, outcome.view_mapping, outcome.line_map,
    )
    return {
        'original': [_line(line) for line in original],
        'abstract': [_line(line) for line in abstract],
    }


def _line(line: highlight.CodeLine) -> Dict[str, Any]:
    return {
        'number': line.number,
        'html': line.html,
        'linked': line.linked,
        'css': line.css,
        'label': line.label,
        'tokens': line.tokens,
    }


@api.post('/abstract')
def api_abstract():
    """ABSTRACT(S, k). Returns all five output formats bar the LLM ones."""
    payload = body()
    outcome = service.run_abstraction(
        code=payload.get('code'),
        filename=payload.get('filename'),
        privacy_level=payload.get('privacy_level', 'high'),
        context_window=payload.get('context_window', 3),
        keep_comments=flag(payload, 'keep_comments'),
        reveal=reveal_allowed(payload),
        save=save_sessions(),
    )

    data = outcome.to_dict()
    data['panes'] = _panes(outcome)
    data['vault_rows'] = highlight.highlight_vault_rows(outcome.vault)
    return jsonify(data)


@api.post('/review')
def api_review():
    """Abstract → LLM → Reconstruct, in one request."""
    payload = body()
    outcome = service.run_review(
        code=payload.get('code'),
        filename=payload.get('filename'),
        task=payload.get('task', 'review'),
        query=payload.get('query'),
        provider=payload.get('provider') or None,
        model=payload.get('model') or None,
        privacy_level=payload.get('privacy_level', 'high'),
        context_window=payload.get('context_window', 3),
        keep_comments=flag(payload, 'keep_comments'),
        reveal=reveal_allowed(payload),
        save=save_sessions(),
        client=current_app.config.get('LLM_CLIENT'),
    )

    data = outcome.to_dict()
    view = outcome.abstraction.view_mapping
    data['panes'] = _panes(outcome.abstraction)
    data['vault_rows'] = highlight.highlight_vault_rows(outcome.abstraction.vault)
    data['raw_response_html'] = highlight.highlight_token_text(
        outcome.raw_response, view,
    )
    data['mapped_feedback_html'] = highlight.highlight_feedback(
        outcome.mapped_feedback, view,
    )
    return jsonify(data)


@api.post('/translate')
def api_translate():
    """RECONSTRUCT(R, M̃, K) against a session saved earlier."""
    payload = body()
    result = service.run_translation(
        session_id=payload.get('session_id', ''),
        response_text=payload.get('text', ''),
        reveal=reveal_allowed(payload),
    )

    view = result.pop('view_mapping')
    result['raw_response_html'] = highlight.highlight_token_text(
        str(payload.get('text', '')), view,
    )
    result['text_html'] = highlight.highlight_feedback(result['text'], view)
    return jsonify(result)


# ═══════════════════════════════════════════════════════════
# API — sessions and capabilities
# ═══════════════════════════════════════════════════════════

@api.get('/sessions')
def api_sessions():
    """Recent sessions. Metadata only — no mapping material."""
    return jsonify({'sessions': service.recent_sessions(request.args.get('limit', 20))})


@api.get('/sessions/<session_id>')
def api_session(session_id: str):
    """One session, with its vault masked."""
    payload = {'reveal': request.args.get('reveal', '')}
    return jsonify(service.session_detail(
        session_id, reveal=reveal_allowed(payload),
    ))


@api.delete('/sessions/<session_id>')
def api_session_delete(session_id: str):
    """Delete a session and the key that unlocks it."""
    return jsonify(service.remove_session(session_id))


@api.get('/providers')
def api_providers():
    return jsonify({'providers': service.provider_options()})


@api.get('/languages')
def api_languages():
    return jsonify({'languages': service.language_options()})


@api.get('/options')
def api_options():
    """Everything the UI needs to build its controls, in one round trip."""
    return jsonify({
        'privacy_levels': service.privacy_options(),
        'tasks': service.task_options(),
        'providers': service.provider_options(),
        'languages': service.language_options(),
        'limits': {
            'max_source_bytes': service.MAX_SOURCE_BYTES,
            'max_context_window': service.MAX_CONTEXT_WINDOW,
            'max_query_chars': service.MAX_QUERY_CHARS,
        },
        'allow_reveal': bool(current_app.config.get('ALLOW_REVEAL', False)),
    })


# ═══════════════════════════════════════════════════════════
# Errors
# ═══════════════════════════════════════════════════════════

def wants_json() -> bool:
    """True when the caller is the API rather than a browser address bar."""
    return request.path.startswith('/api/') or request.is_json


def error_response(message: str, status: int, detail: Optional[str] = None):
    """One error shape for the whole app."""
    if wants_json():
        payload: Dict[str, Any] = {'error': message}
        if detail:
            payload['detail'] = detail
        return jsonify(payload), status
    return render_template(
        'error.html', message=html.escape(message), status=status,
    ), status
