"""
Tests for the web pipeline itself (``web.service``).

No Flask here. These exercise the layer the routes are thin over — which is
where validation, masking and persistence actually happen — so a failure
points at the pipeline rather than at a request handler.
"""

import pytest

from tests.test_web.conftest import SECRETS, STRIPE_KEY
from web import service
from web.service import WebServiceError


# ═══════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════

class TestValidation:
    """The guards on everything a browser can send."""

    @pytest.mark.parametrize('level', ['low', 'medium', 'high', 'critical'])
    def test_accepts_every_privacy_level(self, level):
        assert service.validate_privacy(level) == level

    def test_privacy_level_is_case_insensitive(self):
        assert service.validate_privacy('HIGH') == 'high'

    def test_unknown_privacy_level_lists_the_alternatives(self):
        with pytest.raises(WebServiceError) as exc:
            service.validate_privacy('paranoid')
        assert 'critical' in str(exc.value)

    def test_missing_privacy_level_defaults_to_high(self):
        assert service.validate_privacy(None) == 'high'

    def test_context_window_is_bounded(self):
        with pytest.raises(WebServiceError):
            service.validate_context_window(service.MAX_CONTEXT_WINDOW + 1)

    def test_context_window_rejects_negative(self):
        with pytest.raises(WebServiceError):
            service.validate_context_window(-1)

    def test_context_window_rejects_nonsense(self):
        with pytest.raises(WebServiceError):
            service.validate_context_window('three')

    def test_context_window_accepts_zero(self):
        assert service.validate_context_window(0) == 0

    def test_empty_source_is_rejected(self):
        with pytest.raises(WebServiceError):
            service.validate_source('   \n  ')

    def test_oversized_source_is_413(self):
        with pytest.raises(WebServiceError) as exc:
            service.validate_source('x' * (service.MAX_SOURCE_BYTES + 1))
        assert exc.value.status == 413

    def test_oversized_query_is_rejected(self):
        with pytest.raises(WebServiceError):
            service.validate_query('?' * (service.MAX_QUERY_CHARS + 1))

    def test_blank_query_becomes_none(self):
        assert service.validate_query('   ') is None

    def test_unknown_task_is_rejected(self):
        with pytest.raises(WebServiceError):
            service.validate_task('rewrite-everything')


class TestFilenameHandling:
    """
    A filename from a browser is a label, never a path.

    These are the tests that matter for the difference between this and the
    CLI: ``codeabstract abstract ../../etc/passwd`` reads a file the user
    already has, whereas a *server* honouring the same string reads a file
    the user may not.
    """

    def test_windows_fakepath_is_reduced(self):
        assert service.safe_filename(r'C:\fakepath\app.py') == 'app.py'

    def test_posix_path_is_reduced(self):
        assert service.safe_filename('/home/someone/src/app.py') == 'app.py'

    def test_traversal_is_reduced_to_a_name(self):
        assert service.safe_filename('../../../etc/passwd') == 'passwd'

    def test_traversal_never_survives_as_a_path(self):
        for candidate in ['../secrets.py', '..\\..\\secrets.py', 'a/b/../secrets.py']:
            assert service.safe_filename(candidate) == 'secrets.py'

    def test_empty_filename_is_rejected(self):
        with pytest.raises(WebServiceError):
            service.safe_filename('')

    def test_leading_dots_do_not_produce_a_hidden_path(self):
        assert service.safe_filename('...py') == 'py'

    def test_unknown_extension_names_what_is_supported(self):
        with pytest.raises(WebServiceError) as exc:
            service.resolve_language('notes.txt')
        assert '.py' in str(exc.value)

    @pytest.mark.parametrize('name,language', [
        ('app.py', 'python'),
        ('types.pyi', 'python'),
        ('index.js', 'javascript'),
        ('index.ts', 'javascript'),
    ])
    def test_extension_picks_the_adapter(self, name, language):
        assert service.resolve_language(name) == language


# ═══════════════════════════════════════════════════════════
# Abstraction
# ═══════════════════════════════════════════════════════════

class TestRunAbstraction:
    """ABSTRACT(S, k) as the browser drives it."""

    def test_produces_every_output_the_proposal_names(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=False)

        assert outcome.abstract_code                     # sent to the LLM
        assert outcome.vault                             # local vault
        assert outcome.report.hidden                     # privacy report
        assert outcome.original_code == secret_source
        assert outcome.language == 'python'

    def test_abstract_code_is_valid_python(self, secret_source):
        import ast

        outcome = service.run_abstraction(secret_source, 'payments.py', save=False)
        ast.parse(outcome.abstract_code)                 # raises on failure

    def test_line_map_pairs_the_two_panes(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=False)

        assert outcome.line_map, "no line index — the panes cannot be paired"
        original_lines = len(secret_source.split('\n'))
        assert all(1 <= v <= original_lines for v in outcome.line_map.values())

    def test_the_four_levels_produce_four_different_outputs(self, secret_source):
        outputs = {
            level: service.run_abstraction(
                secret_source, 'payments.py', privacy_level=level, save=False,
            ).abstract_code
            for level in ('low', 'medium', 'high', 'critical')
        }
        assert len(set(outputs.values())) == 4

    def test_javascript_goes_through_the_same_pipeline(self):
        from tests.test_web.conftest import JS_SOURCE

        outcome = service.run_abstraction(JS_SOURCE, 'billing.js', save=False)
        assert outcome.language == 'javascript'
        assert outcome.vault

    def test_syntax_error_is_a_400_naming_the_line(self):
        with pytest.raises(WebServiceError) as exc:
            service.run_abstraction('def broken(:\n    pass\n', 'broken.py', save=False)
        assert exc.value.status == 400
        assert 'line' in str(exc.value).lower()

    def test_saved_session_can_be_loaded_back(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=True)

        assert outcome.saved, outcome.save_error
        detail = service.session_detail(outcome.session_id)
        assert detail['session_id'] == outcome.session_id
        assert len(detail['vault']) == len(outcome.vault)

    def test_unsaved_run_leaves_nothing_behind(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=False)

        assert outcome.saved is False
        with pytest.raises(WebServiceError) as exc:
            service.session_detail(outcome.session_id)
        assert exc.value.status == 404

    def test_vault_is_ordered_by_position_in_the_file(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=False)
        linenos = [entry.lineno for entry in outcome.vault]
        assert linenos == sorted(linenos)


# ═══════════════════════════════════════════════════════════
# Masking
# ═══════════════════════════════════════════════════════════

class TestMasking:
    """The rule that separates a browser pane from a terminal."""

    def test_secret_names_are_masked(self):
        table = {'SECRET_0': {'name': STRIPE_KEY, 'label': 'SECRET', 'lineno': 3}}
        masked = service.mask_mapping_table(table)

        assert STRIPE_KEY not in masked['SECRET_0']['name']
        # The length survives the mask: it identifies which credential this
        # was without being usable as one.
        assert f'{len(STRIPE_KEY)} chars' in masked['SECRET_0']['name']

    def test_secrets_are_scrubbed_from_other_entries_context(self):
        """
        The credential's own entry is the easy half.

        The line that bound it is also the ±k context of every *neighbouring*
        symbol, so masking only the entry that owns it leaves the value
        legible in the snippets around it.
        """
        table = {
            'SECRET_0': {'name': STRIPE_KEY, 'label': 'SECRET', 'lineno': 3},
            'VAR_0': {
                'name': 'commission_rate',
                'label': 'VALUE',
                'lineno': 4,
                'ctx': {'snippet': f'KEY = "{STRIPE_KEY}"\ncommission_rate = 0.029'},
            },
        }
        masked = service.mask_mapping_table(table)
        assert STRIPE_KEY not in masked['VAR_0']['ctx']['snippet']

    def test_masking_does_not_mutate_the_caller(self):
        table = {'SECRET_0': {'name': STRIPE_KEY, 'label': 'SECRET', 'lineno': 3}}
        service.mask_mapping_table(table)
        assert table['SECRET_0']['name'] == STRIPE_KEY

    def test_non_secret_names_survive_intact(self):
        table = {'VAR_0': {'name': 'commission_rate', 'label': 'VALUE', 'lineno': 4}}
        masked = service.mask_mapping_table(table)
        assert masked['VAR_0']['name'] == 'commission_rate'

    def test_reveal_returns_the_real_names(self):
        table = {'SECRET_0': {'name': STRIPE_KEY, 'label': 'SECRET', 'lineno': 3}}
        assert service.display_mapping(table, reveal=True)['SECRET_0']['name'] == STRIPE_KEY

    def test_a_short_secret_inside_a_longer_one_masks_both(self):
        """Longest-first, or the short one eats the prefix of the long one."""
        short, long = 'sk_live_ABCDEF', 'sk_live_ABCDEF_GHIJKLMNOP'
        table = {
            'SECRET_0': {'name': short, 'label': 'SECRET', 'lineno': 1},
            'SECRET_1': {
                'name': long, 'label': 'SECRET', 'lineno': 2,
                'ctx': {'snippet': f'a = "{long}"'},
            },
        }
        masked = service.mask_mapping_table(table)
        assert long not in masked['SECRET_1']['ctx']['snippet']


# ═══════════════════════════════════════════════════════════
# Reconstruction
# ═══════════════════════════════════════════════════════════

class TestRunTranslation:
    """RECONSTRUCT(R, M̃, K) against a stored session."""

    def test_round_trips_a_response(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=True)
        token = next(e.token for e in outcome.vault if e.label != 'SECRET')
        name = next(e.name for e in outcome.vault if e.token == token)

        result = service.run_translation(outcome.session_id, f"{token} is fine.")
        assert name in result['text']
        assert result['tokens_resolved'] == 1

    def test_accepts_a_session_prefix(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=True)
        result = service.run_translation(outcome.session_id[:8], "No issues.")
        assert result['session_id'] == outcome.session_id

    def test_unknown_session_is_404(self):
        with pytest.raises(WebServiceError) as exc:
            service.run_translation('0' * 32, "Anything.")
        assert exc.value.status == 404

    def test_empty_response_is_rejected(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=True)
        with pytest.raises(WebServiceError):
            service.run_translation(outcome.session_id, '   ')

    def test_unresolvable_tokens_are_counted_not_hidden(self, secret_source):
        """
        A token the mapping does not know is the one silent failure mode.

        The prose still reads correctly, so the count is what tells the user
        the response did not come from this session.
        """
        outcome = service.run_abstraction(secret_source, 'payments.py', save=True)
        result = service.run_translation(outcome.session_id, "VAR_9999 looks wrong.")

        assert result['tokens_seen'] == 1
        assert result['tokens_resolved'] == 0
        assert 'VAR_9999' in result['text']

    def test_collision_between_var_1_and_var_10(self, secret_source):
        """
        Phase 0's D2, at the web boundary.

        A response naming both must substitute each whole. This is the
        defect that produced ``name (line 2)0``, and it reappears anywhere a
        new substitution pass is written.
        """
        outcome = service.run_abstraction(
            secret_source, 'payments.py', privacy_level='critical', save=True,
        )
        tokens = {e.token: e.name for e in outcome.vault}
        if 'VAR_1' not in tokens or 'VAR_10' not in tokens:
            pytest.skip("this source did not allocate both VAR_1 and VAR_10")

        result = service.run_translation(outcome.session_id, "VAR_1 and VAR_10 differ.")
        assert f"{tokens['VAR_10']} (line" in result['text']
        assert '0 and' not in result['text']


# ═══════════════════════════════════════════════════════════
# Review
# ═══════════════════════════════════════════════════════════

class TestRunReview:
    """Abstract → LLM → Reconstruct, with a stand-in provider."""

    def test_full_round_trip(self, secret_source, fake_client):
        outcome = service.run_review(
            secret_source, 'payments.py', client=fake_client,
        )

        assert outcome.provider == 'fake'
        assert fake_client.calls, "the provider was never called"
        assert outcome.raw_response
        assert outcome.mapped_feedback != outcome.raw_response

    def test_the_provider_receives_only_abstract_code(self, secret_source, fake_client):
        service.run_review(secret_source, 'payments.py', client=fake_client)

        sent = fake_client.calls[0]['abstract_code']
        for secret in SECRETS:
            assert secret not in sent
        assert 'calculate_commission' not in sent
        assert 'STRIPE_API_KEY' not in sent

    def test_a_free_form_question_is_abstracted_too(self, secret_source, fake_client):
        """
        The question names what the code just stopped naming.

        Sending it verbatim would undo the abstraction in the same request,
        which is precisely the hole ``core.query_abstractor`` exists to close.
        """
        outcome = service.run_review(
            secret_source, 'payments.py',
            query=f"Why does calculate_commission use {STRIPE_KEY}?",
            client=fake_client,
        )

        assert STRIPE_KEY not in fake_client.last_prompt
        assert 'calculate_commission' not in fake_client.last_prompt
        assert outcome.query_redactions >= 1

    def test_a_failed_provider_call_is_502(self, secret_source):
        from tests.test_web.conftest import FakeLLMClient

        broken = FakeLLMClient(success=False, error='rate limited')
        with pytest.raises(WebServiceError) as exc:
            service.run_review(secret_source, 'payments.py', client=broken)
        assert exc.value.status == 502

    def test_review_without_saving_still_reconstructs(self, secret_source, fake_client):
        outcome = service.run_review(
            secret_source, 'payments.py', save=False, client=fake_client,
        )
        assert outcome.abstraction.saved is False
        assert outcome.mapped_feedback

    def test_prompt_digest_matches_what_was_sent(self, secret_source, fake_client):
        from storage import audit_log

        outcome = service.run_review(secret_source, 'payments.py', client=fake_client)
        assert outcome.prompt_sha256 == audit_log.payload_digest(
            fake_client.last_prompt
        )


# ═══════════════════════════════════════════════════════════
# Sessions and capabilities
# ═══════════════════════════════════════════════════════════

class TestSessions:

    def test_recent_sessions_carry_no_mapping_material(self, secret_source):
        service.run_abstraction(secret_source, 'payments.py', save=True)
        rows = service.recent_sessions(5)

        assert rows
        for row in rows:
            assert 'encrypted_mapping' not in row
            assert 'encryption_key' not in row
            assert 'vault' not in row

    def test_delete_removes_the_session(self, secret_source):
        outcome = service.run_abstraction(secret_source, 'payments.py', save=True)
        assert service.remove_session(outcome.session_id)['deleted'] is True

        with pytest.raises(WebServiceError) as exc:
            service.session_detail(outcome.session_id)
        assert exc.value.status == 404

    def test_blank_session_id_is_rejected(self):
        with pytest.raises(WebServiceError):
            service.session_detail('  ')


class TestCapabilityReporting:

    def test_providers_separate_install_from_key(self):
        for option in service.provider_options():
            assert set(option) >= {'provider', 'installed', 'has_key', 'ready', 'hint'}
            assert option['ready'] == (option['installed'] and option['has_key'])
            if not option['ready']:
                assert option['hint'], "an unready provider must say what to do"

    def test_languages_report_availability(self):
        names = {item['language'] for item in service.language_options()}
        assert {'python', 'javascript'} <= names

    def test_privacy_options_cover_all_four_levels(self):
        assert len(service.privacy_options()) == 4

    def test_task_options_include_the_presets(self):
        assert 'review' in service.task_options()
