"""Tunable parameters. Values marked TODO_VERIFY are placeholders, not engineering guidance."""
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Demo site: Flemington Rd x Racecourse Rd (approximate, for the map's initial view only)
DEMO_CENTER = (-37.7938, 144.9467)
# MVP work site: Flemington Rd just east of the intersection (TODO(P2): set from real data)
DEMO_WORK_POINT = (-37.7938, 144.9484)
# Drive network radius. 3 km so the real alternatives to a Flemington Rd closure (Racecourse Rd,
# Dynon Rd, Elliott Ave, Royal Pde) are inside the graph; a tighter box truncates detours and
# silently biases every number downward.
GRAPH_RADIUS_M = 3000
# Walk networks are much denser than drive networks, so a tight radius keeps the file manageable.
WALK_RADIUS_M = 800

# ---- network impact (owner: P2) ----
OD_SAMPLE_SIZE = 400
OD_SEED = 42
LANE_CLOSURE_TIME_FACTOR = {1: 1.8, 2: 3.0, 3: 4.5}  # TODO_VERIFY: travel-time multiplier per lanes closed
PEAK_HOURS = [(7, 9), (16, 19)]
# Time of day now enters the model through AADT_HOURLY_FRACTION below: a night closure is milder
# because fewer vehicles per hour meet the reduced capacity, not because of a blanket multiplier.
# The old TIME_WINDOW_FACTOR = {"day": 1.0, "night": 0.3} post-multiplier was removed when the
# volume/capacity curve landed; keeping both would have applied time of day twice.
FACILITY_ALERT_RADIUS_M = 200
LOAD_REPORT_THRESHOLD = 0.05  # only report streets taking >= 5 % of rerouted trips

# Re-route only the trips whose baseline path touched the closure. Exact, not an approximation
# (see impact/routing.py::assign_incremental). Set False to fall back to full reassignment.
USE_INCREMENTAL_ASSIGNMENT = True

# Divided carriageways: Flemington Rd is two separate one-way ways ~20 m apart, so a "both
# directions" closure cannot rely on G.has_edge(v, u). Matching tolerances for finding the twin.
OPPOSITE_CARRIAGEWAY_MAX_M = 60
OPPOSITE_BEARING_TOLERANCE_DEG = 45

# Walk links within this distance of the closed carriageway are treated as closed too.
WALK_BUFFER_M = 12

# ---- AADT join (scripts/fetch_aadt.py) ----
AADT_MATCH_RADIUS_M = 40
AADT_BEARING_TOLERANCE_DEG = 60

# ---- volume/capacity delay (impact/capacity.py) ----
# Share of a day's traffic that uses the road in one hour of the given window.
# TODO_VERIFY: rules of thumb (peak hour is commonly ~9-10 % of AADT), not measured for this site.
AADT_HOURLY_FRACTION = {"day": 0.06, "night": 0.015, "custom": 0.06, "peak": 0.09}
# TODO_VERIFY: through-capacity per lane on a SIGNALISED urban arterial, i.e. saturation flow
# already discounted for green time. A mid-block figure (~1800) would overstate capacity badly.
CAPACITY_PER_LANE_VPH = 900
# Standard BPR coefficients (Bureau of Public Roads). Widely used defaults.
BPR_ALPHA = 0.15
BPR_BETA = 4.0
# Cap the curve: beyond heavy oversaturation BPR grows without bound and stops being meaningful.
BPR_MAX_FACTOR = 8.0

# ---- transit (owner: P3) ----
TRANSIT_EDGE_BUFFER_M = 15
NEARBY_STOP_RADIUS_M = 400

# ---- comms (owner: P5) ----
VMS_LINES = 3
VMS_CHARS_PER_LINE = 12  # TODO_VERIFY with RPM Hire: actual board format
