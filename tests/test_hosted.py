"""Hosted-demo behavior: a public visitor lands on a processed queue, and nothing is approved for them."""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path
import threading
import tomllib

from streamlit.testing.v1 import AppTest

from conftest import NOW
from support_autopilot import seed
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


def test_local_app_does_not_auto_seed(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPPORT_DATA_DIR", str(tmp_path / "local"))
    monkeypatch.delenv("SUPPORT_AUTO_SEED_DEMO", raising=False)
    at = AppTest.from_file(ROOT / "app.py", default_timeout=15).run()
    assert not at.exception
    assert len(at.dataframe) == 0


def test_shared_config_lets_the_host_choose_the_bind_address():
    # Community Cloud must reach the server; the local launcher pins loopback on its command line.
    config = tomllib.loads((ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    assert "address" not in config.get("server", {})
    assert "--server.address 127.0.0.1" in (ROOT / "run.ps1").read_text(encoding="utf-8")
