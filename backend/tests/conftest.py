"""Tests run on the generated demo grid and demo transit, whatever real data is in app/data.

`REAL_DATA=1 pytest` instead runs against the committed OSM network, VicRoads volumes and any
GTFS subset in app/data: only the suites whose checks mean something there (P2 network, P3 transit).
The API and equipment suites assert demo-grid geometry, so they are left out of that run.
"""
import os
from pathlib import Path

from app import config

if os.environ.get("REAL_DATA"):
    collect_ignore = ["test_api.py", "test_equipment.py"]
else:
    config.DATA_DIR = Path(__file__).parent / "no-data"  # never created; set before app modules read it
