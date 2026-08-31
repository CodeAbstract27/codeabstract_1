"""
Tests for `codeabstract providers` and `codeabstract languages`.

Previously untested. Focus: the readiness table never leaks a key value,
and a directory/missing-file input is rejected cleanly rather than
crashing partway through provider setup.
"""

import pytest
from typer.testing import CliRunner

from cli import app

runner = CliRunner()


class TestProvidersList:
    def test_exits_zero_and_never_prints_a_configured_key(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-SUPER-SECRET-VALUE")

        result = runner.invoke(app, ["providers", "list"])

        assert result.exit_code == 0
        assert "sk-ant-SUPER-SECRET-VALUE" not in result.output
        assert "anthropic" in result.output.lower()

    def test_lists_all_supported_providers(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        result = runner.invoke(app, ["providers", "list"])
        assert result.exit_code == 0
        for name in ("gemini", "openai", "anthropic"):
            assert name in result.output.lower()


class TestLanguagesList:
    def test_exits_zero(self):
        result = runner.invoke(app, ["languages"])
        assert result.exit_code == 0
        assert "python" in result.output.lower()


class TestProvidersCompare:
    def test_missing_file_exits_nonzero(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        result = runner.invoke(app, ["providers", "compare", str(tmp_path / "nope.py")])
        assert result.exit_code != 0

    def test_directory_input_rejected_not_crashed(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        result = runner.invoke(app, ["providers", "compare", str(tmp_path)])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()

    def test_no_ready_provider_reports_cleanly(self, monkeypatch, tmp_path):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        for var in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
            monkeypatch.delenv(var, raising=False)
        source = tmp_path / "a.py"
        source.write_text("x = 1\n", encoding="utf-8")

        result = runner.invoke(app, ["providers", "compare", str(source)])
        assert result.exit_code != 0
