"""Tests for CLI translate command."""

import os
import tempfile
import pytest
from typer.testing import CliRunner

from cli import app
from algorithms.abstract import abstract
from storage.session_manager import save_session
from tests.fixtures.sample_code import SAMPLE_PAYMENT_CODE

runner = CliRunner()


class TestTranslateCommand:

    def _create_session(self):
        result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
        save_session(
            session_id=result.session_id,
            source_file_path="test.py",
            context_window=3,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key,
            statistics=result.statistics,
        )
        return result.session_id

    def test_translate_with_text(self):
        sid = self._create_session()
        result = runner.invoke(app, ["translate", sid, "Check FUNC_0 for bugs"])
        assert result.exit_code == 0

    def test_translate_with_file(self):
        sid = self._create_session()
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, 'w') as f:
            f.write("FUNC_0 has a bug")
        try:
            result = runner.invoke(app, ["translate", sid, "--file", path])
            assert result.exit_code == 0
        finally:
            os.unlink(path)

    def test_translate_invalid_session(self):
        result = runner.invoke(app, ["translate", "nonexistent", "text"])
        assert result.exit_code != 0

    def test_translate_never_prints_secret_values_by_default(self):
        """
        Found by running the CLI end to end: `codeabstract translate`
        called RECONSTRUCT against the raw, unmasked mapping table, so its
        "Source Context" blocks (+/-k lines of the *original* source per
        symbol) printed live secret values to the terminal on every
        translate, with no flag able to prevent it -- not even the
        session's own STRIPE_API_KEY / PAYPAL_SECRET values in this very
        fixture. The web interface already masked the equivalent path
        (see test_web_privacy.py); the CLI now shares that logic via
        core.privacy_report.display_mapping.
        """
        sid = self._create_session()
        # References the token names directly, exactly as a real LLM
        # response would (RECONSTRUCT tells it these are "the exact names
        # to use"), so RECONSTRUCT appends a Source Context block for each
        # -- the mechanism that leaked in the original defect.
        response = "SECRET_0 and SECRET_2 are used as bearer tokens in SECRET_4."
        result = runner.invoke(app, ["translate", sid, response])

        assert result.exit_code == 0
        assert "sk_live_abc123def456ghi789" not in result.output
        assert "ppsecret_xyzabc123" not in result.output

    def test_translate_reveal_shows_the_real_values(self):
        """The opt-in counterpart: --reveal must still work."""
        sid = self._create_session()
        response = "SECRET_0 and SECRET_2 are used as bearer tokens in SECRET_4."
        result = runner.invoke(app, ["translate", sid, response, "--reveal"])

        assert result.exit_code == 0
        assert "sk_live_abc123def456ghi789" in result.output
        assert "ppsecret_xyzabc123" in result.output
