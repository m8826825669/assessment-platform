"""Reuse disposable integration fixtures in the separately invoked browser gate."""

import importlib.util
import sys
from pathlib import Path

integration = Path(__file__).resolve().parents[1] / "tests/integration"
sys.path.insert(0, str(integration))
spec = importlib.util.spec_from_file_location("browser_database_fixtures", integration / "conftest.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
test_database = fixtures.test_database
security_database = fixtures.security_database
from test_media_storage_live import live_media as live_media  # noqa: E402


def pytest_addoption(parser):
    parser.addoption("--require-postgres", action="store_true", default=True)
