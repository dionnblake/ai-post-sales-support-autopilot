"""A recorded live-model run can be replayed exactly, and a stale or missing recording fails safely."""
import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from conftest import NOW
from support_autopilot import recorded
from support_autopilot.config import make_engine
from support_autopilot.engine import Autopilot, WorkflowError
from support_autopilot.presentation import mode_label
from support_autopilot.providers import DemoProvider, ProviderError
from support_autopilot.recorded import RecordedProvider, RecordingProvider
from support_autopilot.seed import seed_demo

ROOT = Path(__file__).resolve().parents[1]


def processed(engine):
    seed_demo(engine, now=NOW)
    for ticket in engine.tickets():
        engine.process(ticket["id"], now=NOW)
    return {ticket["external_id"]: ticket for ticket in engine.tickets()}


def record(tmp_path):
    recorder = RecordingProvider(DemoProvider())
    original = processed(Autopilot(tmp_path / "record.sqlite3", ROOT / "kb", provider=recorder))
    path = tmp_path / "run.json"
    recorder.save(path, model="fake-model-1", recorded_at="2026-10-19")
    return original, path


def test_replay_reproduces_the_recorded_outcomes_without_a_model(tmp_path):
    original, path = record(tmp_path)
    replayed = processed(Autopilot(tmp_path / "replay.sqlite3", ROOT / "kb", provider=RecordedProvider(path)))
    for external_id, ticket in original.items():
        again = replayed[external_id]
        assert (again["status"], again["queue"], again["triage"], again["draft"]) == (
            ticket["status"], ticket["queue"], ticket["triage"], ticket["draft"])
    assert {ticket["mode"] for ticket in replayed.values()} == {"recorded:fake-model-1:2026-10-19"}


def test_a_ticket_missing_from_the_recording_fails_safely(tmp_path):
    _, path = record(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["entries"] = {}
    path.write_text(json.dumps(data), encoding="utf-8")
    replayed = processed(Autopilot(tmp_path / "replay.sqlite3", ROOT / "kb", provider=RecordedProvider(path)))
    assert replayed["SYN-1001"]["status"] == "ERROR"
    assert replayed["SYN-1001"]["draft"] is None


def test_a_draft_recorded_from_different_evidence_is_not_replayed(tmp_path):
    _, path = record(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data["entries"].values():
        if "draft" in entry:
            entry["draft"]["evidence"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    replayed = processed(Autopilot(tmp_path / "replay.sqlite3", ROOT / "kb", provider=RecordedProvider(path)))
    assert replayed["SYN-1001"]["status"] == "ERROR"
    assert replayed["SYN-1001"]["draft"] is None


def test_an_unreadable_recording_is_a_provider_error(tmp_path):
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ProviderError):
        RecordedProvider(path)


def test_mode_labels_say_who_drafted_the_reply():
    assert "keyword rules" in mode_label("demo")
    assert "live" in mode_label("live")
    label = mode_label("recorded:gemini-3.8-flash:2026-10-19")
    assert "gemini-3.8-flash" in label and "2026-10-19" in label and "recorded" in label


def test_record_command_refuses_without_live_enablement(tmp_path, monkeypatch):
    monkeypatch.setattr(recorded, "RECORDING", tmp_path / "never.json")
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "data"))
    for name in ("SUPPORT_ENABLE_LIVE_LLM", "SUPPORT_LLM_API_KEY", "SUPPORT_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderError):
        recorded.record_live_run()
    assert not (tmp_path / "never.json").exists()


def test_hosted_demo_replays_the_committed_real_model_run(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "hosted"))
    monkeypatch.setenv("SUPPORT_AUTO_SEED_DEMO", "0")
    run = json.loads(recorded.RECORDING.read_text(encoding="utf-8"))
    at = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=20).run()
    assert not at.exception
    assert any(run["model"] in caption.value and "recorded" in caption.value for caption in at.caption)


def test_hosted_engine_refuses_a_missing_recording_instead_of_falling_back(tmp_path, monkeypatch):
    monkeypatch.setattr(recorded, "RECORDING", tmp_path / "missing.json")
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "data"))
    with pytest.raises(WorkflowError):
        make_engine(recorded=True)


@pytest.mark.parametrize("damage", [
    lambda entry: entry.update(draft=None),
    lambda entry: entry["draft"].pop("result"),
    lambda entry: entry.update(triage="billing"),
])
def test_a_malformed_recording_entry_fails_safely(tmp_path, damage):
    _, path = record(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    for entry in data["entries"].values():
        if "draft" in entry:
            damage(entry)
    path.write_text(json.dumps(data), encoding="utf-8")
    replayed = processed(Autopilot(tmp_path / "replay.sqlite3", ROOT / "kb", provider=RecordedProvider(path)))
    assert replayed["SYN-1001"]["status"] == "ERROR"
    assert replayed["SYN-1001"]["draft"] is None


class FlakyProvider(DemoProvider):
    model = "flaky-model"

    def draft(self, subject, body, evidence):
        if "invoice" in subject.lower():
            raise ProviderError("simulated outage")
        return super().draft(subject, body, evidence)


def test_a_failed_recording_run_keeps_the_previous_recording(tmp_path, monkeypatch):
    previous = tmp_path / "run.json"
    previous.write_text('{"previous": true}', encoding="utf-8")
    monkeypatch.setattr(recorded, "RECORDING", previous)
    with pytest.raises(ProviderError):
        recorded.record_live_run(now=NOW, provider=FlakyProvider())
    assert previous.read_text(encoding="utf-8") == '{"previous": true}'


def test_a_complete_recording_run_replaces_the_file(tmp_path, monkeypatch):
    target = tmp_path / "run.json"
    target.write_text('{"previous": true}', encoding="utf-8")
    monkeypatch.setattr(recorded, "RECORDING", target)
    summary = recorded.record_live_run(now=NOW, provider=DemoProvider())
    assert summary["external_sends"] == 0
    assert RecordedProvider(target).model == "demo"
    assert not list(tmp_path.glob("*.tmp"))
