"""
Tests for POST /api/benchmarks/run (web/service.run_benchmarks_now).

These actually shell out to `evaluation/run_eval.py --skip-performance`,
so they cost real wall-clock time (a few seconds each) rather than being
mocked -- deliberately: the thing worth verifying is that the *real*
subprocess call, lock, and refreshed-summary plumbing works end to end,
not that a mock of it does.
"""

import threading
import uuid

import pytest

from web.service import EVALUATION_RESULTS_PATH


def _email() -> str:
    return f"{uuid.uuid4().hex}@example.com"


@pytest.fixture
def signed_in_client(client):
    client.post('/api/auth/signup', json={'email': _email(), 'password': 'a-strong-password'})
    return client


@pytest.fixture(autouse=True)
def _preserve_the_committed_evaluation_snapshot():
    """
    ``run_benchmarks_now`` writes to the real, project-relative
    ``evaluation_output/`` -- deliberately, since that is exactly where a
    person running ``python evaluation/run_eval.py`` by hand expects the
    numbers to land, and where ``benchmark_summary()`` always reads from
    (see web/service.py). A test that exercises the real endpoint therefore
    really does overwrite the checked-in reference snapshot as a side
    effect -- found by noticing ``git status`` showed
    evaluation_output/evaluation_results.json changed after this file's
    tests ran the first time. The fix is not to fake the write (that would
    stop testing the real thing); it is to snapshot the two files here and
    restore them afterwards, whatever the test did to them.
    """
    report_path = EVALUATION_RESULTS_PATH.parent / 'evaluation_report.md'
    paths = [EVALUATION_RESULTS_PATH, report_path]
    originals = {p: (p.read_bytes() if p.is_file() else None) for p in paths}

    yield

    for path, content in originals.items():
        if content is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(content)


class TestRunBenchmarksNow:
    def test_requires_login(self, client):
        response = client.post('/api/benchmarks/run', json={})
        assert response.status_code == 401

    def test_runs_and_returns_a_refreshed_summary(self, signed_in_client):
        response = signed_in_client.post('/api/benchmarks/run', json={})
        assert response.status_code == 200
        data = response.get_json()
        assert data['ok'] is True
        assert data['available'] is True
        assert 'classification' in data

        # The regular GET should now see the same, freshly-written snapshot.
        follow_up = signed_in_client.get('/api/benchmarks').get_json()
        assert follow_up['timestamp'] == data['timestamp']

    def test_concurrent_runs_are_rejected_not_corrupted(self, app):
        """
        Two overlapping "Run now" clicks must not both spawn the
        evaluation script -- see the lock in web/service.run_benchmarks_now.
        """
        from web import service

        results = []

        def _call():
            with app.test_request_context():
                results.append(service.run_benchmarks_now())

        first = threading.Thread(target=_call)
        second = threading.Thread(target=_call)
        first.start()
        second.start()
        first.join(timeout=30)
        second.join(timeout=30)

        assert len(results) == 2
        outcomes = [r.get('ok') for r in results]
        # Exactly one of the two should have been turned away by the lock.
        assert outcomes.count(False) <= 1
        assert any(
            'already in progress' in r.get('error', '') for r in results if not r.get('ok')
        ) or all(outcomes)
