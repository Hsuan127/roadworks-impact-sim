"""Tunable parameters. Values marked TODO_VERIFY are placeholders, not engineering guidance."""
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"

# Map's initial view; also the centre of the fetched OSM area (scripts/fetch_osm.py)
DEMO_CENTER = (-37.794491, 144.948750)
# MVP work site: on Flemington Rd, ~150 m east of the centre (off the demo grid's intersections)
DEMO_WORK_POINT = (-37.794491, 144.950450)
# Drive network radius. 3 km so the real alternatives to a Flemington Rd closure (Racecourse Rd,
# Dynon Rd, Elliott Ave, Royal Pde) are inside the graph; a tighter box truncates detours and
# silently biases every number downward.
GRAPH_RADIUS_M = 3000
# Walk networks are much denser than drive networks, so a tight radius keeps the file manageable.
WALK_RADIUS_M = 800

# ---- network impact (owner: P2) ----
# Trips are sampled and routed only within this distance of the works, not across the whole fetched area.
STUDY_RADIUS_M = 2500
STUDY_GRID_M = 500  # the study area's centre snaps to this grid, so nearby edits reuse one baseline
OD_SAMPLE_SIZE = 400
OD_SEED = 42
# TODO_VERIFY: travel-time multiplier per lanes closed. Steers route CHOICE only (a narrowed street
# is less attractive); the delay reported to the planner comes from the capacity curve below.
LANE_CLOSURE_TIME_FACTOR = {1: 1.8, 2: 3.0, 3: 4.5}
PEAK_HOURS = [(7, 9), (16, 19)]
NIGHT_HOURS = (20, 5)  # the measured night window: custom hours inside it use its volumes
# Time of day enters the model through AADT_HOURLY_FRACTION below: a night closure is milder
# because fewer vehicles per hour meet the reduced capacity, not because of a blanket multiplier.
# The old TIME_WINDOW_FACTOR = {"day": 1.0, "night": 0.3} post-multiplier was removed when the
# volume/capacity curve landed; keeping both would have applied time of day twice.
FACILITY_ALERT_RADIUS_M = 200
LOAD_REPORT_THRESHOLD = 0.05  # only report streets taking >= 5 % of affected trips

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
# MEASURED, not assumed: SCATS site 4463 FLEMINGTON/ABBOTSFORD (near the demo work point),
# 22 weekdays of March 2026, citybound detectors 5-8. Cross-checked against VicRoads 2019 AADT:
# SCATS daily 25,568 vs AADT 25,365 citybound (+0.8 %), 23,110 vs 23,011 outbound (+0.4 %).
# Sources: "Traffic Signal Volume Data" + "Victorian Traffic Signals" (site coordinates), CC BY 4.0.
AADT_HOURLY_FRACTION = {
    # 09:30-15:30, the DTP arterial off-peak window this site actually gets. Mean 1,436 veh/h.
    "day": 0.0562,
    # 20:00-05:00, a standard nine-hour night shift. Mean 374 veh/h. Note this window straddles the
    # City of Melbourne 22:00 noisy-works cutoff, so Plan B needs an out-of-hours permit.
    "night": 0.0146,
    "custom": 0.0562,  # ASSUMPTION: custom off-peak hours outside the night window reuse the day mean
    "peak": 0.0953,   # AM peak 07:30-08:30 TOWARD the CBD. Mean 2,437 veh/h.
    # The same clock hour is not the same road. Citybound AM peak is 2,437 veh/h against outbound's
    # 905 - a factor of 2.7. A single direction-blind peak factor is wrong by that much, so the
    # contraflow direction gets its own measured figure.
    "peak_contraflow": 0.039,
}
# The busiest single hour INSIDE each window, for anyone sizing to a worst case rather than a
# typical hour (P4 device counts, if AGTTM keys off peak flow). Measured at the same site:
# day 1,801 veh/h (0.0704), night 793 (0.0310), which is where the day window's V/C reaches 1.00
# with one of two lanes closed. P2's reported delay uses the window MEAN, not these.
AADT_HOURLY_FRACTION_BUSIEST = {"day": 0.0704, "night": 0.0310, "peak": 0.0953}
# Flinders Street Station: "toward the CBD" is measured against this.
CBD_POINT = (-37.8183, 144.9671)
# TODO_VERIFY: through-capacity per lane on a SIGNALISED urban arterial, i.e. saturation flow
# already discounted for green time. A mid-block figure (~1800) would overstate capacity badly.
CAPACITY_PER_LANE_VPH = 900
# Standard BPR coefficients (Bureau of Public Roads). Widely used defaults.
BPR_ALPHA = 0.15
BPR_BETA = 4.0
# Cap the curve: beyond heavy oversaturation BPR grows without bound and stops being meaningful.
BPR_MAX_FACTOR = 8.0

# ---- alternative volume-delay functions (impact/capacity.py), selectable in the UI ----
# Conical (Spiess 1990, Transportation Science 24(2)). ALPHA plays the role of BPR's exponent;
# 4 matches BPR_BETA so the two curves are comparable. TODO_VERIFY: no local calibration.
CONICAL_ALPHA = 4.0

# ---- transit (owner: P3) ----
# TODO_VERIFY(P3): calibrated on the demo grid, where the synthetic straight street sits
# ~46 m from the real tram tracks in Flemington Rd's median. At 15 m a full closure there
# reported no routes at all. Re-measure once fetch_osm.py provides real street geometry:
# the true offset is the median width, and this may then be far too wide.
TRANSIT_EDGE_BUFFER_M = 50
NEARBY_STOP_RADIUS_M = 400

# ---- comms (owner: P5) ----
VMS_MAX_SCREENS = 2
VMS_WORDS_PER_SCREEN = 4
VMS_LINES = 3
VMS_CHARS_PER_LINE = 12  # TODO_VERIFY with RPM Hire: actual board format

# ---- nearby planned works (DTP Planned Disruptions snapshot, scripts/fetch_disruptions.py) ----
# Design choices for a display ranking, not engineering guidance: nothing here enters a calculation.
DISRUPTION_RADIUS_M = 3000  # the drive graph's radius: works further out are not shown
DISRUPTION_HALF_M = 500  # closeness halves at this distance from the drawn works
DAY_HOURS = (9.5, 15.5)  # the day window as modelled elsewhere: DTP arterial off-peak 09:30-15:30
