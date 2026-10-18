"""Display helpers for the dashboard. Pure functions; no workflow state."""
from datetime import datetime


def format_utc(value):
    if not value:
        return "—"
    return datetime.fromisoformat(value).strftime("%Y-%m-%d %H:%M UTC")


def _span(delta):
    minutes = int(delta.total_seconds() // 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m" if hours else f"{minutes}m"


def deadline_label(due_at, now, status):
    """Matches the engine: a deadline at or before now is breached."""
    if status == "RESOLVED":
        return "Resolved"
    if not due_at:
        return "—"
    due = datetime.fromisoformat(due_at)
    return f"Overdue {_span(now - due)}" if due <= now else f"Due in {_span(due - now)}"
