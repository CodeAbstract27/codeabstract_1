import os
import tempfile
from pathlib import Path
import pytest

from config.settings import load_dotenv

def test_load_dotenv(monkeypatch):
    # Setup temporary directory and mock cwd
    with tempfile.TemporaryDirectory() as tmpdir:
        dotenv_path = Path(tmpdir) / ".env"
        dotenv_path.write_text(
            "# A comment line\n"
            "TEST_ENV_KEY_1=value1\n"
            "TEST_ENV_KEY_2='value2'\n"
            "TEST_ENV_KEY_3=\"value3\"\n",
            encoding="utf-8"
        )
        
        # Clear target env vars if they exist
        for k in ["TEST_ENV_KEY_1", "TEST_ENV_KEY_2", "TEST_ENV_KEY_3"]:
            monkeypatch.delenv(k, raising=False)
            
        # Mock Path.cwd() to return our temp dir
        monkeypatch.setattr(Path, "cwd", lambda: Path(tmpdir))
        
        # Run loading
        load_dotenv()
        
        # Assertions
        assert os.environ.get("TEST_ENV_KEY_1") == "value1"
        assert os.environ.get("TEST_ENV_KEY_2") == "value2"
        assert os.environ.get("TEST_ENV_KEY_3") == "value3"
