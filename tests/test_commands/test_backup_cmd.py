"""
Tests for the `backup` / `restore` CLI commands.

These commands operate on the *whole* application directory
(config.settings.get_app_dir()), which the rest of the CLI test suite
shares as one CODEABSTRACT_HOME for the session (see tests/conftest.py).
Running `restore` against that shared directory would overwrite state
every other CLI test depends on, so every test here that actually writes
gets its own private CODEABSTRACT_HOME via monkeypatch, the same pattern
tests/test_web/conftest.py uses for the same reason.
"""

import zipfile
from pathlib import Path

import pytest
from typer.testing import CliRunner

from algorithms.abstract import abstract
from cli import app
from storage.session_manager import save_session

runner = CliRunner()


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """A private ~/.codeabstract for one test."""
    home = tmp_path / "home"
    monkeypatch.setenv("CODEABSTRACT_HOME", str(home))
    return home


def _seed_session(home: Path) -> str:
    """Create one real session (db row + key file + audit entry) under *home*."""
    result = abstract('API_KEY = "sk_live_abc123def456"\ndef f(x):\n    return x + 1\n')
    save_session(
        session_id=result.session_id,
        source_file_path="seed.py",
        context_window=3,
        encrypted_mapping=result.encrypted_mapping,
        encryption_key=result.encryption_key,
        statistics=result.statistics,
    )
    return result.session_id


class TestBackup:
    def test_backs_up_every_file_under_the_app_dir(self, isolated_home, tmp_path):
        _seed_session(isolated_home)
        target = tmp_path / "out" / "archive"

        result = runner.invoke(app, ["backup", str(target)])
        assert result.exit_code == 0

        zip_path = target.with_suffix(".zip")
        assert zip_path.is_file()

        with zipfile.ZipFile(zip_path) as archive:
            names = set(archive.namelist())
        expected_on_disk = {
            str(p.relative_to(isolated_home)).replace("\\", "/")
            for p in isolated_home.rglob("*")
            if p.is_file()
        }
        archived_normalized = {n.replace("\\", "/") for n in names}
        assert expected_on_disk <= archived_normalized

    def test_appends_zip_suffix_when_missing(self, isolated_home, tmp_path):
        _seed_session(isolated_home)
        result = runner.invoke(app, ["backup", str(tmp_path / "plainname")])
        assert result.exit_code == 0
        assert (tmp_path / "plainname.zip").is_file()

    def test_refuses_to_write_the_backup_inside_the_app_dir(self, isolated_home):
        _seed_session(isolated_home)
        result = runner.invoke(app, ["backup", str(isolated_home / "self.zip")])
        assert result.exit_code != 0
        assert "itself" in result.output.lower()

    def test_warns_but_succeeds_on_an_empty_app_dir(self, isolated_home, tmp_path):
        # isolated_home is never created/seeded -- get_app_dir() creates it
        # empty the moment anything under commands/backup_cmd.py touches it.
        result = runner.invoke(app, ["backup", str(tmp_path / "empty")])
        assert result.exit_code == 0
        assert "empty" in result.output.lower()


class TestRestore:
    def test_round_trips_a_session_to_a_fresh_directory(self, isolated_home, tmp_path):
        session_id = _seed_session(isolated_home)
        backup_path = tmp_path / "backup.zip"
        assert runner.invoke(app, ["backup", str(backup_path)]).exit_code == 0

        fresh_home = tmp_path / "fresh"

        # Point at a brand-new, empty home for the restore half of the round trip.
        import os
        old_home = os.environ.get("CODEABSTRACT_HOME")
        os.environ["CODEABSTRACT_HOME"] = str(fresh_home)
        try:
            result = runner.invoke(app, ["restore", str(backup_path)])
            assert result.exit_code == 0

            show = runner.invoke(app, ["sessions", "show", session_id])
            assert show.exit_code == 0
            assert session_id[:8] in show.output
        finally:
            if old_home is not None:
                os.environ["CODEABSTRACT_HOME"] = old_home
            else:
                os.environ.pop("CODEABSTRACT_HOME", None)

    def test_rejects_a_missing_file(self, isolated_home, tmp_path):
        result = runner.invoke(app, ["restore", str(tmp_path / "nope.zip")])
        assert result.exit_code != 0

    def test_prompts_before_overwriting_existing_files(self, isolated_home, tmp_path):
        _seed_session(isolated_home)
        backup_path = tmp_path / "backup.zip"
        assert runner.invoke(app, ["backup", str(backup_path)]).exit_code == 0

        # Restoring on top of the same, now-populated directory should ask
        # first; declining must leave it untouched and exit cleanly.
        declined = runner.invoke(app, ["restore", str(backup_path)], input="n\n")
        assert declined.exit_code == 0
        assert "cancelled" in declined.output.lower()

    def test_force_skips_the_prompt(self, isolated_home, tmp_path):
        _seed_session(isolated_home)
        backup_path = tmp_path / "backup.zip"
        assert runner.invoke(app, ["backup", str(backup_path)]).exit_code == 0

        result = runner.invoke(app, ["restore", str(backup_path), "--force"])
        assert result.exit_code == 0
        assert "restored" in result.output.lower()

    def test_refuses_a_zip_slip_archive(self, isolated_home, tmp_path):
        """A crafted entry naming a path outside the target dir must not extract."""
        malicious = tmp_path / "evil.zip"
        with zipfile.ZipFile(malicious, "w") as archive:
            archive.writestr("../../evil.txt", "pwned")

        result = runner.invoke(app, ["restore", str(malicious), "--force"])
        assert result.exit_code != 0
        assert not (isolated_home.parent.parent / "evil.txt").exists()
