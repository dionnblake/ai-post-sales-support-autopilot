"""All runtime data is explicitly anchored to this project's root."""
import os
import re
from pathlib import Path

from . import recorded as recording
from .engine import ROOT, Autopilot, WorkflowError
from .providers import LiveProvider, ProviderError


def make_engine(*, live=False, sandbox=None, recorded=False):
    directory = Path(os.environ.get("SUPPORT_DATA_DIR", ROOT / "data")).resolve()
    if not directory.is_relative_to(ROOT):
        raise WorkflowError("SUPPORT_DATA_DIR must be inside this project")
    if sandbox is not None:
        # Hosted visitors each get a private database, named by a server-generated token.
        if not isinstance(sandbox, str) or not re.fullmatch(r"[0-9a-f]{32}", sandbox):
            raise WorkflowError("Invalid demo sandbox name")
        directory = directory / "sessions" / sandbox
    provider = None
    if live:
        provider = live_provider()
    elif recorded:
        # The hosted demo replays the recorded model run; a missing recording stops the app, never a fallback.
        try:
            provider = recording.RecordedProvider(recording.RECORDING)
        except ProviderError as error:
            raise WorkflowError(str(error)) from None
    return Autopilot(directory / "support.sqlite3", ROOT / "kb", provider=provider)


def live_provider():
    return LiveProvider(key=os.environ.get("SUPPORT_LLM_API_KEY", ""),
        model=os.environ.get("SUPPORT_LLM_MODEL", ""),
        enabled=os.environ.get("SUPPORT_ENABLE_LIVE_LLM") == "1",
        base_url=os.environ.get("SUPPORT_LLM_BASE_URL", "https://api.openai.com/v1"))
