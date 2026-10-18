"""SQLite workflow with an atomic human-approval / simulated-outbox boundary."""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .knowledge import KnowledgeBase, KnowledgeError
from .providers import (DemoProvider, ProviderError, QUEUES, SLA_HOURS, requires_security_review,
                        validate_draft, validate_triage)

ROOT = Path(__file__).resolve().parents[1]


class WorkflowError(ValueError):
    """A workflow transition was rejected without sending a reply."""


def timestamp(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise WorkflowError("An explicit timezone-aware timestamp is required")
    return value.astimezone(timezone.utc).isoformat()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def checked_text(value, label, limit):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or "\x00" in value:
        raise WorkflowError(f"{label} is required and must be at most {limit} characters")
    return value.strip()


class Autopilot:
    def __init__(self, db_path, kb_dir, provider=None):
        self.db_path, self.kb_dir = Path(db_path).resolve(), Path(kb_dir).resolve()
        if not self.db_path.is_relative_to(ROOT):
            raise WorkflowError("Demo data must stay within the project root")
        self.provider = provider or DemoProvider()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
                raise WorkflowError("Unsupported existing database version; no automatic migration")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY, external_id TEXT NOT NULL UNIQUE,
                    subject TEXT NOT NULL, body TEXT NOT NULL, created_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'NEW', queue TEXT NOT NULL DEFAULT 'Unassigned',
                    triage_json TEXT, draft_json TEXT, draft_hash TEXT,
                    processed_at TEXT, resolved_at TEXT, due_at TEXT,
                    mode TEXT, reason TEXT, sla_breached INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL REFERENCES tickets(id),
                    kind TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS outbox (
                    id INTEGER PRIMARY KEY, ticket_id INTEGER NOT NULL UNIQUE REFERENCES tickets(id),
                    body TEXT NOT NULL, draft_hash TEXT NOT NULL, reviewer TEXT NOT NULL,
                    at TEXT NOT NULL, transport TEXT NOT NULL CHECK(transport = 'SIMULATED')
                );
                PRAGMA user_version = 1;
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.db_path, timeout=45)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def event(conn, ticket_id, kind, actor, at, detail=""):
        conn.execute("INSERT INTO events(ticket_id,kind,actor,at,detail) VALUES(?,?,?,?,?)",
                     (ticket_id, kind, actor, at, detail))

    @staticmethod
    def unpack(row):
        if row is None:
            raise WorkflowError("Ticket not found")
        result = dict(row)
        for field in ("triage", "draft"):
            result[field] = json.loads(result.pop(field + "_json") or "null")
        return result

    def intake(self, external_id, subject, body, *, created_at):
        external_id = checked_text(external_id, "External ID", 100)
        subject, body = checked_text(subject, "Subject", 200), checked_text(body, "Body", 6000)
        created = timestamp(created_at)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            prior = conn.execute("SELECT * FROM tickets WHERE external_id=?", (external_id,)).fetchone()
            if prior:
                if (prior["subject"], prior["body"], prior["created_at"]) != (subject, body, created):
                    raise WorkflowError("External ID already exists with different ticket content")
                return prior["id"]
            due = timestamp(created_at + timedelta(hours=24))
            ticket_id = conn.execute("INSERT INTO tickets(external_id,subject,body,created_at,due_at) VALUES(?,?,?,?,?)",
                                     (external_id, subject, body, created, due)).lastrowid
            self.event(conn, ticket_id, "INGESTED", "seed/operator", created, "Synthetic demo intake")
            return ticket_id

    def get_ticket(self, ticket_id):
        with self.connection() as conn:
            return self.unpack(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())

    def tickets(self):
        with self.connection() as conn:
            return [self.unpack(row) for row in conn.execute("SELECT * FROM tickets ORDER BY id")]

    def events(self, ticket_id):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM events WHERE ticket_id=? ORDER BY id", (ticket_id,))]

    def outbox(self):
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("SELECT * FROM outbox ORDER BY id")]

    def process(self, ticket_id, *, now):
        at = timestamp(now)
        # One local operator, bounded requests. The transaction serializes process/review races.
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ticket = self.unpack(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())
            if ticket["status"] not in {"NEW", "ERROR"} and not (
                    ticket["status"] == "ESCALATED" and not ticket["processed_at"]):
                return ticket
            if ticket["created_at"] > at:
                raise WorkflowError("Cannot process a ticket before its creation time")
            triage, draft, reason = None, None, None
            due_at = ticket["due_at"]
            try:
                unsafe = requires_security_review(ticket["subject"] + " " + ticket["body"])
                triage = ({"category": "security", "urgency": "critical", "sentiment": "negative"}
                          if unsafe else validate_triage(self.provider.triage(ticket["subject"], ticket["body"])))
                queue = QUEUES[triage["category"]]
                due_at = timestamp(datetime.fromisoformat(ticket["created_at"]) +
                                   timedelta(hours=SLA_HOURS[triage["urgency"]]))
                if triage["category"] == "security":
                    status, reason = "ESCALATED", "Security or untrusted-instruction review required"
                else:
                    kb = KnowledgeBase(self.kb_dir)
                    evidence = kb.search(ticket["subject"] + " " + ticket["body"])
                    if not evidence:
                        status, queue, reason = "ESCALATED", "Specialist", "Insufficient knowledge-base evidence"
                    else:
                        generated = validate_draft(self.provider.draft(ticket["subject"], ticket["body"], evidence), evidence)
                        draft = dict(generated, evidence=[item for item in evidence if item["id"] in generated["citations"]],
                                     kb_hash=kb.digest)
                        status = "NEEDS_REVIEW"
            except (ProviderError, KnowledgeError, OSError) as error:
                status, queue, reason = "ERROR", "Specialist", type(error).__name__ + ": workflow failed safely"
                draft = None
            if ticket["sla_breached"] and status == "NEEDS_REVIEW":
                status, reason = "ESCALATED", "Resolution SLA breached; human review required"
            draft_hash = digest({"ticket_id": ticket_id, "draft": draft}) if draft else None
            conn.execute("""UPDATE tickets SET status=?,queue=?,triage_json=?,draft_json=?,draft_hash=?,
                processed_at=?,due_at=?,mode=?,reason=? WHERE id=?""",
                (status, queue, json.dumps(triage), json.dumps(draft), draft_hash, at, due_at,
                 self.provider.mode, reason, ticket_id))
            self.event(conn, ticket_id, "PROCESSED", self.provider.mode, at, reason or "Awaiting human review")
        return self.get_ticket(ticket_id)

    def approve(self, ticket_id, *, expected_hash, reviewer, now):
        reviewer, at = checked_text(reviewer, "Reviewer", 80), timestamp(now)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ticket = self.unpack(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())
            if ticket["status"] not in {"NEEDS_REVIEW", "ESCALATED"} or not ticket["draft"]:
                raise WorkflowError("Ticket has no approvable draft or is already resolved")
            if expected_hash != ticket["draft_hash"] or expected_hash != digest({"ticket_id": ticket_id, "draft": ticket["draft"]}):
                raise WorkflowError("The approval is stale; reload the current draft")
            if ticket["draft"]["kb_hash"] != KnowledgeBase(self.kb_dir).digest:
                raise WorkflowError("Knowledge changed; this approval is stale")
            if at < ticket["processed_at"]:
                raise WorkflowError("Review cannot predate draft generation")
            conn.execute("INSERT INTO outbox(ticket_id,body,draft_hash,reviewer,at,transport) VALUES(?,?,?,?,?,'SIMULATED')",
                         (ticket_id, ticket["draft"]["body"], expected_hash, reviewer, at))
            conn.execute("UPDATE tickets SET status='RESOLVED',resolved_at=? WHERE id=?", (at, ticket_id))
            self.event(conn, ticket_id, "APPROVED", reviewer, at, expected_hash)
            self.event(conn, ticket_id, "SIMULATED_SEND", reviewer, at, "Local outbox only; no external message")
        return self.get_ticket(ticket_id)

    def escalate(self, ticket_id, *, reviewer, now):
        reviewer, at = checked_text(reviewer, "Reviewer", 80), timestamp(now)
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ticket = self.unpack(conn.execute("SELECT * FROM tickets WHERE id=?", (ticket_id,)).fetchone())
            if ticket["status"] == "RESOLVED" or not ticket["processed_at"]:
                raise WorkflowError("Only unresolved processed tickets can be reviewed")
            if conn.execute("SELECT 1 FROM events WHERE ticket_id=? AND kind='REVIEW_ESCALATED'", (ticket_id,)).fetchone():
                raise WorkflowError("Ticket already escalated by a reviewer")
            # Rejection invalidates the draft, so it cannot later be approved accidentally.
            conn.execute("UPDATE tickets SET status='ESCALATED',queue='Specialist',reason='Escalated by reviewer',draft_json='null',draft_hash=NULL WHERE id=?", (ticket_id,))
            self.event(conn, ticket_id, "REVIEW_ESCALATED", reviewer, at, "No reply sent")

    def sweep_slas(self, *, now):
        at, changed = timestamp(now), 0
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for ticket in conn.execute("SELECT id FROM tickets WHERE status!='RESOLVED' AND due_at<=? AND sla_breached=0", (at,)).fetchall():
                conn.execute("UPDATE tickets SET status='ESCALATED',sla_breached=1,reason='Resolution SLA breached' WHERE id=?", (ticket["id"],))
                self.event(conn, ticket["id"], "SLA_BREACHED", "sla-sweep", at, "Original skill queue retained; specialist review required")
                changed += 1
        return changed

    def metrics(self, *, now):
        at = timestamp(now)
        tickets = self.tickets()
        processed = sum(ticket["processed_at"] is not None for ticket in tickets)
        resolutions = len(self.outbox())
        with self.connection() as conn:
            declined = conn.execute("SELECT COUNT(*) FROM events WHERE kind='REVIEW_ESCALATED'").fetchone()[0]
        reviewed = resolutions + declined
        return {"tickets": len(tickets), "processed": processed,
                "assisted_resolutions": resolutions,
                "assisted_resolution_rate": resolutions / processed if processed else 0,
                "reviewed": reviewed, "approval_rate": resolutions / reviewed if reviewed else 0,
                "open_sla_breaches": sum(ticket["status"] != "RESOLVED" and ticket["due_at"] is not None
                                         and ticket["due_at"] <= at for ticket in tickets),
                "estimated_minutes_saved": resolutions * 6}
