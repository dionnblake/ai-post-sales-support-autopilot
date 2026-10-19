"""A single-operator, localhost dashboard. Every ticket and send is simulated."""
from datetime import datetime, timezone
import os

import streamlit as st

from support_autopilot.config import make_engine
from support_autopilot.engine import WorkflowError
from support_autopilot.knowledge import KnowledgeError
from support_autopilot.presentation import deadline_label, format_utc
from support_autopilot.providers import ProviderError
from support_autopilot.seed import prepare_demo, seed_demo

st.set_page_config(page_title="Support Autopilot", page_icon="↗", layout="wide")
st.markdown("""<style>
/* Hallmark: restrained operations dashboard; native Streamlit controls. */
:root { --ink: #0A0A0A; --surface: #141414; --raised: #1E1E1E; --accent: #F59E0B;
        --text: #F5F5F5; --muted: #AAAAAA; --display: 'Space Grotesk', 'Segoe UI', sans-serif;
        --mono: 'Space Mono', Consolas, monospace; }
html, body { overflow-x: clip; }
.stApp, .stApp p, .stApp label { font-family: var(--display); }
h1,h2,h3 { font-family: var(--display) !important; font-style: normal; overflow-wrap: anywhere; }
h1 { letter-spacing: -1.8px; }
[data-testid="stMetricValue"] { font-family: var(--mono); }
[data-testid="stMetric"] { background: var(--surface); padding: 16px; border-radius: 2px; }
[data-testid="stMetricLabel"] p { font-size: 13px; white-space: normal; }
.eyebrow { color: var(--accent); font: 12px var(--mono); letter-spacing: 2px; margin-bottom: 4px; }
.block-container { max-width: 1440px; padding-top: 40px; }
.stButton button { min-height: 42px; white-space: nowrap; }
@media(max-width:768px) { .block-container { padding: 24px 16px; } h1 { font-size: 32px; } }
</style>""", unsafe_allow_html=True)


def flash(message):
    st.session_state["notice"] = message
    st.rerun()


now = datetime.now(timezone.utc)
hosted = os.environ.get("SUPPORT_AUTO_SEED_DEMO") == "1"
try:
    engine = make_engine()
    if hosted:
        prepare_demo(engine, now=now)
except WorkflowError as error:
    st.error(str(error))
    st.stop()

with st.sidebar:
    st.markdown('<p class="eyebrow">LOCAL WORKFLOW LAB</p>', unsafe_allow_html=True)
    st.header("Run the demo")
    st.caption("Fictional TaskHarbor SaaS support. No customer data or external sender.")
    mode = st.radio("Processing mode", ["Free demo", "Live LLM"], key="mode")
    if st.button("Load demo tickets", key="seed", width="stretch"):
        flash(f"Added {seed_demo(engine, now=now)} fictional tickets. Existing reviews were preserved.")
    if st.button("Process pending tickets", key="process", disabled=mode != "Free demo", width="stretch"):
        with st.spinner("Classifying, retrieving, and drafting..."):
            for pending in engine.tickets():
                if pending["status"] in {"NEW", "ERROR"} or not pending["processed_at"]:
                    engine.process(pending["id"], now=now)
            changed = engine.sweep_slas(now=now)
        flash(f"Demo workflow complete. {changed} newly breached SLAs flagged. Nothing was sent externally.")
    if st.button("Check SLAs", key="sla", width="stretch"):
        flash(f"Flagged {engine.sweep_slas(now=now)} newly breached resolution SLAs.")
    st.divider()
    reviewer = st.text_input("Reviewer label", value="Demo reviewer", max_chars=80)
    st.caption("This is an audit label, not authenticated identity. Local, single-operator demo.")
    allow_live = False
    if mode == "Live LLM":
        st.warning("Live mode sends fictional ticket text and KB excerpts to your configured provider.")
        allow_live = st.checkbox("Allow a live request; provider charges may apply", key="allow_live")
        st.caption("Requires SUPPORT_ENABLE_LIVE_LLM=1, API key, and model in the server environment. No automatic fallback.")

st.markdown('<p class="eyebrow">POST-SALES / HUMAN REVIEW</p>', unsafe_allow_html=True)
st.title("Support Autopilot")
st.write("The repetitive work moves forward. You decide what goes out.")
st.info("SYNTHETIC DEMO · Replies go to a local simulated outbox. No email, ClickUp connection, or autonomous sends.")
if hosted:
    with st.expander("Try it in 60 seconds", expanded=True):
        st.markdown(
            "You're a support agent at TaskHarbor, a made-up software company. The AI has already sorted "
            "12 customer emails and drafted replies. **You decide what goes out.**\n\n"
            "1. Below the queue, **SYN-1001 / Download invoice** is open. Read the AI's draft under "
            "**Review the reply**, then expand the source it cites and check that they match.\n"
            "2. Tick **I reviewed the reply and its sources**, then click **Approve & simulate reply**. "
            "The scoreboard updates. Nothing is really sent.\n"
            "3. Open a ticket the AI refused to answer: **SYN-1012** (someone tries to hijack the AI), "
            "**SYN-1006** (a security report), or **SYN-1007** (a question no help article covers). "
            "The yellow box says why it went to a person instead.\n\n"
            "If an earlier visitor already approved SYN-1001, try **SYN-1002**, **SYN-1005**, **SYN-1009**, "
            "or **SYN-1010**.")
    st.caption("Shared public demo: the queue was processed for you, but every reply still waits for your approval. "
               "Other visitors' decisions appear here too, and the data can be wiped when the host restarts the app.")
if notice := st.session_state.pop("notice", None):
    # A toast stays visible even when the reviewer is scrolled down to the approval panel.
    st.toast(notice, icon="✅")

metrics = engine.metrics(now=now)
one, two, three, four = st.columns(4)
one.metric("Assisted resolutions", str(metrics["assisted_resolutions"]),
           help="A ticket counts only after explicit approval and one simulated send.")
two.metric("Approval rate", f"{metrics['approval_rate']:.0%}",
           help="Approved / (approved + reviewer-escalated). Automatic escalations are excluded.")
three.metric("Open SLA breaches", str(metrics["open_sla_breaches"]),
             help="Unresolved tickets at or past their resolution deadline, including unprocessed tickets.")
four.metric("Est. time saved", f"{metrics['estimated_minutes_saved']} min",
            help="Illustrative assumption: 8 manual minutes - 2 review minutes per simulated resolution. Not measured.")
st.caption(f"{metrics['tickets']} tickets · {metrics['processed']} processed · "
           f"{metrics['assisted_resolution_rate']:.0%} AI-assisted resolution rate · "
           f"{metrics['reviewed']} human decisions · Time saved is an estimate, not observed customer impact.")

tickets = engine.tickets()
if not tickets:
    st.subheader("Start with a real workflow, using fictional tickets")
    st.write("Load the demo tickets, process the queue, then open a draft and inspect its sources before approving.")
    st.stop()

st.subheader("Ticket queue")
status_filter = st.selectbox("Filter by status", ["All", "NEW", "NEEDS_REVIEW", "ESCALATED", "ERROR", "RESOLVED"])
visible = [ticket for ticket in tickets if status_filter == "All" or ticket["status"] == status_filter]
if not visible:
    st.info("No tickets in this status.")
    st.stop()
st.dataframe([{"Ticket": ticket["external_id"], "Subject": ticket["subject"],
               "Category": (ticket["triage"] or {}).get("category", "pending"),
               "Urgency": (ticket["triage"] or {}).get("urgency", "pending"),
               "Sentiment": (ticket["triage"] or {}).get("sentiment", "pending"),
               "Queue": ticket["queue"], "Status": ticket["status"],
               "SLA": deadline_label(ticket["due_at"], now, ticket["status"])}
              for ticket in visible], hide_index=True, width="stretch")

by_id = {ticket["id"]: ticket for ticket in visible}
selected = st.selectbox("Open a ticket", list(by_id),
    format_func=lambda value: f"{by_id[value]['external_id']} / {by_id[value]['subject']}", key="ticket_id")
ticket = by_id[selected]
st.divider()
left, right = st.columns([1, 1.15], gap="large")
with left:
    st.markdown('<p class="eyebrow">01 / INTAKE & ROUTING</p>', unsafe_allow_html=True)
    st.subheader(ticket["subject"])
    st.write(ticket["body"])
    st.caption(f"{ticket['external_id']} · {ticket['status']} · {ticket['queue']}")
    if triage := ticket["triage"]:
        urgent = triage["urgency"] in {"high", "critical"}
        st.caption(f"Category :gray-badge[{triage['category']}] · "
                   f"Urgency :{'orange' if urgent else 'gray'}-badge[{triage['urgency']}] · "
                   f"Sentiment :gray-badge[{triage['sentiment']}]")
    st.caption(f"Created {format_utc(ticket['created_at'])} · Resolution deadline {format_utc(ticket['due_at'])} "
               f"({deadline_label(ticket['due_at'], now, ticket['status'])})")
    if ticket["reason"]:
        st.warning(ticket["reason"])
    if mode == "Live LLM" and (ticket["status"] in {"NEW", "ERROR"} or not ticket["processed_at"]):
        if st.button("Process this ticket with live LLM", disabled=not allow_live, key="live_process"):
            try:
                with st.spinner("Calling the configured model..."):
                    live_engine = make_engine(live=True)
                    live_engine.process(selected, now=now)
                    live_engine.sweep_slas(now=now)
                flash("Live request completed. Inspect the stored outcome and sources.")
            except (ProviderError, WorkflowError) as error:
                st.error(str(error))

with right:
    st.markdown('<p class="eyebrow">02 / EVIDENCE & APPROVAL</p>', unsafe_allow_html=True)
    st.subheader("Review the reply")
    draft = ticket["draft"]
    if draft:
        st.caption(f"Generated in {ticket['mode']} mode. Citations are checked; semantic correctness needs your review.")
        st.text(draft["body"])
        for excerpt in draft["evidence"]:
            with st.expander(f"[{excerpt['id']}] {excerpt['source']} / {excerpt['title']}"):
                st.text(excerpt["text"])
        if ticket["status"] != "RESOLVED":
            if st.session_state.get("_review_draft") != ticket["draft_hash"]:
                st.session_state["review_confirm"] = False
                st.session_state["_review_draft"] = ticket["draft_hash"]
            confirmed = st.checkbox("I reviewed the reply and its sources", key="review_confirm")
            approve_col, escalate_col = st.columns(2)
            if approve_col.button("Approve & simulate reply", key="approve", type="primary",
                                  disabled=not confirmed or not reviewer.strip(), width="stretch"):
                try:
                    engine.approve(selected, expected_hash=ticket["draft_hash"], reviewer=reviewer, now=now)
                    flash("Approved. One reply recorded in the local simulated outbox.")
                except (WorkflowError, KnowledgeError) as error:
                    st.error(str(error))
            if escalate_col.button("Escalate instead", key="reject", width="stretch"):
                try:
                    engine.escalate(selected, reviewer=reviewer, now=now)
                    flash("Escalated for a specialist. No reply sent.")
                except WorkflowError as error:
                    st.error(str(error))
        else:
            st.success("Human approved. Simulated reply recorded; no external delivery occurred.")
    else:
        st.info("No reply is available. Process a new ticket, or let a specialist handle an escalated case.")

with st.expander("Audit trail"):
    st.dataframe(engine.events(selected), hide_index=True, width="stretch")
with st.expander("Metric definitions & demo boundaries"):
    st.write("AI-assisted resolutions = unique local simulated outbox records. Resolution rate = resolutions / processed tickets. "
             "Approval rate = approved / (approved + reviewer-escalated). Open SLA breaches use elapsed UTC hours: "
             "critical 1, high 4, normal 24, low 48; unprocessed tickets default to 24. Check SLAs is an explicit sweep, "
             "not a background scheduler. Estimated time saved = resolutions × (8 − 2) minutes. All inputs and results are synthetic.")
