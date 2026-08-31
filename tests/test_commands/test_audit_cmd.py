"""
Tests for the `codeabstract audit` command group.

Previously untested end to end. Exercises the CLI surface directly
(`typer.testing.CliRunner`), isolated to a scratch ``CODEABSTRACT_HOME`` so
runs never touch — or read — the developer's real audit log.
"""

import csv
import io
import json

import pytest
from typer.testing import CliRunner

from cli import app
from storage import audit_log

runner = CliRunner()


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))
    return tmp_path


class TestAuditListAndShow:
    def test_list_on_empty_log_exits_zero(self, home):
        result = runner.invoke(app, ["audit", "list"])
        assert result.exit_code == 0
        assert "No audit entries" in result.output

    def test_list_shows_recorded_entries(self, home):
        audit_log.record_abstraction(
            session_id="s1", source_file="payments.py",
            privacy_level="high", statistics={},
        )
        result = runner.invoke(app, ["audit", "list"])
        assert result.exit_code == 0
        # Rich truncates the narrow "File" column on a narrow terminal
        # (CliRunner's default), so check the un-ellipsized prefix.
        assert "payments" in result.output

    def test_show_unknown_seq_exits_nonzero(self, home):
        result = runner.invoke(app, ["audit", "show", "999"])
        assert result.exit_code != 0

    def test_show_known_seq_prints_entry(self, home):
        audit_log.record_abstraction(
            session_id="s1", source_file="payments.py",
            privacy_level="high", statistics={},
        )
        result = runner.invoke(app, ["audit", "show", "1"])
        assert result.exit_code == 0
        assert "s1" in result.output


class TestAuditVerify:
    def test_verify_empty_log(self, home):
        result = runner.invoke(app, ["audit", "verify"])
        assert result.exit_code == 0

    def test_verify_intact_chain(self, home):
        audit_log.record_abstraction(
            session_id="s1", source_file="a.py", privacy_level="high",
            statistics={},
        )
        audit_log.record_abstraction(
            session_id="s2", source_file="b.py", privacy_level="high",
            statistics={},
        )
        result = runner.invoke(app, ["audit", "verify"])
        assert result.exit_code == 0
        assert "intact" in result.output.lower()

    def test_verify_detects_tampering(self, home):
        audit_log.record_abstraction(
            session_id="s1", source_file="a.py", privacy_level="high",
            statistics={},
        )
        audit_log.record_abstraction(
            session_id="s2", source_file="b.py", privacy_level="high",
            statistics={},
        )
        log_path = audit_log.audit_log_path()
        lines = log_path.read_text(encoding="utf-8").splitlines()
        entry = json.loads(lines[0])
        entry["source_file"] = "tampered.py"
        lines[0] = json.dumps(entry)
        log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        result = runner.invoke(app, ["audit", "verify"])
        assert result.exit_code != 0


class TestAuditExport:
    def test_export_empty_log_fails(self, home, tmp_path):
        out = tmp_path / "out.json"
        result = runner.invoke(app, ["audit", "export", "-o", str(out)])
        assert result.exit_code != 0

    def test_export_json_round_trips(self, home, tmp_path):
        audit_log.record_abstraction(
            session_id="s1", source_file="a.py", privacy_level="high",
            statistics={},
        )
        out = tmp_path / "out.json"
        result = runner.invoke(app, ["audit", "export", "-o", str(out)])
        assert result.exit_code == 0
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data[0]["session_id"] == "s1"

    def test_export_csv_is_valid_when_field_contains_a_quote(self, home, tmp_path):
        """
        Regression: a source path containing a double-quote character
        used to be wrapped in quotes without doubling the embedded quote,
        producing malformed CSV that silently corrupted every field after
        it once re-parsed.
        """
        audit_log.record_abstraction(
            session_id="s1", source_file='my"file.py', privacy_level="high",
            statistics={},
        )
        out = tmp_path / "out.csv"
        result = runner.invoke(app, ["audit", "export", "-o", str(out), "--format", "csv"])
        assert result.exit_code == 0

        rows = list(csv.reader(io.StringIO(out.read_text(encoding="utf-8"))))
        header, row = rows[0], rows[1]
        assert row[header.index("source_file")] == 'my"file.py'

    def test_export_csv_field_with_comma_and_newline(self, home, tmp_path):
        audit_log.append_entry(
            "abstract", session_id="s1",
            source_file="a,b\nc.py", privacy_level="high",
        )
        out = tmp_path / "out.csv"
        result = runner.invoke(app, ["audit", "export", "-o", str(out), "--format", "csv"])
        assert result.exit_code == 0

        rows = list(csv.reader(io.StringIO(out.read_text(encoding="utf-8"))))
        header, row = rows[0], rows[1]
        assert row[header.index("source_file")] == "a,b\nc.py"

    def test_home_isolation_does_not_see_other_dir(self, tmp_path, monkeypatch):
        """Sanity check on the fixture itself: two homes, two logs."""
        home_a = tmp_path / "a"
        home_b = tmp_path / "b"
        monkeypatch.setenv("CODEABSTRACT_HOME", str(home_a))
        audit_log.record_abstraction(
            session_id="only-in-a", source_file="a.py",
            privacy_level="high", statistics={},
        )
        monkeypatch.setenv("CODEABSTRACT_HOME", str(home_b))
        result = runner.invoke(app, ["audit", "list"])
        assert "only-in-a" not in result.output
