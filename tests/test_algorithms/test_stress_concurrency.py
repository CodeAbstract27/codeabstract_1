"""
Priority 3 of the second adversarial round: stress and concurrency.

storage/database.py's connection-level contention safety is already covered
in tests/test_storage/test_database_concurrency.py (found two real defects
there previously -- DDL re-running under contention and a too-short busy
timeout). What's tested here instead is the layer above it: large-scale
token handling, and whether concurrent *sessions* (real secrets, real
per-session keys, going through the public save/load API) ever cross-
contaminate under real thread concurrency.
"""

import sqlite3
import threading
import time
import uuid

import pytest

from algorithms.abstract import abstract
from algorithms.encrypt import decrypt_mapping
from algorithms.reconstruct import reconstruct
from storage.session_manager import load_session, save_session


class TestLargeScaleTokenHandling:
    """VAR_1 .. VAR_9999+: the D2 collision class at real scale, not just
    the property test's bounded range."""

    def test_ten_thousand_identifiers_round_trip_without_corruption(self):
        n = 10_000
        source = "\n".join(f"var_{i} = {i}" for i in range(n))

        start = time.time()
        result = abstract(source, privacy_level="high")
        elapsed = time.time() - start

        # Generous ceiling: prior measurement after the O(n^2) context-
        # extraction fix was 5,300-7,800 LOC/sec; 10,000 single-statement
        # lines should not approach a full minute even on a slow CI box.
        # This is a regression tripwire for a reintroduced O(n^2)/O(n^3)
        # pass, not a tight performance benchmark.
        assert elapsed < 60, f"abstracting {n} identifiers took {elapsed:.1f}s"

        mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
        # Each line abstracts both the identifier and its numeric literal
        # at "high" (numbers are VALUE-classified by default), so there
        # are n VAR_ entries plus n NUM_ entries.
        var_names = {entry["name"] for entry in mapping.values() if entry["name"].startswith("var_")}
        assert len(var_names) == n

        # Reference tokens with ambiguous numeric prefixes in one response:
        # VAR_1 / VAR_10 / VAR_100 / VAR_1000, and their neighbours.
        probe_indices = [1, 10, 100, 1000, 9999, 9990, 19, 199]
        probe_indices = [i for i in probe_indices if i < n]
        response = " ".join(f"VAR_{i}" for i in probe_indices)

        translated = reconstruct(response, result.encrypted_mapping, result.encryption_key)

        for i in probe_indices:
            expected = f"var_{i}"
            idx = translated.find(expected)
            assert idx != -1, f"var_{i} missing from translated output"
            end = idx + len(expected)
            assert end >= len(translated) or not translated[end].isdigit(), (
                f"var_{i} corrupted by a numerically-adjacent token: "
                f"{translated[idx:end+4]!r}"
            )


class TestConcurrentSessionIsolation:
    """
    Real threads, real secrets, real per-session Fernet keys, going through
    the same save_session/load_session API the CLI and web layer use.
    The property being tested: thread A's secret must never be readable
    through thread B's session, and vice versa, regardless of scheduling.
    """

    def test_many_concurrent_sessions_never_cross_contaminate(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CODEABSTRACT_HOME", str(tmp_path))

        n_threads = 16
        results = {}
        errors = []
        lock = threading.Lock()

        def worker(index):
            try:
                secret = f"sk_live_UNIQUE_CANARY_{index:04d}_{'x' * 10}"
                source = f'api_key_{index} = "{secret}"\ndef handler_{index}():\n    return api_key_{index}\n'
                result = abstract(source, privacy_level="high")
                session_id = str(uuid.uuid4())
                save_session(
                    session_id=session_id,
                    source_file_path=f"file_{index}.py",
                    context_window=3,
                    encrypted_mapping=result.encrypted_mapping,
                    encryption_key=result.encryption_key,
                    statistics=result.statistics,
                )
                with lock:
                    results[index] = (session_id, secret)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append((index, exc))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # SQLite's single-writer model can reject a concurrent write with
        # "database is locked" under sustained contention -- a documented,
        # already-known residual limitation (see the module docstring of
        # tests/test_storage/test_database_concurrency.py: "not 'never
        # contends' -- 'when it does contend, nothing is corrupted and the
        # error is the expected, safe one'"). That is a rejected write, not
        # a security violation, so it does not fail this test on its own;
        # any *other* exception shape does, since it would suggest the
        # write partially happened or corrupted something.
        unexpected = [
            (index, exc) for index, exc in errors
            if not (isinstance(exc, sqlite3.OperationalError) and "locked" in str(exc).lower())
        ]
        assert not unexpected, f"worker(s) failed with an unexpected error: {unexpected}"
        if errors:
            assert len(results) + len(errors) == n_threads

        # Reload every session from a clean read and verify: (a) its own
        # secret is present in its own decrypted mapping, and (b) no other
        # thread's secret is anywhere in it. This is the property that
        # actually matters here -- it must hold for every session that DID
        # get saved, lock contention on some of them notwithstanding.
        all_secrets = {secret for _, secret in results.values()}
        for index, (session_id, own_secret) in results.items():
            session = load_session(session_id)
            mapping = decrypt_mapping(session["encrypted_mapping"], session["encryption_key"])
            names = {entry["name"] for entry in mapping.values()}

            assert own_secret in names, f"session {index} lost its own secret"
            for other_secret in all_secrets - {own_secret}:
                assert other_secret not in names, (
                    f"session {index} contains another thread's secret: {other_secret!r}"
                )

    def test_concurrent_abstraction_of_the_same_source_is_independent(self):
        """
        Many threads abstracting *identical* source concurrently must each
        get their own consistent, internally-correct mapping -- shared
        module-level state (a cache, a counter) racing here would show up
        as a token pointing at the wrong name within a single thread's own
        result.
        """
        source = "\n".join(f"local_var_{i} = {i}" for i in range(50))
        outcomes = []
        errors = []
        lock = threading.Lock()

        def worker():
            try:
                result = abstract(source, privacy_level="high")
                mapping = decrypt_mapping(result.encrypted_mapping, result.encryption_key)
                with lock:
                    outcomes.append(mapping)
            except Exception as exc:  # noqa: BLE001
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"worker(s) failed: {errors}"
        assert len(outcomes) == 12

        for mapping in outcomes:
            names = {entry["name"] for entry in mapping.values()}
            for i in range(50):
                assert f"local_var_{i}" in names, (
                    "a concurrent run produced an internally-inconsistent mapping"
                )
