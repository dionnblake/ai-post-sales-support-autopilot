from pathlib import Path

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


def test_reviewer_can_seed_process_and_approve_without_a_key(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "app-data"))
    monkeypatch.delenv("SUPPORT_LLM_API_KEY", raising=False)
    at = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    assert not at.exception
    at.button(key="seed").click().run()
    assert not at.exception
    assert len(at.metric) == 4
    at.button(key="process").click().run()
    assert not at.exception
    assert at.button(key="approve").disabled
    at.checkbox(key="review_confirm").check().run()
    at.button(key="approve").click().run()
    assert not at.exception
    assert at.metric[0].value == "1"


def test_queue_shows_full_triage_and_readable_deadlines(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "app-data"))
    at = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    at.button(key="seed").click().run()
    at.button(key="process").click().run()
    assert not at.exception
    queue = at.dataframe[0].value
    assert {"Category", "Urgency", "Sentiment", "SLA"} <= set(queue.columns)
    assert queue.loc[queue["Ticket"] == "SYN-1001", "Category"].item() == "billing"
    assert all(label.startswith(("Due in", "Overdue", "Resolved")) for label in queue["SLA"])
    # Triage is shown as labelled fields, not a raw JSON dump.
    assert len(at.json) == 0
    assert any("billing" in caption.value and "neutral" in caption.value for caption in at.caption)


def test_empty_app_displays_truthful_zero_metrics(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "empty"))
    at = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    assert not at.exception
    assert [metric.value for metric in at.metric] == ["0", "0%", "0", "0 min"]
