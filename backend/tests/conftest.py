"""Tests run on the generated demo grid and demo transit, whatever real data is in app/data."""
from pathlib import Path

from app import config

config.DATA_DIR = Path(__file__).parent / "no-data"  # never created; set before app modules read it
