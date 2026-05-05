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
