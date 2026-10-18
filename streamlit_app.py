"""Hosted-demo entrypoint (Streamlit Community Cloud). Same dashboard; an empty queue is seeded and processed."""
import os
import runpy
from pathlib import Path

os.environ["SUPPORT_AUTO_SEED_DEMO"] = "1"
runpy.run_path(str(Path(__file__).with_name("app.py")), run_name="__main__")
