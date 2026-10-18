# Verification scope

This covers a local portfolio demo, not a production certification.

**Test suite:** 33 passed on Python 3.13 / Streamlit 1.66.0, with no API key and no network calls.

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## What the tests cover

- **Workflow and storage:** real SQLite transactions for intake, processing, approval, escalation, and the simulated outbox. Intake is idempotent, and reusing a ticket ID with different content is rejected.
- **Human approval boundary:** approval requires the exact current draft hash. Stale drafts, a changed knowledge base, duplicate approvals, and two concurrent approvals are all covered; the concurrent case produces exactly one outbox record.
- **Grounding:** retrieval finds the right KB section, unsupported questions escalate with no draft, and drafts citing unknown sources are rejected.
- **Safety routing:** security reports and prompt-injection text go to the Security queue without a draft.
- **SLA:** deadline boundaries are inclusive (a ticket due exactly now counts as breached), unprocessed tickets get a default deadline, and a drafting failure keeps the urgency-based deadline.
- **LLM adapter contract:** a fake transport checks the JSON request shape and that malformed envelopes, invalid classifications, truncated responses, and bad citations all fail safely. These are contract tests, not a live-provider test.
- **Dashboard:** Streamlit AppTest clicks through seed, process, review, and approve, then checks that the metrics, queue columns, and deadline labels update correctly.

## Manual check

The dashboard was also run in a browser on localhost: 12 fictional tickets loaded and processed, the billing draft showed its cited excerpt, approval stayed disabled until the reviewer confirmed, and one approval updated the metrics. No console errors.

## Review

A separate code review found two issues, both fixed with regression tests: malformed provider responses could escape the safe-failure path, and a drafting failure could reset a critical ticket's SLA to the default.

## Not verified

- Live LLM calls or real answer quality.
- ClickUp integration, real delivery, deployment, or hosted CI.
- Authenticated reviewers, multiple tenants, business-hours SLAs, or production reliability.
