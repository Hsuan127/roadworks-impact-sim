"""Volume/capacity delay for the network impact engine (owner: P2).

Why this exists. Shortest-path assignment on a free-flow network says a Flemington Rd closure costs
0.5 seconds: there is always a parallel street one block over, and nothing in the model makes that
street any slower when traffic piles onto it. Measured on the real graph, closing the entire
citybound carriageway rerouted 4.6 % of trips for a maximum of 0.54 s. That is a true statement
about a model with no capacity, and a useless statement about a road.

So delay comes from congestion, not from distance. Each edge with a known traffic volume gets a
volume-delay curve. Two standard ones, chosen by the planner (default BPR):

    BPR (Bureau of Public Roads, 1964)   t = t0 * (1 + alpha * x^beta)
    Conical (Spiess 1990)                t = t0 * (2 + sqrt(a^2 (1-x)^2 + b^2) - a (1-x) - b),  b = (2a-1)/(2a-2)

with x = V/C. They agree at low flow and part ways near and past capacity, which is exactly where a
lane closure puts a road: the spread between them is how much the answer depends on the curve.

Akcelik (1991, ARRB), the usual third choice in Australia, was tried and NOT offered. On the demo it
gave 35-60 min for a 30 m kerb-lane closure, for two reasons that are this model's, not the curve's:
several single-lane edges already carry 1,236-1,426 veh/h in the day window against the assumed
900 veh/h/lane (V/C 1.4-1.6 before any closure; BPR's flat curve hides that, a queueing curve does
not), and its additive queue delay was charged on every OSM edge fragment, some 0.2 s long, instead
of once per bottleneck. Revisit once lane counts / capacity are checked and delay is per bottleneck.

Closing a lane cuts C; diverted traffic raises V on the streets it lands on. Both push V/C up, and
the curve turns that into time. Volumes are real (VicRoads AADT); capacities are an assumption and
are marked TODO_VERIFY.

Deliberate limits, stated rather than hidden:
  * Only edges with a matched AADT record get a curve. That is the declared arterial network; most
    residential streets have no published count, so they stay free-flow and this UNDER-states the
    impact of dumping traffic into back streets.
  * One pass, not a user equilibrium. Drivers do not re-choose routes in response to the congestion
    they cause. Real assignment iterates; this does not.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

from .. import config

Edge = tuple[int, int, int]


@lru_cache(maxsize=1)
def aadt_table() -> dict[Edge, dict]:
    """Edge -> AADT record, written by scripts/fetch_aadt.py. Empty when it has not been run."""
    path = config.DATA_DIR / "aadt_by_edge.json"
    if not path.exists():
        return {}
    out: dict[Edge, dict] = {}
    for key, rec in json.loads(path.read_text()).items():
        u, v, k = key.split(",")
        out[(int(u), int(v), int(k))] = rec
    return out


def aadt_for(edge: Edge) -> dict | None:
    return aadt_table().get(edge)


def hourly_volume(aadt: int, window: str, toward_cbd: bool = True) -> float:
    """Vehicles per hour in the given window.

    Peak is directional. Measured at the demo site, the citybound AM peak carries 2,437 veh/h while
    the outbound carriageway carries 905 in the same hour; applying one factor to both would be
    wrong by a factor of 2.7. Off-peak and night are near-symmetric, so they share a figure.
    """
    key = window
    if window == "peak" and not toward_cbd:
        key = "peak_contraflow"
    return aadt * config.AADT_HOURLY_FRACTION.get(key, config.AADT_HOURLY_FRACTION["day"])


def capacity_vph(lanes: int) -> float:
    """Zero lanes means zero capacity. Clamping this to one lane (as an earlier version did by
    writing max(lanes, 1)) quietly left a fully closed road carrying 900 vehicles an hour."""
    return max(lanes, 0) * config.CAPACITY_PER_LANE_VPH


FORMULAS = ("bpr", "conical")


def bpr_factor(volume: float, capacity: float) -> float:
    """Travel-time multiplier. 1.0 at zero flow, rising steeply as volume approaches capacity."""
    if capacity <= 0:
        return config.BPR_MAX_FACTOR
    ratio = volume / capacity
    return min(1.0 + config.BPR_ALPHA * ratio ** config.BPR_BETA, config.BPR_MAX_FACTOR)


def conical_factor(volume: float, capacity: float) -> float:
    """Spiess' conical curve: 1.0 at zero flow, exactly 2.0 at capacity, then close to linear, so it
    never explodes the way a 4th power does. Shares BPR's cap for a closed road."""
    if capacity <= 0:
        return config.BPR_MAX_FACTOR
    a = config.CONICAL_ALPHA
    b = (2 * a - 1) / (2 * a - 2)
    y = 1 - volume / capacity
    return min(2 + math.sqrt(a * a * y * y + b * b) - a * y - b, config.BPR_MAX_FACTOR)


def travel_time_s(free_flow_s: float, volume: float, capacity: float, formula: str = "bpr") -> float:
    """Time to traverse one edge under the chosen volume-delay function."""
    if formula == "conical":
        return free_flow_s * conical_factor(volume, capacity)
    return free_flow_s * bpr_factor(volume, capacity)


def edge_delay_delta_s(
    edge: Edge,
    free_flow_s: float,
    lanes: int,
    window: str,
    lanes_closed: int = 0,
    added_vehicles_ph: float = 0.0,
    toward_cbd: bool = True,
    formula: str = "bpr",
) -> float:
    """Extra seconds to traverse `edge` once, after the closure, versus before.

    Returns 0.0 for any edge with no published volume: without V we cannot form V/C, and inventing
    one would be exactly the kind of fabricated quantity the project's honesty rule forbids.
    """
    rec = aadt_for(edge)
    if rec is None:
        return 0.0
    v_base = hourly_volume(rec["aadt"], window, toward_cbd)
    c_base = capacity_vph(max(lanes, 1))
    c_new = capacity_vph(max(lanes - lanes_closed, 0))
    v_new = v_base + added_vehicles_ph
    before = travel_time_s(free_flow_s, v_base, c_base, formula)
    after = travel_time_s(free_flow_s, v_new, c_new, formula)
    return max(after - before, 0.0)


def diverted_vehicles_ph(closed_edges: list[Edge], window: str, fully_closed: bool,
                         lanes: int, lanes_closed: int, toward_cbd: bool = True) -> float:
    """How many vehicles per hour actually have to go somewhere else.

    A full closure diverts everything. A partial lane closure diverts only what no longer fits:
    the excess of demand over the reduced capacity, which is zero on a quiet road and large on a
    saturated one. That is the whole reason a lane closure at 3am differs from one at 8am.
    """
    total = 0.0
    for e in closed_edges:
        rec = aadt_for(e)
        if rec is None:
            continue
        v = hourly_volume(rec["aadt"], window, toward_cbd)
        if fully_closed:
            total += v
        else:
            total += max(v - capacity_vph(max(lanes - lanes_closed, 0)), 0.0)
    return total
