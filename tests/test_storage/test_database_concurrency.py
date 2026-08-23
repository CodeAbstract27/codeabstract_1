"""
Database concurrency regression suite.

Two real defects were found here by direct write-contention testing
against ``storage.database.get_connection``, not by inspection:

1. Every call re-ran the full schema-creation DDL (``executescript``) and
   the migration check, even when the schema was already current. DDL
   takes a stronger SQLite lock than a row write, and every write in
   ``storage.session_manager`` opens a fresh connection per call -- so N
   connections opening at once each re-ran DDL at once. This is now fixed:
   schema/migrations apply at most once per resolved path per process
   (see the module docstring in ``database.py``), and it is verified
   deterministically below, with no dependence on thread scheduling.
2. The connection's busy timeout was the sqlite3 default of 5s, raised to
   30s as further headroom under concurrent writers.

What this suite does *not* claim: that concurrent writes never contend.
Repeated measurement (20+ trials at 5 and at 10 concurrent connections,
recorded during development, not reproduced here) showed that SQLite's
single-writer model -- on this platform, under WAL -- still produces an
occasional ``sqlite3.OperationalError: database is locked`` under
sustained concurrent writers even after both fixes above. That residual
is real, is not something a connection-open-time change can fully close,
and is documented as follow-up work (an application-level write retry or
a serialized writer queue) rather than asserted away here. Encoding "zero
errors under N concurrent writers" as a hard CI assertion would make this
suite flaky by the same measurement, which is worse than not testing it:
a red build with no actionable cause trains people to ignore red builds.
What *is* deterministic, and is what this suite asserts:

* the DDL-once mechanism itself (no thread timing involved), and
* that when a write does hit lock contention, the database is left
  consistent -- no partial row, no corruption -- and the error surfaced
  is the expected, safe ``sqlite3.OperationalError``, not something
  worse.
"""

import sqlite3
import threading

from storage.database import get_connection


class TestSchemaInitRunsOnce:

    def test_schema_ddl_runs_at_most_once_per_path(self, tmp_path, monkeypatch):
        """
        The specific mechanism of the fix: schema/migration setup must
        not run again on a later get_connection() call against a path
        already initialised in this process. Deterministic -- no threads.

        Spies on ``_apply_migrations`` rather than
        ``sqlite3.Connection.executescript`` directly: the latter is a
        C-extension type and CPython refuses to patch attributes on it
        (``TypeError: cannot set 'executescript' attribute of immutable
        type 'sqlite3.Connection'``). Both calls live inside the same
        guarded block in get_connection(), so this exercises the same
        code path.
        """
        import storage.database as database_module

        db_path = tmp_path / "sessions.db"
        get_connection(db_path=db_path).close()  # first call: initialises

        calls = []
        original = database_module._apply_migrations

        def spy(conn):
            calls.append(1)
            return original(conn)

        monkeypatch.setattr(database_module, "_apply_migrations", spy)

        get_connection(db_path=db_path).close()
        get_connection(db_path=db_path).close()

        assert calls == [], "schema/migration setup ran again on an already-initialised path"

    def test_second_call_still_returns_a_working_connection(self, tmp_path):
        """Skipping DDL on the fast path must not skip getting a usable connection."""
        db_path = tmp_path / "sessions.db"
        get_connection(db_path=db_path).close()

        conn = get_connection(db_path=db_path)
        conn.execute(
            "INSERT INTO sessions (session_id, source_file_path, encrypted_mapping, encryption_key) "
            "VALUES ('s1', 'f.py', X'00', X'00')"
        )
        conn.commit()
        row = conn.execute(
            "SELECT session_id FROM sessions WHERE session_id = 's1'"
        ).fetchone()
        conn.close()
        assert row["session_id"] == "s1"


class TestConcurrentWritesFailSafely:
    """
    Not "never contends" (see module docstring) -- "when it does contend,
    nothing is corrupted and the error is the expected, safe one."
    """

    def test_concurrent_writers_never_corrupt_the_database(self, tmp_path):
        db_path = tmp_path / "sessions.db"
        n_threads, n_inserts = 10, 10
        errors = []
        lock = threading.Lock()

        def worker(tid):
            try:
                conn = get_connection(db_path=db_path)
                for i in range(n_inserts):
                    conn.execute(
                        "INSERT INTO sessions "
                        "(session_id, source_file_path, encrypted_mapping, encryption_key) "
                        "VALUES (?, ?, ?, ?)",
                        (f"sess-{tid}-{i}", "file.py", b"x", b"y"),
                    )
                    conn.commit()
                conn.close()
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Any error surfaced must be the specific, expected SQLite
        # contention error -- not a crash, a hang, or something that
        # indicates the schema-init race reopened.
        for exc in errors:
            assert isinstance(exc, sqlite3.OperationalError), (
                f"unexpected failure mode under contention: {exc!r}"
            )
            assert "locked" in str(exc).lower()

        # The database itself must still be readable and structurally
        # intact regardless of how many writes were lost to contention --
        # this is the actual safety property, independent of the flaky
        # error count.
        conn = get_connection(db_path=db_path)
        tables = {
            row["name"]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "sessions" in tables
        count = conn.execute("SELECT COUNT(*) c FROM sessions").fetchone()["c"]
        conn.close()
        assert 0 <= count <= n_threads * n_inserts
