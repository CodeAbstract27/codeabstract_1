"""
Tests for CLI `stats` command.
"""

import pytest
from typer.testing import CliRunner

from cli import app

runner = CliRunner()


class TestStatsCommand:
    """Test suite for `codeabstract stats`."""

    def test_stats_exits_zero(self):
        """stats command should always exit with code 0."""
        result = runner.invoke(app, ["stats"])
        assert result.exit_code == 0

    def test_stats_output_contains_session_info(self):
        """Stats output should mention sessions or usage-related keywords."""
        result = runner.invoke(app, ["stats"])
        output = result.output.lower()
        assert any(
            keyword in output
            for keyword in ["session", "total", "secret", "abstract", "stat"]
        )
