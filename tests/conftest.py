"""
Test isolation.

Phase 4. The test suite exercises commands that write to the application
data directory: sessions land in ``sessions.db``, requests land in the
audit log, and — since keys moved out of the database — every abstraction
writes a key to the OS credential store.

Left alone, a full run would file a few hundred credentials in the
developer's Windows Credential Manager or macOS Keychain and never remove
them, and would interleave test rows into the audit log that a compliance
reviewer would later have to explain. So the whole directory is redirected
to a temporary one, and keys are forced to the file backend.

The environment is set at import time rather than in a fixture: pytest
imports ``conftest.py`` before the test modules, and some of those read the
configuration during import.
"""

import os
import tempfile
from pathlib import Path

import pytest

# Redirect ~/.codeabstract for the whole session.
_TEST_HOME = Path(tempfile.mkdtemp(prefix="codeabstract-tests-"))
os.environ["CODEABSTRACT_HOME"] = str(_TEST_HOME)

# Never touch the real OS keychain from tests.
os.environ["CODEABSTRACT_KEY_BACKEND"] = "file"


@pytest.fixture(scope="session")
def test_home() -> Path:
    """The temporary application directory this run is using."""
    return _TEST_HOME


@pytest.fixture
def isolated_audit_log(tmp_path) -> Path:
    """A fresh audit log path, for tests that assert on its contents."""
    return tmp_path / "audit.log"
