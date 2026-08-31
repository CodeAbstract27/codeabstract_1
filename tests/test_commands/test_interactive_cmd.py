"""
Tests for `codeabstract interactive`.

Previously untested. The questionary prompts are monkeypatched directly
(`commands.interactive_cmd.prompts.*`) since they read from an interactive
terminal; the rest of the pipeline (abstract, session save, reconstruct,
display) runs for real.
"""

from unittest.mock import patch

import pytest
import typer

from commands.interactive_cmd import run_interactive

SECRET_SOURCE = '''api_key = "sk_live_51H8xQ2eZvKYlo2C"
def charge_customer(amount):
    return call_stripe(api_key, amount)
'''


class TestInteractiveCommand:
    def test_secret_values_are_masked_in_translated_output(self, tmp_path, monkeypatch, capsys):
        """
        Regression: the interactive wizard reconstructed against the raw,
        unmasked session mapping -- the same defect already found and
        fixed in `codeabstract translate` and `codeabstract review` -- so
        its "Translated Feedback" panel printed live secret values to the
        terminal on every run.
        """
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
        source = tmp_path / "payments.py"
        source.write_text(SECRET_SOURCE, encoding="utf-8")

        with patch("commands.interactive_cmd.prompts.ask_file_path", return_value=str(source)), \
             patch("commands.interactive_cmd.prompts.ask_privacy_level", return_value="high"), \
             patch("commands.interactive_cmd.prompts.ask_context_window", return_value=3), \
             patch("commands.interactive_cmd.prompts.ask_copy_to_clipboard", return_value=False), \
             patch(
                 "commands.interactive_cmd.prompts.ask_llm_response",
                 return_value="SECRET_0 is used insecurely.",
             ):
            run_interactive()

        printed = capsys.readouterr().out
        assert "sk_live_51H8xQ2eZvKYlo2C" not in printed
        assert "masked" in printed.lower()

    def test_non_interactive_terminal_fails_cleanly(self, monkeypatch, capsys):
        """
        questionary/prompt_toolkit need a real attached console. Piped,
        redirected, or scripted/CI invocation previously surfaced a raw,
        library-internal traceback (prompt_toolkit's
        NoConsoleScreenBufferError on Windows) instead of an actionable
        error -- found by direct testing with stdin/stdout redirected.
        """
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("sys.stdout.isatty", lambda: False)

        with patch(
            "commands.interactive_cmd.prompts.ask_file_path",
            side_effect=RuntimeError("no console"),
        ):
            with pytest.raises(typer.Exit) as excinfo:
                run_interactive()

        assert excinfo.value.exit_code == 1
        printed = capsys.readouterr().out
        assert "real terminal" in printed.lower()

    def test_real_terminal_error_still_propagates(self, monkeypatch):
        """A genuine bug during a real interactive session (stdin/stdout
        both attached to a terminal) must not be swallowed."""
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("sys.stdout.isatty", lambda: True)

        with patch(
            "commands.interactive_cmd.prompts.ask_file_path",
            side_effect=RuntimeError("something else broke"),
        ):
            with pytest.raises(RuntimeError, match="something else broke"):
                run_interactive()
