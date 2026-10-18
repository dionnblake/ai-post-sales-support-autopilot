"""All runtime data is explicitly anchored to this project's root."""
import os
from pathlib import Path

from .engine import ROOT, Autopilot, WorkflowError
from .providers import LiveProvider


def make_engine(*, live=False):
    directory = Path(os.environ.get("SUPPORT_DATA_DIR", ROOT / "data")).resolve()
    if not directory.is_relative_to(ROOT):
        raise WorkflowError("SUPPORT_DATA_DIR must be inside this project")
    provider = None
    if live:
        provider = LiveProvider(key=os.environ.get("SUPPORT_LLM_API_KEY", ""),
            model=os.environ.get("SUPPORT_LLM_MODEL", ""),
            enabled=os.environ.get("SUPPORT_ENABLE_LIVE_LLM") == "1",
            base_url=os.environ.get("SUPPORT_LLM_BASE_URL", "https://api.openai.com/v1"))
    return Autopilot(directory / "support.sqlite3", ROOT / "kb", provider=provider)
