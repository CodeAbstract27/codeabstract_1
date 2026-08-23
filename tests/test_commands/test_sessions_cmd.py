"""
Tests for CLI `sessions` sub-commands:
  - sessions list
  - sessions show
  - sessions delete --force

Uses Typer's CliRunner for isolation.
"""

import pytest
from typer.testing import CliRunner

from cli import app
from algorithms.abstract import abstract
from storage.session_manager import save_session
from tests.fixtures.sample_code import SAMPLE_PAYMENT_CODE

runner = CliRunner()


def _create_session() -> str:
    """Abstract code, persist to DB, return session ID."""
    result = abstract(SAMPLE_PAYMENT_CODE, privacy_level="high")
    save_session(
        session_id=result.session_id,
        source_file_path="test_file.py",
        context_window=3,
        encrypted_mapping=result.encrypted_mapping,
        encryption_key=result.encryption_key,
        statistics=result.statistics,
    )
    return result.session_id


class TestSessionsListCommand:
    """Tests for `codeabstract sessions list`."""

    def test_sessions_list_exits_zero(self):
        """Command should always exit with code 0."""
        result = runner.invoke(app, ["sessions", "list"])
        assert result.exit_code == 0

    def test_sessions_list_shows_table_headers(self):
        """Output should contain table column headers."""
        result = runner.invoke(app, ["sessions", "list"])
        output = result.output
        # At least one of the expected column names should appear
        assert any(
            keyword in output
            for keyword in ["Session", "Source", "Created", "Nodes", "ID"]
        )

    def test_sessions_list_limit_option(self):
        """--limit flag should be accepted without error."""
        result = runner.invoke(app, ["sessions", "list", "--limit", "5"])
        assert result.exit_code == 0


class TestSessionsShowCommand:
    """Tests for `codeabstract sessions show <id>`."""

    def test_sessions_show_valid_id(self):
        """Valid session ID should print session details and exit 0."""
        sid = _create_session()
        result = runner.invoke(app, ["sessions", "show", sid])
        assert result.exit_code == 0
        # Session ID should appear in output
        assert sid[:8] in result.output or sid in result.output

    def test_sessions_show_prefix(self):
        """Prefix of session ID should also work."""
        sid = _create_session()
        result = runner.invoke(app, ["sessions", "show", sid[:8]])
        assert result.exit_code == 0

    def test_sessions_show_invalid_id_fails(self):
        """Non-existent session ID should exit non-zero."""
        result = runner.invoke(app, ["sessions", "show", "00000000-dead-beef-0000-000000000000"])
        assert result.exit_code != 0


class TestSessionsDeleteCommand:
    """Tests for `codeabstract sessions delete <id>`."""

    def test_sessions_delete_with_force(self):
        """Deleting with --force should not prompt and should exit 0."""
        sid = _create_session()
        result = runner.invoke(app, ["sessions", "delete", sid, "--force"])
        assert result.exit_code == 0

    def test_sessions_delete_invalid_id(self):
        """Deleting a non-existent session should warn but not crash (exits 0)."""
        result = runner.invoke(
            app,
            ["sessions", "delete", "nonexistent-id-xyz-000", "--force"]
        )
        # CLI exits 0 and prints a warning — it does NOT raise a hard error
        assert result.exit_code == 0
        assert any(
            keyword in result.output.lower()
            for keyword in ["not found", "warning", "session"]
        )
