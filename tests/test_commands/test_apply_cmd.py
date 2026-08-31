"""
Tests for `codeabstract apply`.

Previously untested end to end. This command writes directly to the
developer's original source file, so the highest-value cases are the ones
where it must refuse to write rather than guess wrong.
"""

import pytest
from typer.testing import CliRunner

from cli import app
from algorithms.abstract import abstract
from storage.session_manager import save_session

runner = CliRunner()


class TestApplyCommand:
    def _create_session(self, source_path, source_code):
        source_path.write_text(source_code, encoding="utf-8")
        result = abstract(source_code, privacy_level="high")
        save_session(
            session_id=result.session_id,
            source_file_path=str(source_path),
            context_window=3,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key,
            statistics=result.statistics,
        )
        return result.session_id

    def test_requires_text_or_file(self, tmp_path):
        source = tmp_path / "a.py"
        sid = self._create_session(source, "x = 1\n")
        result = runner.invoke(app, ["apply", sid])
        assert result.exit_code != 0

    def test_unknown_session_exits_nonzero(self):
        result = runner.invoke(app, ["apply", "nonexistent-session", "some text"])
        assert result.exit_code != 0

    def test_whole_file_fix_applies_with_yes(self, tmp_path):
        source_code = "def calculate_total(amount):\n    fee = amount * 2\n    return fee\n"
        source = tmp_path / "calc.py"
        sid = self._create_session(source, source_code)

        result_obj = abstract(source_code, privacy_level="high")
        response = (
            "```python\n"
            + result_obj.abstract_code.replace("NUM_0", "NUM_0  # fixed")
            + "\n```\n"
        )

        result = runner.invoke(app, ["apply", sid, response, "--yes"])
        assert result.exit_code == 0
        written = source.read_text(encoding="utf-8")
        assert "fee = amount * 2  # fixed" in written
        assert "calculate_total" in written

    def test_fragment_is_never_written(self, tmp_path):
        source_code = "def calculate_total(amount):\n    fee = amount * 2\n    return fee\n"
        source = tmp_path / "calc.py"
        sid = self._create_session(source, source_code)

        result = runner.invoke(app, ["apply", sid, "```python\nx = 1\n```", "--yes"])
        assert result.exit_code == 0
        assert source.read_text(encoding="utf-8") == source_code

    def test_declining_confirmation_leaves_file_untouched(self, tmp_path):
        source_code = "def calculate_total(amount):\n    fee = amount * 2\n    return fee\n"
        source = tmp_path / "calc.py"
        sid = self._create_session(source, source_code)

        result_obj = abstract(source_code, privacy_level="high")
        response = "```python\n" + result_obj.abstract_code + "\n```\n"

        # No --yes: CliRunner feeds "n" to the confirmation prompt.
        result = runner.invoke(app, ["apply", sid, response], input="n\n")
        assert result.exit_code == 0
        assert source.read_text(encoding="utf-8") == source_code

    def test_unrelated_block_never_overwrites_a_no_def_script(self, tmp_path):
        """
        Regression for the apply_fix.py whole-file-detection defect: a
        script with no top-level def/class has nothing to structurally
        match, and an unrelated-but-long-enough code block must not be
        silently written over the user's file with --yes.
        """
        source_code = "x = 1\ny = 2\nprint(x + y)\n"
        source = tmp_path / "script.py"
        sid = self._create_session(source, source_code)

        response = (
            "Unrelated example:\n\n```python\n"
            "def unrelated_helper():\n    pass\n\n"
            "def another_one():\n    pass\n"
            "```\n"
        )
        result = runner.invoke(app, ["apply", sid, response, "--yes"])
        assert result.exit_code == 0
        assert source.read_text(encoding="utf-8") == source_code, (
            "an unrelated code block must never silently replace the "
            "developer's original file"
        )

    def test_output_flag_writes_restored_code_without_touching_source(self, tmp_path):
        source_code = "def calculate_total(amount):\n    fee = amount * 2\n    return fee\n"
        source = tmp_path / "calc.py"
        sid = self._create_session(source, source_code)
        out = tmp_path / "restored.py"

        result_obj = abstract(source_code, privacy_level="high")
        response = "```python\n" + result_obj.abstract_code + "\n```\n"

        result = runner.invoke(
            app, ["apply", sid, response, "--output", str(out)], input="n\n",
        )
        assert result.exit_code == 0
        assert "calculate_total" in out.read_text(encoding="utf-8")
        assert source.read_text(encoding="utf-8") == source_code

    def test_identical_suggestion_is_a_no_op(self, tmp_path):
        source_code = "def calculate_total(amount):\n    fee = amount * 2\n    return fee\n"
        source = tmp_path / "calc.py"
        sid = self._create_session(source, source_code)

        result_obj = abstract(source_code, privacy_level="high")
        response = "```python\n" + result_obj.abstract_code + "\n```\n"

        result = runner.invoke(app, ["apply", sid, response, "--yes"])
        assert result.exit_code == 0
        assert source.read_text(encoding="utf-8") == source_code
