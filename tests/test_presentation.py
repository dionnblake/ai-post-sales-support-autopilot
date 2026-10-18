from datetime import timedelta

from conftest import NOW
from support_autopilot.presentation import deadline_label, format_utc


def test_format_utc_is_readable_and_minute_precise():
    assert format_utc("2026-10-18T19:22:56.055388+00:00") == "2026-10-18 19:22 UTC"
    assert format_utc(None) == "—"


def test_deadline_label_counts_down_and_marks_overdue_inclusively():
    assert deadline_label((NOW + timedelta(hours=23, minutes=59)).isoformat(), NOW, "NEEDS_REVIEW") == "Due in 23h 59m"
    assert deadline_label((NOW + timedelta(minutes=5)).isoformat(), NOW, "NEW") == "Due in 5m"
    # The engine treats due_at == now as breached; the label must agree.
    assert deadline_label(NOW.isoformat(), NOW, "NEEDS_REVIEW") == "Overdue 0m"
    assert deadline_label((NOW - timedelta(hours=26, minutes=3)).isoformat(), NOW, "ESCALATED") == "Overdue 26h 03m"


def test_deadline_label_for_resolved_or_missing_deadline():
    assert deadline_label((NOW - timedelta(hours=5)).isoformat(), NOW, "RESOLVED") == "Resolved"
    assert deadline_label(None, NOW, "NEW") == "—"
