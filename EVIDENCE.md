# Verification scope

This covers a local portfolio demo, not a production certification.

**Test suite:** 43 passed on Python 3.13 / Streamlit 1.66.0, with no API key and no network calls.

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
- **Hosted first load:** an empty database is seeded and processed with no approval or outbox record; an interrupted first load is finished on the next visit; simultaneous first visitors with different clocks seed once and process each ticket once; non-demo data, reviews, and untouched NEW tickets are left alone; the hosted entrypoint lands on a 12-ticket queue with approval still locked; its on-page guide names controls and tickets that exist and behave as it describes; the local entrypoint does not auto-seed; and the shared config leaves the bind address to the host while the local launcher pins loopback.
- **Dashboard:** Streamlit AppTest clicks through seed, process, review, and approve, then checks that the metrics, queue columns, and deadline labels update correctly.

## Manual check

The dashboard was also run in a browser on localhost: 12 fictional tickets loaded and processed, the billing draft showed its cited excerpt, approval stayed disabled until the reviewer confirmed, and one approval updated the metrics. No console errors.

The hosted entrypoint (`streamlit_app.py`) was run on localhost with an empty data directory: the queue opened with 12 processed tickets and 0 resolutions, approval stayed disabled until the reviewer confirmed, one approval set the metrics to 1 / 100% / 6 min, and a reload kept that state without reseeding. No console errors.

## Review

A separate code review found two issues, both fixed with regression tests: malformed provider responses could escape the safe-failure path, and a drafting failure could reset a critical ticket's SLA to the default.

## Not verified

- Live LLM calls or real answer quality.
- ClickUp integration or real delivery.
- Approval on the live Community Cloud app. It was opened after deployment (12 processed tickets, 0 resolutions, guide visible), but nothing was approved there, to keep the shared demo clean; approval was exercised locally.
- Authenticated reviewers, multiple tenants, business-hours SLAs, or production reliability.
