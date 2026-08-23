"""
Regression: passing a directory to a file-taking CLI command must fail
with a message that says so.

Found by direct adversarial testing (`codeabstract abstract <a directory>`),
not by inspection: ``Path.exists()`` is true for a directory, and a
directory's ``.suffix`` is empty, so every command that checked only
``exists()`` before calling ``detect_language()`` fell through to
"No language adapter for ''" -- true, but not the actual problem, and
confusing enough that a user would go looking for a missing file-extension
handler that was never the issue.

Covers every command that had the same copy-pasted ``exists()`` check:
``abstract`` (see also ``test_abstract_cmd.py`` for the fuller regression),
``review``, and ``providers compare``. All three are checked here rather
than only the one first reproduced in, so a future copy-paste of the same
pattern into a new command is the only way this suite would need a new
case.
"""


from typer.testing import CliRunner

from cli import app

runner = CliRunner()


class TestDirectoryRejectedAsFileInput:

    def test_review_command_rejects_a_directory(self, tmp_path):
        result = runner.invoke(app, ["review", str(tmp_path)])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()
        assert "language adapter" not in result.output.lower()

    def test_providers_compare_rejects_a_directory(self, tmp_path):
        result = runner.invoke(app, ["providers", "compare", str(tmp_path)])
        assert result.exit_code != 0
        assert "directory" in result.output.lower()
        assert "language adapter" not in result.output.lower()
