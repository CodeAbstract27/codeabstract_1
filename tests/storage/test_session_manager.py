"""
Tests for storage/session_manager.py

All tests use the tmp_db fixture from conftest.py to isolate against an
in-memory SQLite database — the real CodeAbstract DB is never touched.

Covers:
- save_session / load_session roundtrip
- Prefix-based lookup
- Ambiguous prefix detection
- Non-existent session handling
- delete_session (exact + prefix)
- list_sessions ordering and limit
- get_session_count
- get_stats_summary aggregation
"""

import pytest
from algorithms.abstract import abstract
from storage.session_manager import (
    save_session,
    load_session,
    list_sessions,
    delete_session,
    get_session_count,
    get_stats_summary,
)
from tests.fixtures.sample_code import SAMPLE_PAYMENT_CODE, SAMPLE_SIMPLE_CODE


# ─── Helper ──────────────────────────────────────────────────

def _make_result(source=None, privacy_level="high"):
    """Run abstract() and return the AbstractionResult."""
    src = source or SAMPLE_PAYMENT_CODE
    return abstract(src, privacy_level=privacy_level)


def _save(result, file_path="test_file.py"):
    """Helper: save an AbstractionResult as a session."""
    save_session(
        session_id=result.session_id,
        source_file_path=file_path,
        context_window=3,
        encrypted_mapping=result.encrypted_mapping,
        encryption_key=result.encryption_key,
        statistics=result.statistics,
    )
    return result.session_id


# ═══════════════════════════════════════════════════════════
# save_session / load_session
# ═══════════════════════════════════════════════════════════

class TestSaveAndLoad:
    """Tests for saving and loading sessions."""

    def test_save_and_load_roundtrip(self, tmp_db):
        """Saving then loading by exact ID should return all fields."""
        result = _make_result()
        sid = _save(result)
        session = load_session(sid)

        assert session["session_id"] == sid
        assert session["source_file_path"] == "test_file.py"
        assert session["context_window"] == 3
        assert isinstance(session["encrypted_mapping"], bytes)
        assert isinstance(session["encryption_key"], bytes)
        assert isinstance(session["statistics"], dict)

    def test_load_by_prefix(self, tmp_db):
        """Load by first 8 characters of session ID should work."""
        result = _make_result()
        sid = _save(result)
        prefix = sid[:8]
        session = load_session(prefix)
        assert session["session_id"] == sid

    def test_load_nonexistent_raises_value_error(self, tmp_db):
        """Loading a session ID that doesn't exist should raise ValueError."""
        with pytest.raises(ValueError, match="No session found"):
            load_session("nonexistent-id-xyz")

    def test_load_ambiguous_prefix_raises_value_error(self, tmp_db):
        """Ambiguous prefix (matches >1 session) should raise ValueError."""
        # Save two sessions and manufacture an ambiguous prefix manually
        r1 = _make_result()
        r2 = _make_result(source=SAMPLE_SIMPLE_CODE)
        # Overwrite session IDs with known ambiguous prefix
        import uuid
        sid1 = "aaaa1111-0000-0000-0000-000000000001"
        sid2 = "aaaa2222-0000-0000-0000-000000000002"
        save_session(
            session_id=sid1, source_file_path="a.py", context_window=3,
            encrypted_mapping=r1.encrypted_mapping, encryption_key=r1.encryption_key,
            statistics=r1.statistics,
        )
        save_session(
            session_id=sid2, source_file_path="b.py", context_window=3,
            encrypted_mapping=r2.encrypted_mapping, encryption_key=r2.encryption_key,
            statistics=r2.statistics,
        )
        with pytest.raises(ValueError, match="Ambiguous prefix"):
            load_session("aaaa")  # matches both aaaa1111... and aaaa2222...

    def test_statistics_saved_and_restored(self, tmp_db):
        """Statistics dict should survive save → load intact."""
        result = _make_result()
        sid = _save(result)
        session = load_session(sid)
        stats = session["statistics"]
        assert "total_nodes" in stats
        assert "abstracted_nodes" in stats
        assert "secrets_found" in stats

    def test_save_without_statistics(self, tmp_db):
        """Saving without statistics arg should default to empty dict."""
        result = _make_result()
        save_session(
            session_id=result.session_id,
            source_file_path="test.py",
            context_window=3,
            encrypted_mapping=result.encrypted_mapping,
            encryption_key=result.encryption_key,
            # no statistics
        )
        session = load_session(result.session_id)
        assert session["statistics"] == {}

    def test_encrypted_mapping_bytes_roundtrip(self, tmp_db):
        """Encrypted mapping bytes must survive DB storage unchanged."""
        result = _make_result()
        sid = _save(result)
        session = load_session(sid)
        assert session["encrypted_mapping"] == result.encrypted_mapping
        assert session["encryption_key"] == result.encryption_key


# ═══════════════════════════════════════════════════════════
# delete_session
# ═══════════════════════════════════════════════════════════

class TestDeleteSession:
    """Tests for deleting sessions."""

    def test_delete_by_exact_id_returns_true(self, tmp_db):
        """Deleting by exact session ID should return True."""
        result = _make_result()
        sid = _save(result)
        deleted = delete_session(sid)
        assert deleted is True

    def test_delete_removes_session_from_db(self, tmp_db):
        """After deletion, loading the session should raise ValueError."""
        result = _make_result()
        sid = _save(result)
        delete_session(sid)
        with pytest.raises(ValueError, match="No session found"):
            load_session(sid)

    def test_delete_by_prefix(self, tmp_db):
        """Deleting by a unique prefix should work."""
        result = _make_result()
        sid = _save(result)
        prefix = sid[:8]
        deleted = delete_session(prefix)
        assert deleted is True

    def test_delete_nonexistent_returns_false(self, tmp_db):
        """Deleting a non-existent session should return False (not raise)."""
        result = delete_session("00000000-0000-0000-0000-000000000000")
        assert result is False

    def test_delete_ambiguous_prefix_raises(self, tmp_db):
        """Ambiguous delete prefix should raise ValueError."""
        r1 = _make_result()
        r2 = _make_result(source=SAMPLE_SIMPLE_CODE)
        sid1 = "bbbb1111-0000-0000-0000-000000000001"
        sid2 = "bbbb2222-0000-0000-0000-000000000002"
        save_session(
            session_id=sid1, source_file_path="a.py", context_window=3,
            encrypted_mapping=r1.encrypted_mapping, encryption_key=r1.encryption_key,
        )
        save_session(
            session_id=sid2, source_file_path="b.py", context_window=3,
            encrypted_mapping=r2.encrypted_mapping, encryption_key=r2.encryption_key,
        )
        with pytest.raises(ValueError, match="Ambiguous prefix"):
            delete_session("bbbb")


# ═══════════════════════════════════════════════════════════
# list_sessions
# ═══════════════════════════════════════════════════════════

class TestListSessions:
    """Tests for listing sessions."""

    def test_list_empty_db_returns_empty(self, tmp_db):
        """list_sessions on an empty DB should return an empty list."""
        sessions = list_sessions()
        assert sessions == []

    def test_list_returns_saved_sessions(self, tmp_db):
        """After saving sessions, list_sessions should include them."""
        r1 = _make_result()
        r2 = _make_result(source=SAMPLE_SIMPLE_CODE)
        _save(r1, "file1.py")
        _save(r2, "file2.py")
        sessions = list_sessions()
        assert len(sessions) == 2

    def test_list_respects_limit(self, tmp_db):
        """list_sessions(limit=1) should return only 1 session."""
        for _ in range(3):
            _save(_make_result())
        sessions = list_sessions(limit=1)
        assert len(sessions) == 1

    def test_list_sessions_have_required_keys(self, tmp_db):
        """Each session summary must include required fields."""
        _save(_make_result())
        sessions = list_sessions()
        s = sessions[0]
        assert "session_id" in s
        assert "source_file_path" in s
        assert "created_at" in s
        assert "statistics" in s


# ═══════════════════════════════════════════════════════════
# get_session_count
# ═══════════════════════════════════════════════════════════

class TestGetSessionCount:

    def test_count_zero_on_empty_db(self, tmp_db):
        assert get_session_count() == 0

    def test_count_increments_on_save(self, tmp_db):
        _save(_make_result())
        assert get_session_count() == 1
        _save(_make_result(source=SAMPLE_SIMPLE_CODE))
        assert get_session_count() == 2

    def test_count_decrements_on_delete(self, tmp_db):
        result = _make_result()
        sid = _save(result)
        assert get_session_count() == 1
        delete_session(sid)
        assert get_session_count() == 0


# ═══════════════════════════════════════════════════════════
# get_stats_summary
# ═══════════════════════════════════════════════════════════

class TestGetStatsSummary:

    def test_summary_has_required_keys(self, tmp_db):
        """Stats summary must include all documented keys."""
        _save(_make_result())
        summary = get_stats_summary()
        assert "total_sessions" in summary
        assert "total_secrets_found" in summary
        assert "total_values_found" in summary
        assert "total_abstractions" in summary
        assert "earliest_session" in summary
        assert "latest_session" in summary

    def test_summary_totals_sessions(self, tmp_db):
        """total_sessions must match number of saved sessions."""
        _save(_make_result())
        _save(_make_result(source=SAMPLE_SIMPLE_CODE))
        summary = get_stats_summary()
        assert summary["total_sessions"] == 2

    def test_summary_aggregates_secrets(self, tmp_db):
        """total_secrets_found must sum across all sessions."""
        result = _make_result()
        _save(result)
        summary = get_stats_summary()
        assert summary["total_secrets_found"] == result.statistics.get("secrets_found", 0)

    def test_summary_empty_db(self, tmp_db):
        """Stats on empty DB should return zero totals."""
        summary = get_stats_summary()
        assert summary["total_sessions"] == 0
        assert summary["total_secrets_found"] == 0
        assert summary["total_abstractions"] == 0
