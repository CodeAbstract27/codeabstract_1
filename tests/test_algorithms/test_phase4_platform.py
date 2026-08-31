"""
Phase 4 platform regression suite.

Covers the six workstreams: the provider abstraction, free-form queries,
the privacy report, the audit log, the JavaScript/TypeScript adapter, and
key handling.

Two tests here are the ones that would matter in a defence:

``TestKeyHandling::test_database_alone_cannot_decrypt`` reads the raw
database row and asserts that nothing in it decrypts the mapping — the
Phase 4 exit criterion, checked against the storage layer rather than
against the API that is supposed to enforce it.

``TestQueryAbstraction::test_query_naming_an_identifier_is_tokenised``
asserts the thing free-form queries could most easily get wrong: a question
written in the user's own names would hand back exactly what the code
abstraction removed, in the same request.
"""

import json
import sqlite3

import pytest

from algorithms.abstract import abstract
from algorithms.encrypt import decrypt_mapping
from algorithms.reconstruct import reconstruct

# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

PYTHON_SOURCE = '''
import os
import stripe
from acme_internal.billing import ledger


def charge_customer(customer_id, amount):
    """Charge a customer."""
    stripe_api_key = "sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv"
    commission = amount * 0.029
    return ledger.record(customer_id, commission, stripe_api_key)
'''

JS_SOURCE = '''const express = require("express");
const { applyDiscount } = require("./pricing/rules");

// Checkout for the storefront.
const COUPON_SECRET = "whsec_9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c";

function checkoutCart(cartItems, customerTier) {
  let subtotal = 0;
  for (const item of cartItems) {
    subtotal += item.unitPrice * item.quantity;
  }
  return applyDiscount(subtotal, customerTier, COUPON_SECRET);
}

module.exports = { checkoutCart };
'''

TS_SOURCE = '''import express from "express";
import { chargeCard } from "./billing/ledger";

const STRIPE_KEY: string = "sk_live_51H8xYzAbCdEfGhIjKlMnOp";

export class PaymentGateway {
  private apiKey: string;

  constructor(apiKey: string) {
    this.apiKey = apiKey;
  }

  async charge(customerId: number, amount: number): Promise<boolean> {
    const headers = { Authorization: `Bearer ${this.apiKey}` };
    return chargeCard(customerId, amount * 0.029, headers);
  }
}
'''


def js_symbols(source, dialect='javascript'):
    """Parse with the adapter, skipping if the grammar is not installed."""
    from core.languages.javascript import JavaScriptAdapter

    adapter = JavaScriptAdapter(dialect=dialect)
    available, reason = adapter.availability()
    if not available:
        pytest.skip(reason)
    return adapter, adapter.symbols(source)


# ═══════════════════════════════════════════════════════════
# Provider abstraction
# ═══════════════════════════════════════════════════════════

class FlakyError(RuntimeError):
    """An error whose message marks it transient."""


class RecordingClient:
    """A client that records calls instead of making them."""

    def __init__(self, failures=0, error=None, content="VAR_0 looks wrong on line 2."):
        from llm.base import BaseLLMClient, RetryPolicy, TokenUsage

        self.failures = failures
        self.error = error or FlakyError("429 rate limit exceeded")
        self.content = content
        self.calls = 0
        self.slept = []

        outer = self

        class _Client(BaseLLMClient):
            provider = "recording"
            default_model = "test-model"

            def _generate(self, prompt):
                outer.calls += 1
                outer.last_prompt = prompt
                if outer.calls <= outer.failures:
                    raise outer.error
                return outer.content, TokenUsage(11, 7, reported=True)

        self.impl = _Client(
            api_key="test-key",
            retry=RetryPolicy(max_attempts=3, sleep=self.slept.append),
        )

    def send(self, *args, **kwargs):
        return self.impl.send(*args, **kwargs)

    @property
    def provider(self):
        return self.impl.provider

    @property
    def model(self):
        return self.impl.model


class TestProviderRegistry:
    """The factory must honour the provider argument it used to ignore."""

    def test_all_three_providers_are_registered(self):
        from llm import PROVIDERS

        assert set(PROVIDERS) == {'gemini', 'openai', 'anthropic'}

    def test_unknown_provider_names_the_alternatives(self):
        from llm import ProviderError, get_spec

        with pytest.raises(ProviderError) as excinfo:
            get_spec('bedrock')
        assert 'gemini' in str(excinfo.value)

    def test_explicit_provider_wins(self, monkeypatch):
        from llm import resolve_provider

        monkeypatch.setenv('CODEABSTRACT_PROVIDER', 'openai')
        assert resolve_provider('anthropic') == 'anthropic'

    def test_environment_provider_is_used_when_none_given(self, monkeypatch):
        from llm import resolve_provider

        monkeypatch.setenv('CODEABSTRACT_PROVIDER', 'openai')
        assert resolve_provider(None) == 'openai'

    def test_environment_key_beats_configured_key(self, monkeypatch):
        from llm import resolve_api_key

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'from-env')
        assert resolve_api_key('anthropic') == 'from-env'

    def test_no_usable_provider_explains_what_is_missing(self, monkeypatch):
        import llm

        monkeypatch.delenv('CODEABSTRACT_PROVIDER', raising=False)
        monkeypatch.setattr(llm, 'available_providers', lambda: [])
        monkeypatch.setattr(
            llm, 'get_config', lambda: type('C', (), {'get': lambda *_: ''})(),
            raising=False,
        )
        for var in ('GEMINI_API_KEY', 'GOOGLE_API_KEY', 'OPENAI_API_KEY',
                    'ANTHROPIC_API_KEY'):
            monkeypatch.delenv(var, raising=False)

        with pytest.raises(llm.ProviderError) as excinfo:
            llm.resolve_provider(None)
        assert 'pip install' in str(excinfo.value)

    def test_ambiguity_is_refused_rather_than_guessed(self, monkeypatch):
        import llm

        monkeypatch.delenv('CODEABSTRACT_PROVIDER', raising=False)
        monkeypatch.setattr(
            llm, 'available_providers', lambda: ['openai', 'anthropic']
        )
        monkeypatch.setenv('CODEABSTRACT_HOME', str(getattr(monkeypatch, '_home', '')))

        # A default in config would resolve it; without one, refuse.
        from config.settings import get_config
        get_config().set('default_provider', '')

        with pytest.raises(llm.ProviderError) as excinfo:
            llm.resolve_provider(None)
        assert '--provider' in str(excinfo.value)


class TestCreateClientLegacyKey:
    """
    Regression: ``create_client(api_key=..., provider=None)`` — the shape
    ``codeabstract review file.py --api-key <key>`` compiles to when
    ``--provider`` is omitted — used to try ``resolve_provider(None)``
    first and only fall back to the documented legacy default (gemini)
    when that raised. If the environment or config already had a *different*
    provider ready (e.g. ANTHROPIC_API_KEY set for unrelated tooling), the
    explicit key silently got attached to that provider's client instead —
    sending it to the wrong vendor's API on every request.
    """

    def test_explicit_key_always_uses_legacy_default_when_provider_omitted(
        self, monkeypatch
    ):
        from llm import LEGACY_DEFAULT_PROVIDER, create_client

        monkeypatch.delenv('GEMINI_API_KEY', raising=False)
        monkeypatch.delenv('GOOGLE_API_KEY', raising=False)
        monkeypatch.delenv('OPENAI_API_KEY', raising=False)
        # A different provider is fully ready via the environment.
        monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-unrelated-tooling-key')

        client = create_client(api_key='the-users-explicit-key')

        assert client.provider == LEGACY_DEFAULT_PROVIDER
        assert client.api_key == 'the-users-explicit-key'

    def test_explicit_provider_with_explicit_key_is_unaffected(self, monkeypatch):
        from llm import create_client

        monkeypatch.setenv('ANTHROPIC_API_KEY', 'sk-ant-unrelated-tooling-key')

        client = create_client(api_key='an-explicit-openai-key', provider='openai')

        assert client.provider == 'openai'
        assert client.api_key == 'an-explicit-openai-key'


class TestSharedClientBehaviour:
    """Retries, timing and token accounting live in one place for all providers."""

    def test_transient_failures_are_retried(self):
        client = RecordingClient(failures=2)
        response = client.send("VAR_0 = 1", task="review")

        assert response.success
        assert response.attempts == 3
        assert len(client.slept) == 2

    def test_backoff_grows(self):
        client = RecordingClient(failures=2)
        client.send("VAR_0 = 1")
        assert client.slept[1] > client.slept[0]

    def test_permanent_failures_are_not_retried(self):
        client = RecordingClient(
            failures=5, error=RuntimeError("invalid api key")
        )
        response = client.send("VAR_0 = 1")

        assert not response.success
        assert response.attempts == 1
        assert client.calls == 1

    def test_failure_is_reported_not_raised(self):
        client = RecordingClient(failures=9)
        response = client.send("VAR_0 = 1")

        assert response.success is False
        assert response.error

    def test_token_usage_is_normalised(self):
        response = RecordingClient().send("VAR_0 = 1")

        assert response.usage.prompt_tokens == 11
        assert response.usage.completion_tokens == 7
        assert response.usage.total_tokens == 18
        assert response.usage.reported is True

    def test_unreported_usage_is_distinguishable_from_zero(self):
        from llm.base import TokenUsage

        assert TokenUsage().reported is False
        assert TokenUsage(0, 0, reported=True).reported is True

    def test_transient_detection(self):
        from llm.base import is_transient

        assert is_transient(RuntimeError("429 Too Many Requests"))
        assert is_transient(RuntimeError("503 Service Unavailable"))
        assert is_transient(RuntimeError("connection reset by peer"))
        assert not is_transient(RuntimeError("invalid_api_key"))
        assert not is_transient(ValueError("model not found"))


class TestPromptAssembly:
    """One prompt shape for every provider, so comparisons mean something."""

    def test_preset_task(self):
        from llm.base import build_prompt

        prompt = build_prompt("VAR_0 = 1", task="security")
        assert "security issues" in prompt
        assert "```python" in prompt

    def test_free_form_query_replaces_the_preset(self):
        from llm.base import build_prompt

        prompt = build_prompt("VAR_0 = 1", task="security", query="Why is FUNC_0 slow?")
        assert "Why is FUNC_0 slow?" in prompt
        assert "security issues" not in prompt

    def test_language_sets_the_fence(self):
        from llm.base import build_prompt

        assert "```javascript" in build_prompt("x", language="javascript")


# ═══════════════════════════════════════════════════════════
# Free-form queries
# ═══════════════════════════════════════════════════════════

class TestQueryAbstraction:
    """A question in the user's own names would undo the abstraction."""

    def _mapping(self, source=PYTHON_SOURCE, level='high'):
        result = abstract(source, privacy_level=level)
        return result, decrypt_mapping(result.encrypted_mapping, result.encryption_key)

    def test_query_naming_an_identifier_is_tokenised(self):
        from core.query_abstractor import abstract_query

        _, mapping = self._mapping()
        outcome = abstract_query("why does charge_customer fail?", mapping)

        assert 'charge_customer' not in outcome.text
        assert any(token in outcome.text for token in mapping)
        assert outcome.substitutions

    def test_credential_pasted_into_the_query_is_redacted(self):
        from core.query_abstractor import abstract_query

        outcome = abstract_query(
            'it breaks with key "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"', {}
        )

        assert 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' not in outcome.text
        assert outcome.redactions
        assert outcome.mapping_additions

    def test_a_secret_already_in_the_mapping_reuses_its_token(self):
        from core.query_abstractor import abstract_query

        _, mapping = self._mapping()
        secret = "sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv"
        existing = next(
            token for token, entry in mapping.items() if entry['name'] == secret
        )

        outcome = abstract_query(f'why is "{secret}" rejected?', mapping)

        assert existing in outcome.text
        assert not outcome.mapping_additions

    def test_short_names_are_left_alone(self):
        from core.query_abstractor import abstract_query

        mapping = {'VAR_0': {'name': 'id', 'label': 'IDENTIFIER'}}
        outcome = abstract_query("what does id mean in this code?", mapping)

        assert 'id' in outcome.text
        assert not outcome.substitutions

    def test_non_identifier_names_are_not_substituted(self):
        from core.query_abstractor import abstract_query

        mapping = {'CONST_0': {'name': 'https://api.example.com', 'label': 'IDENTIFIER'}}
        outcome = abstract_query("is the endpoint reachable?", mapping)

        assert 'CONST_0' not in outcome.text

    def test_longest_name_wins_an_overlap(self):
        from core.query_abstractor import abstract_query

        mapping = {
            'FUNC_0': {'name': 'charge', 'label': 'IDENTIFIER'},
            'FUNC_1': {'name': 'charge_customer', 'label': 'IDENTIFIER'},
        }
        outcome = abstract_query("why does charge_customer fail?", mapping)

        assert 'FUNC_1' in outcome.text
        assert 'FUNC_0' not in outcome.text

    def test_query_minted_token_reconstructs(self):
        from algorithms.encrypt import encrypt_mapping
        from core.query_abstractor import abstract_query

        result, mapping = self._mapping()
        outcome = abstract_query(
            'why is "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" rejected?', mapping
        )
        mapping.update(outcome.mapping_additions)
        encrypted, key = encrypt_mapping(mapping)

        token = next(iter(outcome.mapping_additions))
        restored = reconstruct(f"The problem is {token}.", encrypted, key)

        assert 'ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789' in restored


# ═══════════════════════════════════════════════════════════
# Privacy report
# ═══════════════════════════════════════════════════════════

class TestPrivacyReport:
    """The report must lead with what was *kept*, and never copy a secret."""

    def _report(self, level='medium', reveal=False):
        from core.privacy_report import report_for_result

        result = abstract(PYTHON_SOURCE, privacy_level=level)
        return result, report_for_result(
            result, source_file='payments.py', privacy_level=level, reveal=reveal
        )

    def test_kept_names_are_recorded_with_reasons(self):
        _, report = self._report(level='low')

        assert report.kept
        reasons = {item.reason for item in report.kept}
        assert any('privacy level' in reason for reason in reasons)

    def test_allowlisted_import_is_recorded_as_kept(self):
        _, report = self._report(level='high')

        kept_names = {item.name for item in report.kept}
        assert any(name.startswith('os') for name in kept_names)
        assert any(item.reason == 'allowlisted module' for item in report.kept)

    def test_nothing_kept_at_critical(self):
        _, report = self._report(level='critical')

        level_kept = [
            item for item in report.kept if 'privacy level' in item.reason
        ]
        assert not level_kept

    def test_secret_values_are_masked_by_default(self):
        _, report = self._report()

        rendered = json.dumps(report.to_dict())
        assert 'sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv' not in rendered
        assert 'chars)' in rendered

    def test_reveal_shows_the_value(self):
        _, report = self._report(reveal=True)

        rendered = json.dumps(report.to_dict())
        assert 'sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv' in rendered

    def test_uncertain_items_are_below_the_threshold(self):
        from algorithms.classify import REVIEW_THRESHOLD

        _, report = self._report()

        assert all(item.confidence < REVIEW_THRESHOLD for item in report.uncertain)
        assert all(item in report.hidden for item in report.uncertain)

    def test_markdown_has_the_three_sections(self):
        _, report = self._report()
        markdown = report.to_markdown()

        assert 'Kept readable' in markdown
        assert 'Unsure' in markdown
        assert 'Hidden' in markdown

    def test_detector_version_is_recorded(self):
        from config.settings import detector_version

        _, report = self._report()
        assert report.detector_version == detector_version()

    def test_detector_version_changes_with_the_patterns(self, monkeypatch):
        import config.patterns
        from config.settings import detector_version

        before = detector_version()
        monkeypatch.setattr(
            config.patterns, 'SECRET_PATTERNS',
            config.patterns.SECRET_PATTERNS + [r'.*newpattern.*'],
        )
        assert detector_version() != before


# ═══════════════════════════════════════════════════════════
# Audit log
# ═══════════════════════════════════════════════════════════

class TestAuditLog:
    """A compliance record has to be complete, verifiable and content-free."""

    def test_entries_are_appended_in_order(self, tmp_path):
        from storage import audit_log

        path = tmp_path / "audit.log"
        audit_log.append_entry('abstract', path=path, source_file='a.py')
        audit_log.append_entry('request', path=path, source_file='b.py')

        entries = audit_log.read_entries(path=path)
        assert [e['seq'] for e in entries] == [1, 2]
        assert [e['event'] for e in entries] == ['abstract', 'request']

    def test_chain_verifies(self, tmp_path):
        from storage import audit_log

        path = tmp_path / "audit.log"
        for index in range(4):
            audit_log.append_entry('abstract', path=path, source_file=f'{index}.py')

        verification = audit_log.verify_chain(path=path)
        assert verification.ok
        assert verification.entries == 4

    def test_editing_an_entry_is_detected(self, tmp_path):
        from storage import audit_log

        path = tmp_path / "audit.log"
        audit_log.append_entry('abstract', path=path, source_file='a.py')
        audit_log.append_entry('abstract', path=path, source_file='b.py')

        lines = path.read_text(encoding='utf-8').splitlines()
        tampered = json.loads(lines[0])
        tampered['source_file'] = 'something_else.py'
        lines[0] = json.dumps(tampered, sort_keys=True, separators=(',', ':'))
        path.write_text("\n".join(lines) + "\n", encoding='utf-8')

        verification = audit_log.verify_chain(path=path)
        assert not verification.ok
        assert any('modified' in problem for problem in verification.problems)

    def test_deleting_an_entry_is_detected(self, tmp_path):
        from storage import audit_log

        path = tmp_path / "audit.log"
        for index in range(3):
            audit_log.append_entry('abstract', path=path, source_file=f'{index}.py')

        lines = path.read_text(encoding='utf-8').splitlines()
        path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding='utf-8')

        verification = audit_log.verify_chain(path=path)
        assert not verification.ok
        assert any('removed' in problem for problem in verification.problems)

    def test_reordering_entries_is_detected(self, tmp_path):
        from storage import audit_log

        path = tmp_path / "audit.log"
        for index in range(4):
            audit_log.append_entry('abstract', path=path, source_file=f'{index}.py')

        lines = path.read_text(encoding='utf-8').splitlines()
        reordered = [lines[0], lines[2], lines[1], lines[3]]
        path.write_text("\n".join(reordered) + "\n", encoding='utf-8')

        verification = audit_log.verify_chain(path=path)
        assert not verification.ok

    def test_appended_malformed_line_is_detected(self, tmp_path):
        from storage import audit_log

        path = tmp_path / "audit.log"
        audit_log.append_entry('abstract', path=path, source_file='a.py')

        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('this is not a json object\n')

        verification = audit_log.verify_chain(path=path)
        assert not verification.ok
        assert any('not a valid record' in problem for problem in verification.problems)

    def test_request_entry_records_provider_and_tokens(self, tmp_path):
        from storage import audit_log

        response = RecordingClient().send("VAR_0 = 1")
        entry = audit_log.record_request(
            session_id='abc',
            source_file='payments.py',
            provider='recording',
            model='test-model',
            privacy_level='high',
            payload_sha256=audit_log.payload_digest("VAR_0 = 1"),
            response=response,
            path=tmp_path / "audit.log",
        )

        assert entry['provider'] == 'recording'
        assert entry['tokens']['total_tokens'] == 18
        assert entry['detector_version']

    def test_the_log_records_no_content(self, tmp_path):
        from storage import audit_log

        path = tmp_path / "audit.log"
        result = abstract(PYTHON_SOURCE, privacy_level='high')
        audit_log.record_abstraction(
            session_id=result.session_id,
            source_file='payments.py',
            privacy_level='high',
            statistics=result.statistics,
            path=path,
        )
        audit_log.record_request(
            session_id=result.session_id,
            source_file='payments.py',
            provider='recording', model='test-model', privacy_level='high',
            payload_sha256=audit_log.payload_digest(result.abstract_code),
            path=path,
        )

        raw = path.read_text(encoding='utf-8')
        assert 'sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv' not in raw
        assert 'charge_customer' not in raw
        assert 'def ' not in raw

    def test_payload_digest_is_reproducible(self):
        from storage.audit_log import payload_digest

        assert payload_digest("abc") == payload_digest("abc")
        assert payload_digest("abc") != payload_digest("abd")

    def test_logging_can_be_disabled_by_environment(self, monkeypatch):
        from storage import audit_log

        monkeypatch.setenv('CODEABSTRACT_NO_AUDIT', '1')
        assert audit_log.logging_enabled() is False


# ═══════════════════════════════════════════════════════════
# Key handling
# ═══════════════════════════════════════════════════════════

class TestKeyHandling:
    """The database on its own must decrypt nothing."""

    def _save(self, session_id='11111111-1111-1111-1111-111111111111'):
        from storage.session_manager import save_session

        result = abstract(PYTHON_SOURCE, privacy_level='high')
        save_session(
            session_id=session_id,
            source_file_path='payments.py',
            context_window=3,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key,
            statistics=result.statistics,
            line_map=result.line_map,
        )
        return result

    def test_file_key_store_round_trip(self, tmp_path):
        from storage.key_store import FileKeyStore

        store = FileKeyStore(directory=tmp_path / "keys")
        reference = store.store('session-a', b'a-fernet-key')

        assert store.load(reference) == b'a-fernet-key'
        assert store.delete(reference) is True
        assert store.delete(reference) is False

    def test_loading_a_deleted_key_fails_cleanly(self, tmp_path):
        """A key removed after being stored (or never written) must raise
        a clear KeyStoreError, not an unhandled OSError."""
        from storage.key_store import FileKeyStore, KeyStoreError

        store = FileKeyStore(directory=tmp_path / "keys")
        reference = store.store('session-b', b'a-fernet-key')
        store.delete(reference)

        with pytest.raises(KeyStoreError):
            store.load(reference)

    def test_unrecognised_key_reference_fails_cleanly(self):
        from storage.key_store import KeyStoreError, load_session_key

        with pytest.raises(KeyStoreError):
            load_session_key('not-a-real-prefix:session-x')

    def test_path_traversal_in_session_id_is_contained(self, tmp_path):
        """A session id is a UUID from the database, but the key store
        builds a filesystem path from it -- a crafted id must not escape
        the key directory."""
        from storage.key_store import FileKeyStore

        directory = tmp_path / "keys"
        store = FileKeyStore(directory=directory)
        reference = store.store('../../etc/passwd', b'a-fernet-key')

        stored_files = list(directory.rglob('*.key'))
        assert len(stored_files) == 1
        assert stored_files[0].parent == directory
        assert store.load(reference) == b'a-fernet-key'

    def test_empty_session_id_is_rejected(self, tmp_path):
        from storage.key_store import FileKeyStore, KeyStoreError

        store = FileKeyStore(directory=tmp_path / "keys")
        with pytest.raises(KeyStoreError):
            store.store('', b'a-fernet-key')

    def test_corrupted_ciphertext_fails_closed(self):
        """Decryption must raise rather than return garbage or partial
        data when the ciphertext has been altered."""
        result = abstract(PYTHON_SOURCE, privacy_level='high')
        corrupted = result.encrypted_mapping[:-5] + b'XXXXX'

        with pytest.raises(ValueError):
            decrypt_mapping(corrupted, result.encryption_key)

    def test_wrong_key_fails_closed(self):
        from cryptography.fernet import Fernet

        result = abstract(PYTHON_SOURCE, privacy_level='high')
        wrong_key = Fernet.generate_key()

        with pytest.raises(ValueError):
            decrypt_mapping(result.encrypted_mapping, wrong_key)

    def test_database_alone_cannot_decrypt(self):
        from config.settings import get_db_path

        session_id = '22222222-2222-2222-2222-222222222222'
        self._save(session_id)

        connection = sqlite3.connect(str(get_db_path()))
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT * FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
        finally:
            connection.close()

        assert row['key_ref']
        assert not row['encryption_key']

        # The row's own bytes must not unlock the mapping.
        with pytest.raises(Exception):
            decrypt_mapping(row['encrypted_mapping'], row['encryption_key'])

    def test_session_still_loads_through_the_key_store(self):
        session_id = '33333333-3333-3333-3333-333333333333'
        original = self._save(session_id)

        from storage.session_manager import load_session

        session = load_session(session_id)
        mapping = decrypt_mapping(
            session['encrypted_mapping'], session['encryption_key']
        )
        assert mapping == decrypt_mapping(
            original.encrypted_mapping, original.encryption_key
        )

    def test_legacy_session_with_key_in_the_database_still_loads(self):
        from config.settings import get_db_path
        from storage.database import get_connection
        from storage.session_manager import load_session

        result = abstract(PYTHON_SOURCE, privacy_level='high')
        session_id = '44444444-4444-4444-4444-444444444444'

        connection = get_connection()
        try:
            connection.execute(
                """
                INSERT INTO sessions
                  (session_id, source_file_path, context_window,
                   encrypted_mapping, encryption_key, statistics_json,
                   line_map_json, key_ref)
                VALUES (?, ?, ?, ?, ?, '{}', '{}', '')
                """,
                (session_id, 'legacy.py', 3,
                 result.encrypted_mapping, result.encryption_key),
            )
            connection.commit()
        finally:
            connection.close()

        session = load_session(session_id)
        assert decrypt_mapping(
            session['encrypted_mapping'], session['encryption_key']
        )

    def test_migration_moves_a_legacy_key_out(self):
        from storage.database import get_connection
        from storage.key_store import migrate_legacy_keys

        result = abstract(PYTHON_SOURCE, privacy_level='high')
        session_id = '55555555-5555-5555-5555-555555555555'

        connection = get_connection()
        try:
            connection.execute(
                """
                INSERT INTO sessions
                  (session_id, source_file_path, context_window,
                   encrypted_mapping, encryption_key, statistics_json,
                   line_map_json, key_ref)
                VALUES (?, ?, ?, ?, ?, '{}', '{}', '')
                """,
                (session_id, 'legacy.py', 3,
                 result.encrypted_mapping, result.encryption_key),
            )
            connection.commit()
        finally:
            connection.close()

        migrated, failures = migrate_legacy_keys()
        assert migrated >= 1
        assert not failures

        connection = get_connection()
        try:
            row = connection.execute(
                "SELECT key_ref, encryption_key FROM sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        finally:
            connection.close()

        assert row['key_ref']
        assert not row['encryption_key']

        from storage.session_manager import load_session
        assert decrypt_mapping(
            load_session(session_id)['encrypted_mapping'],
            load_session(session_id)['encryption_key'],
        )

    def test_deleting_a_session_removes_its_key(self):
        from storage.key_store import load_session_key
        from storage.session_manager import delete_session, load_session

        session_id = '66666666-6666-6666-6666-666666666666'
        self._save(session_id)
        reference = load_session(session_id)['key_ref']

        assert delete_session(session_id) is True
        with pytest.raises(Exception):
            load_session_key(reference)

    def test_unknown_reference_is_refused(self):
        from storage.key_store import KeyStoreError, load_session_key

        with pytest.raises(KeyStoreError):
            load_session_key('vault:whatever')


# ═══════════════════════════════════════════════════════════
# JavaScript / TypeScript
# ═══════════════════════════════════════════════════════════

class TestJavaScriptAdapter:
    """The second language, and the claim that this is not an ast trick."""

    def _abstract(self, source, language='javascript', dialect='javascript', level='high'):
        from algorithms.abstract_source import abstract_source
        from core.languages.javascript import JavaScriptAdapter

        adapter = JavaScriptAdapter(dialect=dialect)
        available, reason = adapter.availability()
        if not available:
            pytest.skip(reason)

        return abstract_source(
            source, language=language, privacy_level=level, adapter=adapter,
        )

    def test_javascript_abstracts_and_reconstructs(self):
        result = self._abstract(JS_SOURCE)

        assert 'checkoutCart' not in result.abstract_code
        assert 'whsec_9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c' not in result.abstract_code

        restored = reconstruct(
            "FUNC_0 has a bug on line 8.",
            result.encrypted_mapping, result.encryption_key, result.line_map,
        )
        assert 'checkoutCart' in restored

    def test_abstract_output_still_parses(self):
        result = self._abstract(JS_SOURCE)
        adapter, _ = js_symbols(result.abstract_code)
        adapter.symbols(result.abstract_code)  # raises if it does not parse

    def test_no_secret_survives_any_level(self):
        for level in ('low', 'medium', 'high', 'critical'):
            result = self._abstract(JS_SOURCE, level=level)
            assert 'whsec_9f8a7b6c5d4e3f2a1b0c9d8e7f6a5b4c' not in result.abstract_code

    def test_allowlisted_module_is_preserved(self):
        result = self._abstract(JS_SOURCE)
        assert 'express' in result.abstract_code

    def test_internal_module_is_abstracted(self):
        result = self._abstract(JS_SOURCE)
        assert './pricing/rules' not in result.abstract_code
        assert 'MODULE_' in result.abstract_code

    def test_an_imported_name_gets_one_token_everywhere(self):
        result = self._abstract(JS_SOURCE)
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)

        tokens = [t for t, e in mapping.items() if e['name'] == 'applyDiscount']
        assert len(tokens) == 1
        # Declaration and call site both rewritten to that one token.
        assert result.abstract_code.count(tokens[0]) == 2

    def test_module_level_constant_keeps_one_token_inside_a_function(self):
        result = self._abstract(JS_SOURCE)
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)

        tokens = [t for t, e in mapping.items() if e['name'] == 'COUPON_SECRET']
        assert len(tokens) == 1
        assert result.abstract_code.count(tokens[0]) == 2

    def test_formatting_survives(self):
        """Byte-range rewriting keeps the file's shape — the line map's
        identity depends on it, so stripping a comment must not take its
        line with it."""
        result = self._abstract(JS_SOURCE)

        assert len(result.abstract_code.splitlines()) == len(JS_SOURCE.splitlines())

    def test_comments_are_stripped_by_default(self):
        """
        This assertion used to read the other way round.

        It asserted that ``// Checkout for the storefront.`` survived, which
        is what the adapter did — and the same path carried a comment
        holding a credential out to the LLM at every privacy level. The
        policy in ``core.comment_handler`` is not Python-specific: stripped
        by default, screened when kept.
        """
        result = self._abstract(JS_SOURCE)

        assert '// Checkout for the storefront.' not in result.abstract_code

    def test_comments_survive_when_explicitly_kept(self):
        from algorithms.abstract_source import abstract_source
        from core.languages.javascript import JavaScriptAdapter

        adapter = JavaScriptAdapter(dialect='javascript')
        available, reason = adapter.availability()
        if not available:
            pytest.skip(reason)

        result = abstract_source(
            JS_SOURCE, language='javascript', privacy_level='high',
            adapter=adapter, keep_comments=True,
        )
        assert '// Checkout for the storefront.' in result.abstract_code

    def test_line_map_is_the_identity(self):
        result = self._abstract(JS_SOURCE)

        assert result.line_map[7] == 7
        assert result.language == 'javascript'

    def test_a_syntax_error_is_refused(self):
        with pytest.raises(ValueError):
            self._abstract("function broken( {\n")

    def test_typescript_types_survive(self):
        result = self._abstract(TS_SOURCE, dialect='typescript')

        assert ': string' in result.abstract_code
        assert 'Promise<boolean>' in result.abstract_code
        assert 'sk_live_51H8xYzAbCdEfGhIjKlMnOp' not in result.abstract_code

    def test_typescript_property_and_field_share_a_token(self):
        result = self._abstract(TS_SOURCE, dialect='typescript')
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)

        tokens = [t for t, e in mapping.items() if e['name'] == 'apiKey']
        # The field and the constructor parameter are different bindings, so
        # two tokens; what must not happen is the field being written with
        # one token at its declaration and another at ``this.apiKey``.
        field_token = next(
            t for t, e in mapping.items()
            if e['name'] == 'apiKey' and e['node_type'] == 'property'
        )
        assert f'private {field_token}' in result.abstract_code
        assert f'this.{field_token}' in result.abstract_code
        assert len(tokens) <= 2

    def test_template_literal_credential_is_redacted(self):
        result = self._abstract(TS_SOURCE, dialect='typescript')
        assert 'Bearer ' not in result.abstract_code

    def test_language_globals_keep_their_names(self):
        source = "const items = [1, 2];\nconsole.log(items.length);\n"
        result = self._abstract(source)

        assert 'console' in result.abstract_code
        assert 'log' in result.abstract_code
        assert 'length' in result.abstract_code

    def test_detection_agrees_across_languages(self):
        """The same credential must classify identically in both engines."""
        from algorithms.classify import classify_signals

        python_decision = classify_signals(
            text='stripe_api_key', literal='sk_live_51H8xYzAbCdEfGhIjKlMnOp'
        )
        js_decision = classify_signals(
            text='stripeApiKey', literal='sk_live_51H8xYzAbCdEfGhIjKlMnOp'
        )

        assert python_decision.label == js_decision.label == 'SECRET'
        assert python_decision.detector == js_decision.detector


class TestLanguageRegistry:
    """Dispatch by extension, and refuse to guess."""

    def test_extensions_map_to_languages(self):
        from core.languages import detect_language

        assert detect_language('a/b/c.py') == 'python'
        assert detect_language('a/b/c.ts') == 'javascript'
        assert detect_language('a/b/c.jsx') == 'javascript'
        assert detect_language('a/b/c.rb') is None

    def test_unknown_extension_is_an_error_not_a_python_assumption(self, tmp_path):
        from algorithms.abstract_source import abstract_file

        path = tmp_path / "thing.rb"
        path.write_text("puts 'hi'\n", encoding='utf-8')

        with pytest.raises(ValueError) as excinfo:
            abstract_file(path)
        assert 'No language adapter' in str(excinfo.value)

    def test_python_is_routed_to_the_native_engine(self, tmp_path):
        from algorithms.abstract_source import abstract_file

        path = tmp_path / "thing.py"
        path.write_text(PYTHON_SOURCE, encoding='utf-8')

        result = abstract_file(path, privacy_level='high')
        assert result.language == 'python'
        assert 'sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv' not in result.abstract_code

    def test_typescript_dialect_is_chosen_from_the_extension(self):
        from core.languages.javascript import JavaScriptAdapter

        assert JavaScriptAdapter.dialect_for('.ts') == 'typescript'
        assert JavaScriptAdapter.dialect_for('.tsx') == 'tsx'
        assert JavaScriptAdapter.dialect_for('.js') == 'javascript'

    def test_edits_that_overlap_are_dropped_not_merged(self):
        from core.languages.base import Edit, apply_edits

        source = "abcdef"
        out = apply_edits(source, [Edit(0, 3, "X"), Edit(2, 5, "Y")])
        assert out in ("Xdef", "abYf")  # one wins; neither is interleaved


# ═══════════════════════════════════════════════════════════
# Cross-provider comparison
# ═══════════════════════════════════════════════════════════

class TestProviderComparison:
    """The same payload to every provider, and no quality claim from it."""

    def _corpus(self):
        return [{'name': 'payments.py', 'code': PYTHON_SOURCE, 'language': 'python'}]

    def test_no_clients_raises_rather_than_reporting_zeros(self):
        from evaluation.providers import collect_responses

        with pytest.raises(ValueError):
            collect_responses(self._corpus(), clients=[])

    def test_every_provider_sees_the_same_prompt(self):
        from evaluation.providers import collect_responses

        left, right = RecordingClient(), RecordingClient()
        collect_responses(self._corpus(), clients=[left, right])

        assert left.last_prompt == right.last_prompt

    def test_token_fidelity_rewards_using_real_tokens(self):
        from evaluation.providers import compare_providers

        result = abstract(PYTHON_SOURCE, privacy_level='high')
        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
        real_token = next(iter(mapping))

        faithful = RecordingClient(content=f"{real_token} is unused.")
        faithful.impl.provider = 'faithful'
        inventing = RecordingClient(content="FUNC_999 is unused.")
        inventing.impl.provider = 'inventing'

        comparison = compare_providers(
            self._corpus(), clients=[faithful, inventing]
        )
        scores = {s.provider: s for s in comparison.per_provider}

        assert scores['faithful'].token_fidelity == 1.0
        assert scores['inventing'].token_fidelity == 0.0

    def test_agreement_is_reported_pairwise(self):
        from evaluation.providers import compare_providers

        left = RecordingClient(content="There is a bug and a leak on line 3.")
        left.impl.provider = 'left'
        right = RecordingClient(content="There is a bug on line 3.")
        right.impl.provider = 'right'

        comparison = compare_providers(self._corpus(), clients=[left, right])

        assert 'left|right' in comparison.finding_agreement
        assert comparison.line_agreement['left|right'] == 1.0

    def test_comparison_carries_its_caveat(self):
        from evaluation.providers import compare_providers

        comparison = compare_providers(self._corpus(), clients=[RecordingClient()])
        assert 'quality' in comparison.caveat()
        assert 'blind rating' in comparison.caveat()


# ═══════════════════════════════════════════════════════════
# Guarantees from earlier phases
# ═══════════════════════════════════════════════════════════

class TestEarlierPhasesStillHold:
    """Phase 4 touched abstract.py and classify.py; neither may regress."""

    def test_no_secret_leaks_at_any_level(self):
        for level in ('low', 'medium', 'high', 'critical'):
            result = abstract(PYTHON_SOURCE, privacy_level=level)
            assert 'sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv' not in result.abstract_code

    def test_classification_tiers_are_unchanged(self):
        import ast

        from algorithms.classify import classify_with_evidence

        node = ast.parse('"sk_live_51H8xYzAbCdEfGhIjKlMnOpQrStUv"').body[0].value
        decision = classify_with_evidence(node)

        assert decision.label == 'SECRET'
        assert decision.detector == 'credential-format'
        assert decision.confidence == 0.99

    def test_numeric_literals_still_classify_as_value(self):
        import ast

        from algorithms.classify import classify_with_evidence

        node = ast.parse('0.029').body[0].value
        decision = classify_with_evidence(node)

        assert decision.label == 'VALUE'
        assert decision.detector == 'literal-type'

    def test_line_map_still_produced_for_python(self):
        result = abstract(PYTHON_SOURCE, privacy_level='high')
        assert result.line_map
