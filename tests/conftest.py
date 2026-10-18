from datetime import datetime, timezone
from pathlib import Path
import tempfile
import uuid
import os

import pytest

from support_autopilot.engine import Autopilot

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 18, 16, 0, tzinfo=timezone.utc)


def pytest_configure(config):
    local_temp = ROOT / "work" / "tmp"
    local_temp.mkdir(parents=True, exist_ok=True)
    tempfile.tempdir = str(local_temp)
    os.environ["TEMP"] = str(local_temp)
    os.environ["TMP"] = str(local_temp)
    if not config.option.basetemp:
        runs = ROOT / "work" / "test-runs"
        runs.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = str(runs / uuid.uuid4().hex)


@pytest.fixture
def engine(tmp_path):
    return Autopilot(tmp_path / "demo.sqlite3", ROOT / "kb")


@pytest.fixture
def invoice(engine):
    return engine.intake("example-001", "Download invoice", "Where can I download our monthly invoice PDF?", created_at=NOW)
