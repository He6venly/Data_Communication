"""Explicit test-only subprocess bootstrap; never a submission entry point."""

from pathlib import Path
import runpy
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from contract_double import install

install()
runpy.run_module("hw3.worker", run_name="__main__")
