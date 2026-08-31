"""Tests for CLI abstract command."""

import os
import tempfile
import pytest
from typer.testing import CliRunner

from cli import app
from tests.fixtures.sample_code import SAMPLE_PAYMENT_CODE, SAMPLE_SIMPLE_CODE

runner = CliRunner()


class TestAbstractCommand:
    """Test suite for 'codeabstract abstract' CLI command."""

    def _write_temp_file(self, content, suffix=".py"):
        """Write content to a temp file and return its path."""
        fd, path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, 'w') as f:
            f.write(content)
        return path

    def test_abstract_basic(self):
        """Basic abstract command should succeed."""
        path = self._write_temp_file(SAMPLE_PAYMENT_CODE)
        try:
            result = runner.invoke(app, ["abstract", path])
            assert result.exit_code == 0
            assert "✓" in result.output or "Session ID" in result.output
        finally:
            os.unlink(path)

    def test_abstract_show_mapping(self):
        """--show-mapping flag should display statistics."""
        path = self._write_temp_file(SAMPLE_SIMPLE_CODE)
        try:
            result = runner.invoke(app, ["abstract", path, "--show-mapping"])
            assert result.exit_code == 0
            assert "Abstraction Statistics" in result.output or "Total" in result.output
        finally:
            os.unlink(path)

    def test_abstract_output_file(self):
        """--output flag should save abstract code to file."""
        path = self._write_temp_file(SAMPLE_PAYMENT_CODE)
        fd, out_path = tempfile.mkstemp(suffix=".py")
        os.close(fd)
        try:
            result = runner.invoke(app, ["abstract", path, "--output", out_path])
            assert result.exit_code == 0
            with open(out_path, 'r') as f:
                content = f.read()
            assert len(content) > 0
        finally:
            os.unlink(path)
            if os.path.exists(out_path):
                os.unlink(out_path)

    def test_abstract_file_not_found(self):
        """Non-existent file should fail gracefully."""
        result = runner.invoke(app, ["abstract", "nonexistent_file.py"])
        assert result.exit_code != 0

    def test_abstract_directory_gives_a_clear_error(self, tmp_path):
        """
        A directory `.exists()` too, and has no suffix. Before this was
        fixed, passing one fell through to language detection and failed
        there with "No language adapter for ''" -- misleading, since the
        actual problem (a directory, not a file) was never stated.
        """
        result = runner.invoke(app, ["abstract", str(tmp_path)])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()
        assert "language adapter" not in result.output.lower()

    def test_abstract_privacy_levels(self):
        """All privacy levels should work."""
        path = self._write_temp_file(SAMPLE_PAYMENT_CODE)
        try:
            for level in ["low", "medium", "high", "critical"]:
                result = runner.invoke(app, ["abstract", path, "--privacy", level])
                assert result.exit_code == 0, f"Failed for privacy={level}"
        finally:
            os.unlink(path)

    def test_abstract_invalid_privacy_level_is_rejected(self):
        """
        An unrecognised ``--privacy`` value was silently accepted and
        passed straight through to the abstraction engine, which falls
        back to 'medium' for an unknown level -- found by direct
        adversarial testing. A typo like ``hihg`` (meant to be ``high``)
        must be refused, not silently downgraded with no indication
        anything was wrong.
        """
        path = self._write_temp_file(SAMPLE_PAYMENT_CODE)
        try:
            result = runner.invoke(app, ["abstract", path, "--privacy", "nonsense"])
            assert result.exit_code != 0
            assert "not a valid privacy level" in result.output
        finally:
            os.unlink(path)

    def test_abstract_context_window(self):
        """Custom context window should work."""
        path = self._write_temp_file(SAMPLE_PAYMENT_CODE)
        try:
            result = runner.invoke(app, ["abstract", path, "-k", "5"])
            assert result.exit_code == 0
        finally:
            os.unlink(path)

    def test_abstract_negative_context_window_is_rejected(self):
        """
        A negative window flows straight into get_context()'s start/end
        line arithmetic (which assumes k >= 0) and silently produces an
        inverted range and an empty context snippet rather than an error --
        found by direct adversarial testing. The CLI must refuse it rather
        than accept it and quietly degrade the output.
        """
        path = self._write_temp_file(SAMPLE_PAYMENT_CODE)
        try:
            result = runner.invoke(app, ["abstract", path, "-k", "-5"])
            assert result.exit_code != 0
        finally:
            os.unlink(path)
