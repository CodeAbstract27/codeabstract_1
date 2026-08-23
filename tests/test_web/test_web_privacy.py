"""
The guarantee, at the web boundary.

Phase 0 established that no credential-shaped string survives abstraction.
Phase 5 puts a browser in front of that, and a browser is a second place
things can escape from: a response body, a rendered pane, a stored session
read back later. These tests state the claim in the form the web interface
has to hold it in.

**The claim, precisely.** The original-code pane echoes the submitted source
back verbatim, credentials and all, and that is not a leak — it is the
user's own paste, returned to the tab it came from, and the side-by-side
view the proposal asks for cannot exist without it. What must never carry a
secret value is anything *derived* from the source: the abstract code, the
vault, the privacy report, the reconstructed feedback, the stored session,
the audit log, and above all the provider payload.

``assert_no_secrets`` walks a whole JSON response and reports the path of
any violation, so a regression names the field it appeared in rather than
just failing.
"""

import json

import pytest

from tests.test_web.conftest import (
    JS_SOURCE,
    SECRET_SOURCE,
    SECRETS,
    STRIPE_KEY,
)

# The one path allowed to contain the source verbatim, per the module
# docstring. Anything else is a finding.
ALLOWED_PATHS = ('.panes.original',)

PRIVACY_LEVELS = ('low', 'medium', 'high', 'critical')


def find_secrets(node, path='', secrets=SECRETS):
    """Every (path, secret) pair in a JSON-ish structure."""
    findings = []
    if isinstance(node, dict):
        for key, value in node.items():
            findings += find_secrets(value, f'{path}.{key}', secrets)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            findings += find_secrets(value, f'{path}[{index}]', secrets)
    elif isinstance(node, str):
        findings += [(path, secret) for secret in secrets if secret in node]
    return findings


def assert_no_secrets(payload, allowed=ALLOWED_PATHS, secrets=SECRETS):
    """Fail with the exact field, if any, that carried a credential."""
    leaks = [
        (path, secret) for path, secret in find_secrets(payload, secrets=secrets)
        if not any(path.startswith(prefix) for prefix in allowed)
    ]
    assert not leaks, "credential values reached: " + ", ".join(
        f"{path} ({secret[:8]}…)" for path, secret in leaks
    )


def abstract(client, **extra):
    payload = {'code': SECRET_SOURCE, 'filename': 'payments.py'}
    payload.update(extra)
    return client.post('/api/abstract', json=payload).get_json()


# ═══════════════════════════════════════════════════════════
# What is sent
# ═══════════════════════════════════════════════════════════

class TestProviderPayload:
    """The only bytes that actually leave the machine."""

    def test_no_secret_reaches_the_provider(self, client, fake_client):
        client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        })

        prompt = fake_client.last_prompt
        for secret in SECRETS:
            assert secret not in prompt

    def test_no_proprietary_identifier_reaches_the_provider(self, client, fake_client):
        client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        })

        prompt = fake_client.last_prompt
        for name in ('STRIPE_API_KEY', 'calculate_commission', 'charge_customer',
                     'commission_rate', 'DATABASE_URL'):
            assert name not in prompt

    def test_the_vault_never_reaches_the_provider(self, client, fake_client):
        """
        The mapping is the whole asset. It is rendered in a panel labelled
        never-sent, and this is the assertion behind that label.
        """
        data = client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        }).get_json()

        prompt = fake_client.last_prompt
        for row in data['vault_rows']:
            if row['label'] != 'SECRET' and len(row['name']) > 3:
                assert row['name'] not in prompt

    def test_a_question_naming_a_secret_is_redacted_before_sending(
        self, client, fake_client,
    ):
        client.post('/api/review', json={
            'code': SECRET_SOURCE,
            'filename': 'payments.py',
            'query': f'Is it safe to log {STRIPE_KEY} when charge_customer fails?',
        })

        prompt = fake_client.last_prompt
        assert STRIPE_KEY not in prompt
        assert 'charge_customer' not in prompt

    @pytest.mark.parametrize('level', PRIVACY_LEVELS)
    def test_secrets_are_withheld_at_every_privacy_level(
        self, client, fake_client, level,
    ):
        """
        Phase 0's headline result, restated at the web boundary.

        ``low`` abstracts secrets and nothing else, so if a level were going
        to leak one it would be this one — which is exactly why the loosest
        setting has to be tested, not just the strictest.
        """
        client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py', 'privacy_level': level,
        })

        prompt = fake_client.last_prompt
        for secret in SECRETS:
            assert secret not in prompt, f'leaked at privacy level {level}'


# ═══════════════════════════════════════════════════════════
# What comes back
# ═══════════════════════════════════════════════════════════

class TestResponseBodies:

    @pytest.mark.parametrize('level', PRIVACY_LEVELS)
    def test_abstract_response_carries_no_secret_outside_the_original_pane(
        self, client, level,
    ):
        assert_no_secrets(abstract(client, privacy_level=level))

    def test_review_response_carries_no_secret(self, client):
        data = client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        }).get_json()
        assert_no_secrets(data)

    def test_javascript_response_carries_no_secret(self, client):
        data = client.post('/api/abstract', json={
            'code': JS_SOURCE, 'filename': 'billing.js',
        }).get_json()
        assert_no_secrets(data, secrets=(STRIPE_KEY,))

    def test_the_abstract_code_itself_is_clean(self, client):
        code = abstract(client)['abstract_code']
        for secret in SECRETS:
            assert secret not in code

    def test_the_privacy_report_masks_rather_than_omits(self, client):
        """
        A report that simply dropped the secrets would be useless for
        compliance. It has to say a credential was there, and how long it
        was, without being a second copy of it.
        """
        data = abstract(client)
        markdown = data['report_markdown']

        for secret in SECRETS:
            assert secret not in markdown
        assert 'SECRET' in markdown
        assert any(row['masked'] for row in data['vault_rows'])

    def test_the_vault_pane_shows_masks_not_values(self, client):
        for row in abstract(client)['vault_rows']:
            if row['label'] == 'SECRET':
                assert 'chars)' in row['name']
                assert row['masked'] is True

    def test_a_tooltip_cannot_carry_a_secret(self, client):
        """
        The abstract pane puts the original name in a ``title`` attribute.

        That attribute is the least visible place a mask could be forgotten,
        which is why it is asserted separately from the vault table.
        """
        panes = abstract(client)['panes']['abstract']
        rendered = ' '.join(line['html'] for line in panes)
        for secret in SECRETS:
            assert secret not in rendered

    def test_session_detail_read_back_later_is_still_masked(self, client):
        """
        Masking is applied on the way out, not baked into what is stored.

        So it has to be re-applied when a session is read back — a different
        code path, and the one a user hits days later.
        """
        session_id = abstract(client)['session_id']
        detail = client.get(f'/api/sessions/{session_id}').get_json()
        assert_no_secrets(detail, allowed=())

    def test_reconstructed_feedback_never_restores_a_secret_value(self, client):
        """
        RECONSTRUCT's job is to put the original names back — which for a
        SECRET token means the credential itself. In a terminal that is the
        user's own screen. In a browser it is history, extensions and
        whatever is being screen-shared, so the masked mapping is what the
        reconstruction runs against.
        """
        data = abstract(client)
        secret_token = next(
            row['token'] for row in data['vault_rows'] if row['label'] == 'SECRET'
        )

        translated = client.post('/api/translate', json={
            'session_id': data['session_id'],
            'text': f'{secret_token} is hard-coded and should move to the environment.',
        }).get_json()

        assert_no_secrets(translated, allowed=())
        assert 'chars)' in translated['text']

    def test_source_context_blocks_are_scrubbed(self, client):
        """
        The subtle half of the previous test.

        RECONSTRUCT appends ±k lines of the *original* source around each
        cited symbol. Masking the name alone leaves the credential legible
        in the snippet printed underneath it.
        """
        data = abstract(client, context_window=5)
        token = next(
            row['token'] for row in data['vault_rows'] if row['label'] != 'SECRET'
        )

        translated = client.post('/api/translate', json={
            'session_id': data['session_id'], 'text': f'{token} is fine.',
        }).get_json()

        assert 'Source Context' in translated['text']
        for secret in SECRETS:
            assert secret not in translated['text']


# ═══════════════════════════════════════════════════════════
# The opt-out
# ═══════════════════════════════════════════════════════════

class TestReveal:
    """Masking has to be defeatable, or it is a bug rather than a policy."""

    def test_the_server_flag_alone_does_not_reveal(self, fake_client):
        from web import create_app

        app = create_app({'ALLOW_REVEAL': True, 'LLM_CLIENT': fake_client})
        data = app.test_client().post('/api/abstract', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        }).get_json()

        assert data['secrets_masked'] is True

    def test_both_gates_together_reveal(self, fake_client):
        from web import create_app

        app = create_app({'ALLOW_REVEAL': True, 'LLM_CLIENT': fake_client})
        data = app.test_client().post('/api/abstract', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py', 'reveal': True,
        }).get_json()

        assert data['secrets_masked'] is False
        assert any(STRIPE_KEY in row['name'] for row in data['vault_rows'])

    def test_revealing_still_does_not_change_what_is_sent(self, fake_client):
        """
        Reveal is a display setting. It must not widen the payload — the
        provider sees the same abstract code either way.
        """
        from web import create_app

        app = create_app({'ALLOW_REVEAL': True, 'LLM_CLIENT': fake_client})
        app.test_client().post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py', 'reveal': True,
        })

        for secret in SECRETS:
            assert secret not in fake_client.last_prompt


# ═══════════════════════════════════════════════════════════
# The compliance record
# ═══════════════════════════════════════════════════════════

class TestAuditTrail:
    """
    A web run has to be as accountable as a CLI one.

    The audit log is the proposal's compliance deliverable; a UI that
    bypassed it would leave a reviewer with a gap they cannot explain.
    """

    def test_a_web_abstraction_is_recorded(self, client):
        from storage import audit_log

        before = len(audit_log.read_entries())
        session_id = abstract(client)['session_id']
        entries = audit_log.read_entries()

        assert len(entries) > before
        assert any(e.get('session_id') == session_id for e in entries)

    def test_a_web_request_is_recorded_as_a_request(self, client):
        from storage import audit_log

        data = client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        }).get_json()

        requests = [
            e for e in audit_log.read_entries()
            if e.get('event') == 'request' and e.get('session_id') == data['session_id']
        ]
        assert requests
        assert requests[0]['provider'] == 'fake'
        assert requests[0]['payload_sha256'] == data['prompt_sha256']

    def test_the_log_marks_web_runs_as_web_runs(self, client):
        """
        No such file exists on this machine. Recording a plausible-looking
        path would send a reviewer looking for one.
        """
        from storage import audit_log

        session_id = abstract(client)['session_id']
        entry = next(
            e for e in audit_log.read_entries() if e.get('session_id') == session_id
        )
        assert entry['source_file'].startswith('<web>/')

    def test_the_log_records_metadata_not_content(self, client):
        from storage import audit_log

        client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        })
        text = json.dumps(audit_log.read_entries())

        for secret in SECRETS:
            assert secret not in text
        assert 'calculate_commission' not in text

    def test_the_hash_chain_still_verifies_after_web_runs(self, client):
        from storage import audit_log

        abstract(client)
        client.post('/api/review', json={
            'code': SECRET_SOURCE, 'filename': 'payments.py',
        })

        verification = audit_log.verify_chain()
        assert verification.ok, verification.problems


# ═══════════════════════════════════════════════════════════
# The server-side filesystem
# ═══════════════════════════════════════════════════════════

class TestNoServerSideFileAccess:
    """
    The CLI reads the path it is given. A server must not.

    This is the one respect in which the web interface has to be *stricter*
    than the tool it wraps: the same string that names the user's own file
    on their machine names someone else's file on a server.
    """

    @pytest.mark.parametrize('filename', [
        '../../../../etc/passwd',
        '..\\..\\..\\Windows\\System32\\drivers\\etc\\hosts',
        '/etc/shadow',
        'C:\\Users\\someone\\.ssh\\id_rsa',
    ])
    def test_a_path_is_treated_as_a_name(self, client, filename):
        """
        Every one of these either abstracts the *submitted* code or is
        rejected for its extension. None reads anything.
        """
        response = client.post('/api/abstract', json={
            'code': 'value = 1\n', 'filename': filename,
        })

        if response.status_code == 200:
            assert response.get_json()['filename'] in ('passwd', 'hosts',
                                                       'shadow', 'id_rsa')
        else:
            assert response.status_code == 400

    def test_a_path_never_survives_into_the_session_record(self, client):
        data = client.post('/api/abstract', json={
            'code': 'value = 1\n', 'filename': '../../secrets.py',
        }).get_json()

        listed = client.get('/api/sessions').get_json()['sessions']
        row = next(r for r in listed if r['session_id'] == data['session_id'])
        assert '..' not in row['source_file']

    def test_the_code_is_what_was_submitted_not_what_was_named(self, client):
        """
        The decisive assertion: the abstraction describes the posted buffer.

        If any path were honoured, the statistics would describe a different
        file entirely.
        """
        data = client.post('/api/abstract', json={
            'code': 'only_one_name = 1\n', 'filename': '/etc/passwd.py',
        }).get_json()

        assert data['statistics']['abstracted_nodes'] <= 2
        assert 'only_one_name' in [row['name'] for row in data['vault_rows']]
