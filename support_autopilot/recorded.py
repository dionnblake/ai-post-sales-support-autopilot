"""Record one live-model run over the demo tickets, then replay it with no key, network, or charge.

The hosted demo replays the committed recording so visitors see real model output. Replay is exact:
a ticket missing from the recording, or a draft made from different knowledge-base evidence, fails
safely as an ERROR instead of falling back to another provider.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from .engine import ROOT, Autopilot, digest
from .providers import ProviderError
from .seed import seed_demo

RECORDING = Path(__file__).with_name("recorded_run.json")


def ticket_key(subject, body):
    return digest({"subject": subject, "body": body})


def evidence_key(evidence):
    return digest(evidence)


class RecordingProvider:
    """Passes calls to a real provider and keeps what it returned."""

    def __init__(self, inner):
        self.inner, self.mode, self.entries = inner, inner.mode, {}

    def triage(self, subject, body):
        result = self.inner.triage(subject, body)
        self.entries.setdefault(ticket_key(subject, body), {})["triage"] = result
        return result

    def draft(self, subject, body, evidence):
        result = self.inner.draft(subject, body, evidence)
        self.entries.setdefault(ticket_key(subject, body), {})["draft"] = {
            "result": result, "evidence": evidence_key(evidence)}
        return result

    def save(self, path, *, model, recorded_at):
        # Written beside the target, then swapped in, so a failure never leaves a half-written recording.
        path = Path(path)
        data = {"model": model, "recorded_at": recorded_at, "entries": self.entries}
        temporary = path.with_name(path.name + ".tmp")
        temporary.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(temporary, path)


class RecordedProvider:
    """Replays a recording; never calls a model."""

    def __init__(self, path=None):
        try:
            data = json.loads(Path(path or RECORDING).read_text(encoding="utf-8"))
            self.model, self.recorded_at = str(data["model"]), str(data["recorded_at"])
            self.entries = dict(data["entries"])
        except (OSError, ValueError, KeyError, TypeError):
            raise ProviderError("Recorded model run is missing or unreadable") from None
        self.mode = f"recorded:{self.model}:{self.recorded_at}"

    def _entry(self, subject, body, part):
        entry = self.entries.get(ticket_key(subject, body))
        if not isinstance(entry, dict) or part not in entry:
            raise ProviderError("This ticket is not in the recorded model run")
        return entry[part]

    def triage(self, subject, body):
        return json.loads(json.dumps(self._entry(subject, body, "triage")))

    def draft(self, subject, body, evidence):
        recorded = self._entry(subject, body, "draft")
        if not isinstance(recorded, dict) or not isinstance(recorded.get("result"), dict):
            raise ProviderError("Recorded draft is malformed")
        if recorded.get("evidence") != evidence_key(evidence):
            raise ProviderError("Recorded draft was made from different knowledge-base evidence")
        return json.loads(json.dumps(recorded["result"]))


def record_live_run(*, now=None, provider=None):
    """Process the demo tickets once with the configured live model and save the recording.

    A run with any failed ticket is rejected and the previous recording is kept.
    """
    if provider is None:
        from .config import live_provider
        provider = live_provider()
    now = now or datetime.now(timezone.utc)
    recorder = RecordingProvider(provider)
    engine = Autopilot(ROOT / "work" / "recordings" / uuid.uuid4().hex / "support.sqlite3", ROOT / "kb",
                       provider=recorder)
    seed_demo(engine, now=now)
    for ticket in engine.tickets():
        engine.process(ticket["id"], now=now)
    statuses = {}
    for ticket in engine.tickets():
        statuses[ticket["status"]] = statuses.get(ticket["status"], 0) + 1
    if statuses.get("ERROR"):
        raise ProviderError(f"{statuses['ERROR']} ticket(s) failed; the previous recording was kept")
    model = getattr(provider, "model", provider.mode)
    recorder.save(RECORDING, model=model, recorded_at=now.date().isoformat())
    return {"model": model, "tickets": len(engine.tickets()), "statuses": statuses, "external_sends": 0}
