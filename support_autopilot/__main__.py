"""Small local CLI; no external sending command exists."""
import argparse
import json
from datetime import datetime, timezone

from .config import make_engine
from .recorded import record_live_run
from .seed import seed_demo


def main():
    parser = argparse.ArgumentParser(description="Local support workflow demo; all tickets are synthetic")
    parser.add_argument("command", choices=["seed", "process", "sla", "metrics", "record"])
    args = parser.parse_args()
    engine, now = make_engine(), datetime.now(timezone.utc)
    if args.command == "seed":
        print(json.dumps({"added": seed_demo(engine, now=now)}))
    elif args.command == "process":
        count = 0
        for ticket in engine.tickets():
            if ticket["status"] in {"NEW", "ERROR"} or not ticket["processed_at"]:
                engine.process(ticket["id"], now=now)
                count += 1
        print(json.dumps({"processed": count, "sla_escalated": engine.sweep_slas(now=now), "external_sends": 0}))
    elif args.command == "record":
        # Opt-in paid call: needs SUPPORT_ENABLE_LIVE_LLM=1, a key, and a model in the environment.
        print(json.dumps(record_live_run(now=now)))
    elif args.command == "sla":
        print(json.dumps({"escalated": engine.sweep_slas(now=now)}))
    else:
        print(json.dumps(engine.metrics(now=now), indent=2))


if __name__ == "__main__":
    main()
