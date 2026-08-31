"""
Tests for `codeabstract review`.

Previously untested end to end. The LLM call is mocked (via
``commands.review_cmd.create_client``) so these run without network access
and deterministically, exercising the real abstract -> send -> reconstruct
-> display pipeline in between.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock, patch

_ANSI = re.compile(r"\x1b\[[0-9;]*m")

import pytest
from typer.testing import CliRunner

from cli import app
from llm.base import LLMResponse, TokenUsage

runner = CliRunner()

SECRET_SOURCE = '''api_key = "sk_live_51H8xQ2eZvKYlo2C"
def charge_customer(amount):
    return call_stripe(api_key, amount)
'''


def _fake_client(content, success=True, error=None):
    client = MagicMock()
    client.provider = "fake"
    client.model = "fake-model"
    client.send.return_value = LLMResponse(
        content=content, response_time=0.01, success=success, error=error,
        provider="fake", model="fake-model", usage=TokenUsage(), attempts=1,
    )
    return client


class TestReviewCommand:
    def test_missing_file_exits_nonzero(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        result = runner.invoke(app, ["review", str(tmp_path / "nope.py")])
        assert result.exit_code != 0

    def test_directory_input_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()

    def test_provider_failure_exits_nonzero_and_reports_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        f = tmp_path / "a.py"
        f.write_text("x = 1\n", encoding="utf-8")
        client = _fake_client("", success=False, error="rate limited")

        with patch("commands.review_cmd.create_client", return_value=client):
            result = runner.invoke(app, ["review", str(f)])

        assert result.exit_code != 0
        assert "rate limited" in result.output

    def test_secret_values_are_masked_by_default(self, tmp_path, monkeypatch):
        """
        Regression: `codeabstract review` reconstructed against the raw,
        unmasked session mapping, so its Source Context blocks printed
        live secret values to the terminal on every run, with no flag able
        to prevent it -- the same defect already fixed in
        `codeabstract translate`. Found by running the CLI end to end.
        """
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        f = tmp_path / "payments.py"
        f.write_text(SECRET_SOURCE, encoding="utf-8")
        client = _fake_client("The bug is that SECRET_0 is used insecurely.")

        with patch("commands.review_cmd.create_client", return_value=client):
            result = runner.invoke(app, ["review", str(f)])

        assert result.exit_code == 0
        assert "sk_live_51H8xQ2eZvKYlo2C" not in result.output

    def test_reveal_flag_shows_the_real_value(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        f = tmp_path / "payments.py"
        f.write_text(SECRET_SOURCE, encoding="utf-8")
        client = _fake_client("The bug is that SECRET_0 is used insecurely.")

        with patch("commands.review_cmd.create_client", return_value=client):
            result = runner.invoke(app, ["review", str(f), "--reveal"])

        assert result.exit_code == 0
        assert "sk_live_51H8xQ2eZvKYlo2C" in result.output

    def test_session_saved_still_holds_the_real_mapping(self, tmp_path, monkeypatch):
        """
        Masking the *display* must not weaken what's persisted: a later
        `apply`/`translate --reveal` still needs the real mapping.
        """
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        f = tmp_path / "payments.py"
        f.write_text(SECRET_SOURCE, encoding="utf-8")
        client = _fake_client("SECRET_0 looks fine.")

        with patch("commands.review_cmd.create_client", return_value=client):
            result = runner.invoke(app, ["review", str(f)])
        assert result.exit_code == 0

        session_id = None
        for line in result.output.splitlines():
            clean = _ANSI.sub("", line)
            if "Session:" in clean:
                session_id = clean.split("Session:")[-1].strip()
        assert session_id

        from storage.session_manager import load_session
        from algorithms.encrypt import decrypt_mapping

        session = load_session(session_id)
        mapping = decrypt_mapping(session["encrypted_mapping"], session["encryption_key"])
        secret_entry = next(e for e in mapping.values() if "SECRET" not in e["name"] and "sk_live" in e.get("name", ""))
        assert secret_entry["name"] == "sk_live_51H8xQ2eZvKYlo2C"

    def test_output_written_to_file_is_also_masked(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        f = tmp_path / "payments.py"
        f.write_text(SECRET_SOURCE, encoding="utf-8")
        out = tmp_path / "result.txt"
        client = _fake_client("SECRET_0 is a concern.")

        with patch("commands.review_cmd.create_client", return_value=client):
            result = runner.invoke(app, ["review", str(f), "--output", str(out)])

        assert result.exit_code == 0
        assert "sk_live_51H8xQ2eZvKYlo2C" not in out.read_text(encoding="utf-8")
