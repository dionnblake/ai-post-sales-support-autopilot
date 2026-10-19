"""Hosted-demo behavior: a public visitor lands on a processed queue, and nothing is approved for them."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import threading
import tomllib

from streamlit.testing.v1 import AppTest

from conftest import NOW
from support_autopilot import seed
from support_autopilot.config import make_engine
from support_autopilot.seed import SAMPLES, prepare_demo

ROOT = Path(__file__).resolve().parents[1]


def test_empty_database_is_seeded_and_processed_but_never_approved(engine):
    assert prepare_demo(engine, now=NOW) == len(SAMPLES)
    tickets = engine.tickets()
    assert len(tickets) == len(SAMPLES)
    assert all(ticket["processed_at"] for ticket in tickets)
    assert any(ticket["status"] == "NEEDS_REVIEW" for ticket in tickets)
    assert not any(ticket["status"] == "RESOLVED" for ticket in tickets)
    assert engine.outbox() == []
    assert engine.metrics(now=NOW)["assisted_resolutions"] == 0


def test_existing_data_and_reviews_are_left_alone(engine, invoice):
    engine.process(invoice, now=NOW)
    ticket = engine.get_ticket(invoice)
    engine.approve(invoice, expected_hash=ticket["draft_hash"], reviewer="Earlier visitor", now=NOW)
    assert prepare_demo(engine, now=NOW) == 0
    assert [t["external_id"] for t in engine.tickets()] == ["example-001"]
    assert len(engine.outbox()) == 1


def test_untouched_new_tickets_are_not_processed_behind_the_operator(engine, invoice):
    assert prepare_demo(engine, now=NOW) == 0
    assert engine.get_ticket(invoice)["status"] == "NEW"


def test_interrupted_first_load_is_finished_on_the_next_visit(engine):
    # A first load that died after intake left seed tickets unprocessed.
    engine.intake("SYN-1001", *SAMPLES[0][:2], created_at=NOW - timedelta(hours=SAMPLES[0][2]))
    prepare_demo(engine, now=NOW)
    tickets = engine.tickets()
    assert len(tickets) == len(SAMPLES)
    assert all(ticket["processed_at"] for ticket in tickets)
    assert engine.outbox() == []


def test_first_load_waits_for_the_shared_lock(engine):
    worker = threading.Thread(target=prepare_demo, args=(engine,), kwargs={"now": NOW})
    with seed.FIRST_LOAD_LOCK:
        worker.start()
        worker.join(timeout=0.5)
        assert worker.is_alive()
        assert engine.tickets() == []
    worker.join(timeout=20)
    assert not worker.is_alive()
    assert len(engine.tickets()) == len(SAMPLES)


def test_simultaneous_first_visitors_seed_once(engine):
    # Real visitors arrive with different clocks; unserialized seeding would conflict on created_at.
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda offset: prepare_demo(engine, now=NOW + timedelta(seconds=offset)), range(4)))
    tickets = engine.tickets()
    assert len(tickets) == len(SAMPLES)
    for ticket in tickets:
        assert [e["kind"] for e in engine.events(ticket["id"])].count("PROCESSED") == 1
    assert engine.outbox() == []


def test_hosted_entrypoint_lands_on_a_populated_queue_with_approval_still_locked(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "hosted"))
    # Registers the variable so the entrypoint's assignment is undone after this test.
    monkeypatch.setenv("SUPPORT_AUTO_SEED_DEMO", "0")
    at = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=20).run()
    assert not at.exception
    assert len(at.dataframe[0].value) == len(SAMPLES)
    assert at.metric[0].value == "0"
    assert at.button(key="approve").disabled
    at.checkbox(key="review_confirm").check().run()
    at.button(key="approve").click().run()
    assert not at.exception
    assert at.metric[0].value == "1"


GUIDE_LABEL = "Try it in 60 seconds"
GUIDE_REVIEWABLE = ["SYN-1001", "SYN-1002", "SYN-1005", "SYN-1009", "SYN-1010"]
GUIDE_REFUSED = ["SYN-1006", "SYN-1007", "SYN-1012"]


def test_hosted_page_opens_with_a_short_guide_whose_claims_hold(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "guide"))
    monkeypatch.setenv("SUPPORT_AUTO_SEED_DEMO", "0")
    at = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=20).run()
    assert not at.exception
    guides = [expander for expander in at.expander if expander.label == GUIDE_LABEL]
    assert len(guides) == 1
    text = " ".join(block.value for block in guides[0].markdown)
    # The guide names real controls, by labels that hold at any screen width...
    assert "on the right" not in text
    review_panel = next(header.value for header in at.subheader if header.value == "Review the reply")
    assert review_panel in text
    assert at.checkbox(key="review_confirm").label in text
    assert at.button(key="approve").label in text
    # ...and real tickets, which behave the way it says.
    for external_id in GUIDE_REVIEWABLE + GUIDE_REFUSED:
        assert external_id in text
    tickets = {ticket["external_id"]: ticket for ticket in make_engine().tickets()}
    assert at.selectbox(key="ticket_id").value == tickets["SYN-1001"]["id"]
    assert all(tickets[external_id]["status"] == "NEEDS_REVIEW" for external_id in GUIDE_REVIEWABLE)
    refusals = {"SYN-1006": ("Security", "Security"), "SYN-1007": ("Specialist", "knowledge-base evidence"),
                "SYN-1012": ("Security", "untrusted-instruction")}
    assert set(refusals) == set(GUIDE_REFUSED)
    for external_id, (queue, reason) in refusals.items():
        ticket = tickets[external_id]
        assert (ticket["status"], ticket["queue"], ticket["draft"]) == ("ESCALATED", queue, None)
        # The guide promises a yellow box explaining why a person took over.
        at.selectbox(key="ticket_id").set_value(ticket["id"]).run()
        assert any(reason in warning.value for warning in at.warning)


def sidebar_text(at):
    return " ".join(element.value for element in [*at.sidebar.markdown, *at.sidebar.caption])


def test_hosted_sidebar_does_not_claim_a_local_single_operator_app(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "sidebar"))
    monkeypatch.setenv("SUPPORT_AUTO_SEED_DEMO", "0")
    at = AppTest.from_file(ROOT / "streamlit_app.py", default_timeout=20).run()
    assert not at.exception
    text = sidebar_text(at)
    assert "local" not in text.lower()
    assert "single-operator" not in text
    assert "not authenticated identity" in text
    assert "shared public demo" in text.lower()


def test_local_sidebar_keeps_its_local_wording(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "local-sidebar"))
    monkeypatch.delenv("SUPPORT_AUTO_SEED_DEMO", raising=False)
    at = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    text = sidebar_text(at)
    assert "LOCAL WORKFLOW LAB" in text
    assert "Local, single-operator demo." in text


def test_local_app_does_not_auto_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.delenv("SUPPORT_AUTO_SEED_DEMO", raising=False)
    at = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    assert not at.exception
    assert len(at.dataframe) == 0
    assert not any(expander.label == GUIDE_LABEL for expander in at.expander)


def test_shared_config_lets_the_host_choose_the_bind_address():
    # Community Cloud must reach the server; the local launcher pins loopback on its command line.
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert "address" not in config.get("server", {})
    assert "--server.address 127.0.0.1" in (ROOT / "run.ps1").read_text(encoding="utf-8")
