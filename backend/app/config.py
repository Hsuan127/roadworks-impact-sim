"""Tunable parameters. Values marked TODO_VERIFY are placeholders, not engineering guidance."""
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Demo site: Flemington Rd x Racecourse Rd (approximate, for the map's initial view only)
DEMO_CENTER = (-37.7938, 144.9467)
# MVP work site: Flemington Rd just east of the intersection (TODO(P2): set from real data)
DEMO_WORK_POINT = (-37.7938, 144.9484)
GRAPH_RADIUS_M = 1500

# ---- network impact (owner: P2) ----
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
