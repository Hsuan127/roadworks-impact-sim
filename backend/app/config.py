"""Tunable parameters. Values marked TODO_VERIFY are placeholders, not engineering guidance."""
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Map's initial view; also the centre of the fetched OSM area (scripts/fetch_osm.py)
DEMO_CENTER = (-37.794491, 144.948750)
# MVP work site: on Flemington Rd, ~150 m east of the centre (off the demo grid's intersections)
DEMO_WORK_POINT = (-37.794491, 144.950450)

# ---- network impact (owner: P2) ----
# Trips are sampled and routed only within this distance of the works, not across the whole fetched area.
STUDY_RADIUS_M = 2500
STUDY_GRID_M = 500  # the study area's centre snaps to this grid, so nearby edits reuse one baseline
OD_SAMPLE_SIZE = 400
OD_SEED = 42
LANE_CLOSURE_TIME_FACTOR = {1: 1.8, 2: 3.0, 3: 4.5}  # TODO_VERIFY: travel-time multiplier per lanes closed
TIME_WINDOW_FACTOR = {"day": 1.0, "night": 0.3}  # TODO_VERIFY: delay severity by time window
PEAK_HOURS = [(7, 9), (16, 19)]
PEAK_FACTOR, OFFPEAK_FACTOR = 1.3, 0.8  # used for custom hours
FACILITY_ALERT_RADIUS_M = 200
LOAD_REPORT_THRESHOLD = 0.05  # only report streets taking >= 5 % of rerouted trips

# ---- transit (owner: P3) ----
TRANSIT_EDGE_BUFFER_M = 15
NEARBY_STOP_RADIUS_M = 400

# ---- comms (owner: P5) ----
VMS_LINES = 3
VMS_CHARS_PER_LINE = 12  # TODO_VERIFY with RPM Hire: actual board format
