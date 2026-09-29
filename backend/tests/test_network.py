"""Unit tests for the P2 network impact internals.

The default run uses the demo grid (see conftest.py), which has no published traffic volumes. Checks
that only mean something on the real network -- divided carriageways, VicRoads counts, the
capacity curve's response to time of day -- are marked `real` and run with `REAL_DATA=1 pytest`.
"""
from __future__ import annotations

import math

import pytest

from app import config
from app.graph import _is_oneway, is_demo, load_graph, snap
from app.impact import capacity, routing
from app.impact.network import (
    _baseline, _closed_edges, _lanes, _routing_impact, closure_mods, demo_area, merge_segments, network_impact,
    opposite_carriageway, time_factor, volume_window,
)
from app.schemas import ClosureTarget, NetworkRequest, TimeWindow

real = pytest.mark.skipif(is_demo(), reason="needs the committed OSM network: run with REAL_DATA=1")


@pytest.fixture(scope="module")
def graph():
    return load_graph()


@pytest.fixture(scope="module")
def demo_edge():
    return snap(*config.DEMO_WORK_POINT)


@pytest.fixture(scope="module")
def area_baseline():
    return _baseline(demo_area())


def _key(edge, targets, direction="citybound", lanes=1):
    return ((tuple(edge),), tuple(sorted(targets, key=lambda t: t.value)), direction, lanes)


def _mods(graph, A, edge, targets, direction="citybound", lanes=1):
    return closure_mods(A, merge_segments(graph, (_key(edge, targets, direction, lanes),)))


# ---------- the exactness guarantee ----------
def test_incremental_matches_full_reassignment(graph, area_baseline, demo_edge):
    """The whole performance argument rests on this being EXACT, not approximate."""
    A, base = area_baseline
    for targets, lanes in (([ClosureTarget.full], 1), ([ClosureTarget.traffic_lane], 1),
                           ([ClosureTarget.traffic_lane], 2)):
        for direction in ("citybound", "both"):
            mods = _mods(graph, A, demo_edge, targets, direction, lanes)
            inc_times, _, _, _ = routing.assign_incremental(A, base, mods)
            full_times, _, _, _ = routing.assign_full(A, base, mods)
            for a, b in zip(inc_times, full_times):
                if math.isinf(a) or math.isinf(b):
                    assert math.isinf(a) and math.isinf(b)
                else:
                    assert a == pytest.approx(b, rel=1e-9)


def test_untouched_trips_keep_baseline_time(graph, area_baseline, demo_edge):
    A, base = area_baseline
    times, paths, _, dirty = routing.assign_incremental(A, base, _mods(graph, A, demo_edge, [ClosureTarget.full]))
    for i in range(base.n):
        if i not in dirty:
            assert times[i] == base.times[i]
            assert paths[i] == base.paths[i]


def test_closure_never_speeds_a_trip_up(graph, area_baseline, demo_edge):
    """A closure can only remove options, so no trip may get faster. Catches sign errors."""
    A, base = area_baseline
    times, _, _, _ = routing.assign_incremental(A, base, _mods(graph, A, demo_edge, [ClosureTarget.full]))
    for i in range(base.n):
        if not math.isinf(base.times[i]) and not math.isinf(times[i]):
            assert times[i] >= base.times[i] - 1e-6


def test_dirty_set_is_exactly_trips_over_the_closed_edge(graph, area_baseline, demo_edge):
    A, base = area_baseline
    _, _, _, dirty = routing.assign_incremental(A, base, _mods(graph, A, demo_edge, [ClosureTarget.full]))
    assert dirty == set(base.trips_by_edge.get(demo_edge, ()))


# ---------- closure semantics ----------
def test_bike_lane_only_leaves_vehicles_alone(graph, demo_edge):
    assert merge_segments(graph, (_key(demo_edge, [ClosureTarget.bike_lane]),)) == {}
    assert merge_segments(graph, (_key(demo_edge, [ClosureTarget.footpath]),)) == {}


def test_closing_every_lane_removes_the_edge(graph, demo_edge):
    effect = merge_segments(graph, (_key(demo_edge, [ClosureTarget.traffic_lane], lanes=_lanes(graph, demo_edge)),))
    assert effect[demo_edge] is None


def test_partial_lane_closure_penalises_rather_than_removes(graph, area_baseline, demo_edge):
    if _lanes(graph, demo_edge) < 2:
        pytest.skip("demo edge has a single lane")
    A, _ = area_baseline
    mods = _mods(graph, A, demo_edge, [ClosureTarget.traffic_lane])
    assert mods[demo_edge] > A.edges[demo_edge]["travel_time"]


@real
def test_both_directions_closes_the_opposite_carriageway(graph, demo_edge):
    """Flemington Rd is divided: OSM models it as two one-way ways with no (v, u) reverse edge,
    so a naive reverse lookup would close only half the road."""
    assert not graph.has_edge(demo_edge[1], demo_edge[0]), "expected a divided carriageway here"
    assert opposite_carriageway(demo_edge) is not None
    assert len(_closed_edges(graph, [demo_edge], "both")) == 2
    assert len(_closed_edges(graph, [demo_edge], "citybound")) == 1


# ---------- time window ----------
def test_volume_window_selects_the_right_profile():
    assert volume_window(TimeWindow.day) == "day"
    assert volume_window(TimeWindow.night) == "night"
    assert volume_window(TimeWindow.custom, (8, 10)) == "peak"
    assert volume_window(TimeWindow.custom, (10, 14)) == "custom"


def test_custom_hours_wrapping_past_midnight_are_handled():
    """An overnight window is two spans, [start, 24) and [0, end). Testing `start < pe and end > ps`
    directly silently misjudges every window that crosses midnight."""
    assert volume_window(TimeWindow.custom, (18, 2)) == "peak"    # [18,24) overlaps the 16-19 peak
    assert volume_window(TimeWindow.custom, (20, 5)) == "night"   # clears both peaks, inside the night window
    assert volume_window(TimeWindow.custom, (22, 2)) == "night"
    assert volume_window(TimeWindow.custom, (19, 23)) == "custom"  # starts before the night window
    assert volume_window(TimeWindow.custom, (5, 8)) == "peak"     # ordinary window, morning peak


def test_time_factor_is_relative_to_a_daytime_hour():
    assert time_factor(TimeWindow.day) == 1.0
    assert time_factor(TimeWindow.night) < 1.0


def test_every_window_has_a_volume_profile():
    for w in TimeWindow:
        assert volume_window(w) in config.AADT_HOURLY_FRACTION


# ---------- capacity / BPR ----------
def test_bpr_rises_with_volume():
    c = capacity.capacity_vph(2)
    assert capacity.bpr_factor(0, c) == pytest.approx(1.0)
    assert capacity.bpr_factor(c, c) > capacity.bpr_factor(c / 2, c) > 1.0


def test_zero_lanes_is_zero_capacity():
    """Clamping to one lane would leave a fully closed road still carrying traffic."""
    assert capacity.capacity_vph(0) == 0


def test_no_published_volume_means_no_invented_delay():
    missing = (-1, -2, 0)
    assert capacity.aadt_for(missing) is None
    assert capacity.edge_delay_delta_s(missing, 30.0, 2, "day", lanes_closed=1) == 0.0


def test_peak_is_directional():
    """Citybound AM peak measured 2,437 veh/h against outbound's 905 at the same hour. A single
    direction-blind peak factor would be wrong by ~2.7x."""
    assert capacity.hourly_volume(25_365, "peak", toward_cbd=True) > 2 * capacity.hourly_volume(25_365, "peak", toward_cbd=False)


def test_volume_profile_is_ordered():
    assert capacity.hourly_volume(25_365, "peak") > capacity.hourly_volume(25_365, "day") > capacity.hourly_volume(25_365, "night")


def test_measured_night_volume_matches_scats():
    """SCATS site 4463 measured 304-382 veh/h citybound overnight, depending on the window."""
    assert 250 <= capacity.hourly_volume(25_365, "night") <= 450


# ---------- end to end ----------
def _impact(edge, targets, direction="citybound", lanes_closed=1, **kw):
    seg = {"id": "1", "edges": [edge], "targets": targets, "direction": direction, "lanes_closed": lanes_closed}
    return network_impact(NetworkRequest(segments=[seg], **kw))


def test_bike_lane_closure_has_no_vehicle_impact(demo_edge):
    r = _impact(demo_edge, [ClosureTarget.bike_lane])
    assert r.affected_trips_pct == 0.0 and r.avg_extra_min == 0.0


def test_every_affected_trip_is_in_exactly_one_bucket(demo_edge):
    for targets, direction in (([ClosureTarget.full], "both"), ([ClosureTarget.traffic_lane], "citybound")):
        r = _impact(demo_edge, targets, direction)
        buckets = r.rerouted_trips_pct + r.slowed_trips_pct + r.unreachable_trips_pct
        assert buckets == pytest.approx(r.affected_trips_pct, abs=0.002)


def test_time_of_day_never_recomputes_routing(demo_edge):
    """Rule 3: the time window re-runs only the cheap volume lookup, never the routing."""
    _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.day)
    before = _routing_impact.cache_info()
    _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.night)
    _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.custom, custom_hours=(8, 9))
    after = _routing_impact.cache_info()
    assert after.misses == before.misses and after.hits == before.hits + 2


def test_edge_load_delta_is_a_share(demo_edge):
    for load in _impact(demo_edge, [ClosureTarget.full]).load_increase:
        assert 0 < load.delta <= 1.0


def test_repeated_calls_return_equal_results(demo_edge):
    """Guards the cached EdgeLoad objects against being mutated by per-request decoration."""
    assert _impact(demo_edge, [ClosureTarget.full]).model_dump() == _impact(demo_edge, [ClosureTarget.full]).model_dump()


def test_no_published_volume_means_no_congestion_delay(demo_edge):
    """The demo grid has no counts, so the only delay is the longer way round: time of day, which acts
    through volumes, cannot change the answer, and no count is reported for the closed road."""
    if not is_demo():
        pytest.skip("the real network has counts")
    day = _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.day)
    night = _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.night)
    assert day.slowed_trips_pct > 0 and day.avg_extra_min == night.avg_extra_min
    assert day.closed_aadt == {}


@real
def test_night_is_less_severe_than_day(demo_edge):
    """Can fail: night differs because the hourly volume drops below capacity, not by a multiplier."""
    day = _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.day)
    night = _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.night)
    assert night.avg_extra_min < day.avg_extra_min


@real
def test_peak_closure_is_worse_than_offpeak(demo_edge):
    """The model should reproduce why arterial lane closures are restricted to off-peak."""
    peak = _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.custom, custom_hours=(8, 9))
    off = _impact(demo_edge, [ClosureTarget.traffic_lane], time_window=TimeWindow.custom, custom_hours=(10, 14))
    assert peak.avg_extra_min > off.avg_extra_min


@real
def test_severity_is_monotone_in_lanes_closed(demo_edge, graph):
    if _lanes(graph, demo_edge) < 2:
        pytest.skip("needs a multi-lane edge")
    one = _impact(demo_edge, [ClosureTarget.traffic_lane], lanes_closed=1)
    two = _impact(demo_edge, [ClosureTarget.traffic_lane], lanes_closed=2)
    assert two.avg_extra_min >= one.avg_extra_min


@real
def test_closed_road_reports_its_published_count(demo_edge):
    r = _impact(demo_edge, [ClosureTarget.traffic_lane])
    assert r.closed_aadt["1"].aadt > 10_000, "Flemington Rd is a major arterial"


@real
def test_footpath_detour_uses_the_walk_network(demo_edge):
    r = _impact(demo_edge, [ClosureTarget.footpath])
    if r.ped_detour_m is None:
        pytest.skip("no alternative footway found around this edge")
    assert r.ped_detour_basis == "footway"


# ---------- graph loading ----------
@real
def test_graph_loads_without_osmnx(monkeypatch):
    """The API must never import osmnx: it lives in requirements-data.txt only."""
    import sys
    monkeypatch.setitem(sys.modules, "osmnx", None)
    import app.graph as g
    g.load_graph.cache_clear()
    try:
        G = g.load_graph()
    finally:
        g.load_graph.cache_clear()
    assert G.number_of_edges() > 0
    for _, _, d in list(G.edges(data=True))[:50]:
        assert isinstance(d["travel_time"], float) and isinstance(d["length"], float)


def test_edge_geometry_is_latlng_pairs(graph, demo_edge):
    from app.graph import edge_info
    geom = edge_info(graph, demo_edge)["geometry"]
    assert len(geom) >= 2
    for lat, lng in geom:
        assert -39 < lat < -37 and 144 < lng < 146


def test_snap_is_deterministic():
    assert snap(*config.DEMO_WORK_POINT) == snap(*config.DEMO_WORK_POINT)


# ---------- AADT join ----------
@real
def test_demo_edge_has_a_measured_volume(demo_edge):
    rec = capacity.aadt_for(demo_edge)
    assert rec is not None and rec["aadt"] > 10_000 and rec["year"] == 2019


@real
def test_published_direction_agrees_with_computed_bearing(graph, demo_edge):
    """Independent cross-check: our bearing rule and VicRoads' published travel direction are
    derived from completely different data and must agree."""
    from scripts.fetch_aadt import angular_diff, direction_bearing
    rec = capacity.aadt_for(demo_edge)
    published = direction_bearing(rec["direction"])
    computed = graph.edges[demo_edge].get("bearing")
    if published is None or computed is None:
        pytest.skip("no directional record")
    assert angular_diff(float(computed), published) <= config.AADT_BEARING_TOLERANCE_DEG


# ---------- lanes ----------
@real
def test_two_way_lanes_are_halved(graph):
    """OSM `lanes` counts both directions unless the way is one-way. Treating it as per-direction
    doubles the capacity of every two-way street."""
    checked = 0
    for u, v, k, d in graph.edges(keys=True, data=True):
        raw = d.get("lanes")
        if isinstance(raw, list) or raw is None:
            continue
        try:
            total = int(str(raw).split(";")[0])
        except ValueError:
            continue
        if total < 2:
            continue
        assert _lanes(graph, (u, v, k)) == (total if _is_oneway(d) else max(total // 2, 1))
        checked += 1
        if checked > 200:
            break
    assert checked > 0


def test_lanes_never_below_one(graph, demo_edge):
    assert _lanes(graph, demo_edge) >= 1


def test_oneway_parsing_handles_graphml_strings():
    assert _is_oneway({"oneway": True}) and _is_oneway({"oneway": "True"})
    assert not _is_oneway({"oneway": "False"}) and not _is_oneway({"oneway": None})
