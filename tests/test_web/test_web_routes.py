"""
Tests for the HTTP layer (``web.routes``, ``web.app``).

These drive the real application through Flask's test client — same
routing, same error handlers, same headers a browser would get. What they
check is the contract: status codes that mean what they say, a single error
shape, and the request-level defences that the service layer cannot provide
because they are properties of the request rather than of the pipeline.
"""

import pytest

from tests.test_web.conftest import JS_SOURCE, SECRET_SOURCE


def abstract(client, code=SECRET_SOURCE, filename='payments.py', **extra):
    """POST /api/abstract with sensible defaults."""
    payload = {'code': code, 'filename': filename}
    payload.update(extra)
    return client.post('/api/abstract', json=payload)


# ═══════════════════════════════════════════════════════════
# Pages
# ═══════════════════════════════════════════════════════════

class TestPages:

    def test_workbench_renders(self, client):
        response = client.get('/')
        assert response.status_code == 200
        assert b'CodeAbstract' in response.data

    def test_workbench_offers_all_four_privacy_levels(self, client):
        body = client.get('/').get_data(as_text=True)
        for level in ('low', 'medium', 'high', 'critical'):
            assert f'value="{level}"' in body

    def test_workbench_shows_the_five_output_panes(self, client):
        """The proposal names five output formats. All five need a home."""
        body = client.get('/').get_data(as_text=True)
        for pane in ('Abstracted', 'Local vault', 'LLM analysis',
                     'Mapped feedback', 'Privacy report'):
            assert pane in body

    def test_reveal_control_is_absent_unless_the_server_allows_it(self, client):
        assert 'id="reveal"' not in client.get('/').get_data(as_text=True)

    def test_reveal_control_appears_when_the_server_allows_it(self, fake_client):
        from web import create_app

        app = create_app({'ALLOW_REVEAL': True, 'LLM_CLIENT': fake_client})
        assert 'id="reveal"' in app.test_client().get('/').get_data(as_text=True)

    def test_sessions_page_renders(self, client):
        assert client.get('/sessions').status_code == 200

    def test_health_reports_capabilities(self, client):
        data = client.get('/health').get_json()
        assert data['status'] == 'ok'
        assert 'python' in data['languages']
        assert data['detector_version']

    def test_unknown_page_is_a_404_page_not_json(self, client):
        response = client.get('/no-such-page')
        assert response.status_code == 404
        assert b'404' in response.data


# ═══════════════════════════════════════════════════════════
# Request-level defences
# ═══════════════════════════════════════════════════════════

class TestRequestDefences:
    """
    Properties of the request, which the service layer cannot see.

    The content-type rule is the CSRF posture: a cross-origin page can make
    the browser issue a form POST without a preflight, but not a
    ``application/json`` one. Requiring JSON on writes takes every mutating
    endpoint out of the simple-request class.
    """

    def test_form_encoded_post_is_refused(self, client):
        response = client.post(
            '/api/abstract',
            data={'code': 'x = 1', 'filename': 'a.py'},
        )
        assert response.status_code == 415

    def test_plain_text_post_is_refused(self, client):
        response = client.post(
            '/api/abstract',
            data='{"code": "x = 1"}',
            content_type='text/plain',
        )
        assert response.status_code == 415

    def test_delete_requires_json_content_type_too(self, client):
        assert client.delete('/api/sessions/abc').status_code == 415

    def test_reads_do_not_require_a_content_type(self, client):
        assert client.get('/api/providers').status_code == 200

    def test_malformed_json_is_a_400_not_a_crash(self, client):
        response = client.post(
            '/api/abstract',
            data='{not json',
            content_type='application/json',
        )
        assert response.status_code == 400
        assert 'error' in response.get_json()

    def test_a_json_list_body_is_rejected(self, client):
        response = client.post('/api/abstract', json=['code'])
        assert response.status_code == 400

    def test_oversized_body_is_refused_before_the_route_sees_it(self, client):
        from web.app import MAX_CONTENT_LENGTH

        response = client.post(
            '/api/abstract',
            data=b'x' * (MAX_CONTENT_LENGTH + 1024),
            content_type='application/json',
        )
        assert response.status_code == 413

    def test_security_headers_are_set(self, client):
        headers = client.get('/').headers
        assert headers['X-Content-Type-Options'] == 'nosniff'
        assert headers['X-Frame-Options'] == 'DENY'
        assert headers['Referrer-Policy'] == 'no-referrer'
        assert 'no-store' in headers['Cache-Control']

    def test_csp_forbids_inline_script(self, client):
        """
        The policy is only worth having if the pages actually comply.

        Every page renders other people's source code, so a policy that
        blocks inline script is what makes an escaping mistake survivable
        rather than fatal.
        """
        csp = client.get('/').headers['Content-Security-Policy']
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp

    @pytest.mark.parametrize('path', ['/', '/sessions'])
    def test_no_page_contains_an_inline_script_block(self, client, path):
        body = client.get(path).get_data(as_text=True)
        assert '<script>' not in body        # only <script src="…">
        assert 'onclick=' not in body


# ═══════════════════════════════════════════════════════════
# /api/abstract
# ═══════════════════════════════════════════════════════════

class TestAbstractEndpoint:

    def test_returns_every_output_format(self, client):
        data = abstract(client).get_json()

        assert data['abstract_code']
        assert data['vault_rows']
        assert data['report']['summary']['hidden'] > 0
        assert data['report_markdown'].startswith('# Privacy Report')
        assert data['panes']['original'] and data['panes']['abstract']

    def test_panes_have_one_entry_per_line(self, client):
        data = abstract(client).get_json()
        assert len(data['panes']['original']) == len(SECRET_SOURCE.split('\n'))

    def test_session_is_persisted_and_listed(self, client):
        session_id = abstract(client).get_json()['session_id']
        listed = client.get('/api/sessions').get_json()['sessions']
        assert session_id in [row['session_id'] for row in listed]

    def test_stateless_server_saves_nothing(self, fake_client):
        from web import create_app

        app = create_app({'SAVE_SESSIONS': False, 'LLM_CLIENT': fake_client})
        with app.test_client() as stateless:
            data = abstract(stateless).get_json()
            assert data['saved'] is False
            assert stateless.get(
                f"/api/sessions/{data['session_id']}"
            ).status_code == 404

    def test_javascript_is_accepted(self, client):
        data = abstract(client, code=JS_SOURCE, filename='billing.js').get_json()
        assert data['language'] == 'javascript'

    def test_missing_code_is_400(self, client):
        assert client.post('/api/abstract', json={'filename': 'a.py'}).status_code == 400

    def test_unsupported_extension_is_400(self, client):
        response = abstract(client, code='hello', filename='notes.txt')
        assert response.status_code == 400
        assert '.py' in response.get_json()['error']

    def test_syntax_error_is_400_with_a_useful_message(self, client):
        response = abstract(client, code='def broken(:\n  pass\n', filename='b.py')
        assert response.status_code == 400
        assert 'line' in response.get_json()['error'].lower()

    def test_bad_privacy_level_is_400(self, client):
        assert abstract(client, privacy_level='paranoid').status_code == 400

    def test_bad_context_window_is_400(self, client):
        assert abstract(client, context_window=999).status_code == 400

    def test_a_reveal_request_is_ignored_when_the_server_forbids_it(self, client):
        """
        Two gates, and the client only controls one.

        If asking were enough, the masking would protect nothing — anyone who
        can reach the port can ask.
        """
        data = abstract(client, reveal=True).get_json()
        assert data['secrets_masked'] is True


# ═══════════════════════════════════════════════════════════
# /api/review
# ═══════════════════════════════════════════════════════════

class TestReviewEndpoint:

    def test_returns_both_the_raw_and_the_mapped_answer(self, client):
        response = client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py', 'task': 'review',
        })
        data = response.get_json()

        assert response.status_code == 200
        assert data['raw_response_html']
        assert data['mapped_feedback_html']
        assert data['provider'] == 'fake'
        assert data['usage']['total_tokens'] == 140

    def test_the_raw_pane_still_shows_tokens(self, client):
        """
        This pane is the evidence, not decoration.

        It is what lets a user see for themselves that the model was
        answering about placeholders.
        """
        data = client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        }).get_json()
        assert 'data-token=' in data['raw_response_html']

    def test_unknown_task_is_400(self, client):
        response = client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py', 'task': 'nonsense',
        })
        assert response.status_code == 400

    def test_provider_failure_is_502(self, fake_client):
        from tests.test_web.conftest import FakeLLMClient
        from web import create_app

        broken = FakeLLMClient(success=False, error='overloaded')
        app = create_app({'LLM_CLIENT': broken})

        response = app.test_client().post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        })
        assert response.status_code == 502
        assert 'overloaded' in response.get_json()['error']

    def test_no_configured_provider_is_503(self, monkeypatch):
        """
        Missing configuration is not a bad request, and not a bug.

        503 with the provider's own remediation text is what tells the user
        to set a key rather than to change what they sent.
        """
        from llm import ProviderError
        from web import create_app, service

        def refuse(**_kwargs):
            raise ProviderError("No LLM provider is ready.")

        monkeypatch.setattr(service, 'create_client', refuse)
        app = create_app({'LLM_CLIENT': None})

        response = app.test_client().post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        })
        assert response.status_code == 503
        assert 'provider' in response.get_json()['error'].lower()


# ═══════════════════════════════════════════════════════════
# /api/translate
# ═══════════════════════════════════════════════════════════

class TestTranslateEndpoint:

    def test_round_trips_through_a_saved_session(self, client):
        data = abstract(client).get_json()
        token = next(
            row['token'] for row in data['vault_rows'] if row['label'] != 'SECRET'
        )

        response = client.post('/api/translate', json={
            'session_id': data['session_id'], 'text': f"{token} is recomputed.",
        })
        translated = response.get_json()

        assert response.status_code == 200
        assert translated['tokens_resolved'] == 1
        assert 'class="restored' in translated['text_html']

    def test_a_prefix_identifies_the_session(self, client):
        session_id = abstract(client).get_json()['session_id']
        response = client.post('/api/translate', json={
            'session_id': session_id[:8], 'text': 'Looks fine.',
        })
        assert response.get_json()['session_id'] == session_id

    def test_unknown_session_is_404(self, client):
        response = client.post('/api/translate', json={
            'session_id': '0' * 32, 'text': 'Anything.',
        })
        assert response.status_code == 404

    def test_empty_text_is_400(self, client):
        session_id = abstract(client).get_json()['session_id']
        response = client.post('/api/translate', json={
            'session_id': session_id, 'text': '   ',
        })
        assert response.status_code == 400


# ═══════════════════════════════════════════════════════════
# Sessions and capability endpoints
# ═══════════════════════════════════════════════════════════

class TestSessionEndpoints:

    def test_listing_never_includes_mapping_material(self, client):
        abstract(client)
        body = client.get('/api/sessions').get_data(as_text=True)

        assert 'encrypted_mapping' not in body
        assert 'encryption_key' not in body

    def test_detail_returns_a_masked_vault(self, client):
        session_id = abstract(client).get_json()['session_id']
        detail = client.get(f'/api/sessions/{session_id}').get_json()

        assert detail['secrets_masked'] is True
        assert any(row['masked'] for row in detail['vault'])

    def test_delete_removes_it(self, client):
        session_id = abstract(client).get_json()['session_id']

        assert client.delete(
            f'/api/sessions/{session_id}',
            headers={'Content-Type': 'application/json'},
        ).status_code == 200
        assert client.get(f'/api/sessions/{session_id}').status_code == 404

    def test_deleting_an_unknown_session_is_404(self, client):
        response = client.delete(
            '/api/sessions/' + '0' * 32,
            headers={'Content-Type': 'application/json'},
        )
        assert response.status_code == 404

    def test_limit_is_clamped_rather_than_trusted(self, client):
        abstract(client)
        assert client.get('/api/sessions?limit=999999').status_code == 200
        assert client.get('/api/sessions?limit=banana').status_code == 200


class TestCapabilityEndpoints:

    def test_providers_endpoint(self, client):
        providers = client.get('/api/providers').get_json()['providers']
        assert {p['provider'] for p in providers} == {'gemini', 'openai', 'anthropic'}

    def test_languages_endpoint(self, client):
        languages = client.get('/api/languages').get_json()['languages']
        assert {item['language'] for item in languages} >= {'python', 'javascript'}

    def test_options_endpoint_answers_in_one_round_trip(self, client):
        options = client.get('/api/options').get_json()
        assert len(options['privacy_levels']) == 4
        assert options['limits']['max_source_bytes'] > 0
        assert options['allow_reveal'] is False


class TestErrorShape:
    """One error shape everywhere, so the client needs one branch."""

    @pytest.mark.parametrize('call', [
        lambda c: c.post('/api/abstract', json={'filename': 'a.py'}),
        lambda c: c.post('/api/translate', json={'session_id': 'x', 'text': 'y'}),
        lambda c: c.get('/api/sessions/nope'),
        lambda c: c.get('/api/nothing-here'),
    ])
    def test_api_errors_are_json_with_an_error_key(self, client, call):
        response = call(client)
        assert response.status_code >= 400
        assert response.is_json
        assert isinstance(response.get_json()['error'], str)

    def test_an_error_body_carries_no_traceback(self, client):
        body = client.post('/api/abstract', json={'filename': 'a.py'}).get_data(as_text=True)
        assert 'Traceback' not in body
        assert 'File "' not in body

    def test_method_not_allowed_is_405(self, client):
        assert client.get('/api/abstract').status_code == 405
