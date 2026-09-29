"""Unit tests for the P2 network impact internals.

These did not exist before: the only P2 coverage was two API smoke tests, one of which
(test_night_is_less_severe_than_day) was true by construction and would have passed even if the
routing engine returned zeros.
"""
from __future__ import annotations

import math

import networkx as nx
import pytest

from app import config
from app.graph import load_graph, snap
from app.impact import capacity, routing
from app.impact.network import (
    _closed_edges, _lanes, closure_mods, network_impact, opposite_carriageway, time_factor,
    volume_window,
)
from app.schemas import ClosureTarget, NetworkRequest, TimeWindow


@pytest.fixture(scope="module")
def graph():
    return load_graph()


@pytest.fixture(scope="module")
def demo_edge():
    return snap(*config.DEMO_WORK_POINT)


@pytest.fixture(scope="module")
def baseline(graph):
    from app.impact.network import _baseline
    return _baseline()


# ---------- the exactness guarantee ----------
def test_incremental_matches_full_reassignment(graph, baseline, demo_edge):
    """The whole performance argument rests on this being EXACT, not approximate."""
    for targets, lanes in (([ClosureTarget.full], 1), ([ClosureTarget.traffic_lane], 1),
                           ([ClosureTarget.traffic_lane], 2)):
        for direction in ("citybound", "both"):
            closed = _closed_edges(graph, demo_edge, direction)
            mods = closure_mods(graph, closed, targets, lanes)
            inc_times, _, _, _ = routing.assign_incremental(graph, baseline, mods)
            full_times, _, _, _ = routing.assign_full(graph, baseline, mods)
            for a, b in zip(inc_times, full_times):
                if math.isinf(a) or math.isinf(b):
                    assert math.isinf(a) and math.isinf(b)
                else:
                    assert a == pytest.approx(b, rel=1e-9)


def test_untouched_trips_keep_baseline_time(graph, baseline, demo_edge):
    mods = closure_mods(graph, [demo_edge], [ClosureTarget.full], 1)
    times, paths, _, dirty = routing.assign_incremental(graph, baseline, mods)
    for i in range(baseline.n):
        if i not in dirty:
            assert times[i] == baseline.times[i]
            assert paths[i] == baseline.paths[i]


def test_closure_never_speeds_a_trip_up(graph, baseline, demo_edge):
    """A closure can only remove options, so no trip may get faster. Catches sign errors."""
    mods = closure_mods(graph, [demo_edge], [ClosureTarget.full], 1)
    times, _, _, _ = routing.assign_incremental(graph, baseline, mods)
    for i in range(baseline.n):
        if not math.isinf(baseline.times[i]) and not math.isinf(times[i]):
            assert times[i] >= baseline.times[i] - 1e-6


def test_dirty_set_is_exactly_trips_over_the_closed_edge(graph, baseline, demo_edge):
    mods = closure_mods(graph, [demo_edge], [ClosureTarget.full], 1)
    _, _, _, dirty = routing.assign_incremental(graph, baseline, mods)
    assert dirty == set(baseline.trips_by_edge.get(demo_edge, ()))


# ---------- closure semantics ----------
def test_bike_lane_only_leaves_vehicles_alone(graph, demo_edge):
    assert closure_mods(graph, [demo_edge], [ClosureTarget.bike_lane], 1) == {}
    assert closure_mods(graph, [demo_edge], [ClosureTarget.footpath], 1) == {}


def test_closing_every_lane_removes_the_edge(graph, demo_edge):
    lanes = _lanes(graph, demo_edge)
    mods = closure_mods(graph, [demo_edge], [ClosureTarget.traffic_lane], lanes)
    assert mods[demo_edge] is None


def test_partial_lane_closure_penalises_rather_than_removes(graph, demo_edge):
    lanes = _lanes(graph, demo_edge)
    if lanes < 2:
        pytest.skip("demo edge has a single lane")
    mods = closure_mods(graph, [demo_edge], [ClosureTarget.traffic_lane], 1)
    assert mods[demo_edge] > graph.edges[demo_edge]["travel_time"]


def test_both_directions_closes_the_opposite_carriageway(graph, demo_edge):
    """Flemington Rd is divided: OSM models it as two one-way ways with no (v, u) reverse edge,
    so a naive reverse lookup would close only half the road."""
    if graph.graph.get("name") == "demo-grid":
        pytest.skip("demo grid is not divided")
    assert not graph.has_edge(demo_edge[1], demo_edge[0]), "expected a divided carriageway here"
    twin = opposite_carriageway(demo_edge)
    assert twin is not None
    assert len(_closed_edges(graph, demo_edge, "both")) == 2
    assert len(_closed_edges(graph, demo_edge, "citybound")) == 1


# ---------- time window ----------
def test_volume_window_selects_the_right_profile():
    assert volume_window(TimeWindow.day) == "day"
    assert volume_window(TimeWindow.night) == "night"
    assert volume_window(TimeWindow.custom, (8, 10)) == "peak"
    assert volume_window(TimeWindow.custom, (10, 14)) == "custom"


def test_custom_hours_wrapping_past_midnight_are_handled():
    """An overnight window is two spans, [start, 24) and [0, end). Testing `start < pe and end > ps`
    directly, as the original code did, silently misjudges every window that crosses midnight."""
    assert volume_window(TimeWindow.custom, (18, 2)) == "peak"    # [18,24) overlaps the 16-19 peak
    assert volume_window(TimeWindow.custom, (20, 5)) == "custom"  # clears both peaks
    assert volume_window(TimeWindow.custom, (5, 8)) == "peak"     # ordinary window, morning peak


def test_time_factor_is_relative_to_a_daytime_hour():
    assert time_factor(TimeWindow.day) == 1.0
    assert time_factor(TimeWindow.night) < 1.0


def test_every_window_has_a_volume_profile():
    """The old code did TIME_WINDOW_FACTOR.get("custom", 1.0) and silently fell back to 1.0."""
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


# ---------- end to end ----------
def _impact(edge, **kw):
    kw.setdefault("direction", "citybound")
    kw.setdefault("lanes_closed", 1)
    return network_impact(NetworkRequest(edge=edge, **kw))


def test_bike_lane_closure_has_no_vehicle_impact(demo_edge):
    r = _impact(demo_edge, targets=[ClosureTarget.bike_lane])
    assert r.affected_trips_pct == 0.0
    assert r.avg_extra_min == 0.0


def test_severity_is_monotone_in_lanes_closed(demo_edge, graph):
    if _lanes(graph, demo_edge) < 2:
        pytest.skip("needs a multi-lane edge")
    one = _impact(demo_edge, targets=[ClosureTarget.traffic_lane], lanes_closed=1)
    two = _impact(demo_edge, targets=[ClosureTarget.traffic_lane], lanes_closed=2)
    assert two.avg_extra_min >= one.avg_extra_min


def test_night_is_less_severe_than_day(demo_edge):
    """Unlike the old API smoke test, this can fail: night differs because the hourly volume drops
    below capacity, not because of a constant multiplier."""
    day = _impact(demo_edge, targets=[ClosureTarget.traffic_lane], time_window=TimeWindow.day)
    night = _impact(demo_edge, targets=[ClosureTarget.traffic_lane], time_window=TimeWindow.night)
    assert night.avg_extra_min <= day.avg_extra_min


def test_unreachable_trips_are_not_reported_as_delay(demo_edge):
    r = _impact(demo_edge, targets=[ClosureTarget.full], direction="both")
    assert 0.0 <= r.unreachable_trips_pct <= 1.0
    assert r.max_extra_min != 60.0, "60.0 was the old saturation constant masquerading as a delay"


def test_edge_load_delta_is_a_share(demo_edge):
    r = _impact(demo_edge, targets=[ClosureTarget.full])
    for load in r.load_increase:
        assert 0 < load.delta <= 1.0


def test_routing_cache_is_reused(demo_edge):
    from app.impact.network import _routing_impact
    _impact(demo_edge, targets=[ClosureTarget.full])
    before = _routing_impact.cache_info().hits
    _impact(demo_edge, targets=[ClosureTarget.full])
    assert _routing_impact.cache_info().hits > before


def test_repeated_calls_return_equal_results(demo_edge):
    """Guards the cached EdgeLoad objects against being mutated by per-request decoration."""
    a = _impact(demo_edge, targets=[ClosureTarget.full])
    b = _impact(demo_edge, targets=[ClosureTarget.full])
    assert a.model_dump() == b.model_dump()


# ---------- graph loading ----------
def test_graph_loads_without_osmnx(monkeypatch):
    """The API must never import osmnx: it lives in requirements-data.txt only."""
    import sys
    monkeypatch.setitem(sys.modules, "osmnx", None)
    import app.graph as g
    g.load_graph.cache_clear()
    G = g.load_graph()
    assert G.number_of_edges() > 0
    for _, _, d in list(G.edges(data=True))[:50]:
        assert isinstance(d["travel_time"], float)
        assert isinstance(d["length"], float)


def test_edge_geometry_is_latlng_pairs(graph, demo_edge):
    from app.graph import edge_info
    geom = edge_info(graph, demo_edge)["geometry"]
    assert len(geom) >= 2
    for lat, lng in geom:
        assert -39 < lat < -37 and 144 < lng < 146


def test_snap_is_deterministic():
    assert snap(*config.DEMO_WORK_POINT) == snap(*config.DEMO_WORK_POINT)


# ---------- AADT join ----------
@pytest.mark.skipif(not (config.DATA_DIR / "aadt_by_edge.json").exists(), reason="AADT not fetched")
def test_demo_edge_has_a_measured_volume(demo_edge):
    rec = capacity.aadt_for(demo_edge)
    assert rec is not None
    assert rec["aadt"] > 10_000, "Flemington Rd is a major arterial"
    assert rec["year"] == 2019


@pytest.mark.skipif(not (config.DATA_DIR / "aadt_by_edge.json").exists(), reason="AADT not fetched")
def test_published_direction_agrees_with_computed_bearing(graph, demo_edge):
    """Independent cross-check: our bearing rule and VicRoads' published travel direction are
    derived from completely different data and must agree."""
    from scripts.fetch_aadt import direction_bearing, angular_diff
    rec = capacity.aadt_for(demo_edge)
    published = direction_bearing(rec["direction"])
    computed = graph.edges[demo_edge].get("bearing")
    if published is None or computed is None:
        pytest.skip("no directional record")
    assert angular_diff(float(computed), published) <= config.AADT_BEARING_TOLERANCE_DEG


# ---------- work-zone geometry (draggable closure) ----------
def test_corridor_follows_one_road(graph, demo_edge):
    from app.impact.network import corridor
    span = corridor(demo_edge)
    assert len(span) >= 1
    names = {_norm(graph.edges[e].get("name")) for e, _, _ in span}
    assert len(names) == 1, "a corridor must stay on a single road"
    starts = [s for _, s, _ in span]
    assert starts == sorted(starts), "corridor must be ordered along the road"


def _norm(value):
    from app.impact.network import _norm_name
    return _norm_name(value)


def test_anchor_edge_sits_at_zero(graph, demo_edge):
    from app.impact.network import corridor
    anchor = [(s, t) for e, s, t in corridor(demo_edge) if e == demo_edge]
    assert anchor and anchor[0][0] == 0.0
    assert anchor[0][1] == pytest.approx(graph.edges[demo_edge]["length"])


def test_longer_zone_covers_more_edges(demo_edge):
    from app.impact.network import closure_span_edges
    short = closure_span_edges(demo_edge, 0, 30)
    long = closure_span_edges(demo_edge, 0, 900)
    assert len(long) > len(short)
    assert set(short) <= set(long)


def test_zone_length_is_honoured(demo_edge):
    from app.geo import haversine_m
    from app.impact.network import work_zone_geometry
    pts = work_zone_geometry(demo_edge, 0, 400)
    drawn = sum(haversine_m(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1))
    assert drawn == pytest.approx(400, rel=0.15)


def test_work_zone_is_not_wider_than_what_was_closed(demo_edge):
    """The drawn dig must never exceed the road the model actually closed."""
    from app.geo import haversine_m
    r = _impact(demo_edge, targets=[ClosureTarget.traffic_lane], length_m=100)
    def length(pts):
        return sum(haversine_m(*pts[i], *pts[i + 1]) for i in range(len(pts) - 1))
    assert length(r.work_zone_geometry) <= length(r.closed_geometry) + 1


def test_drag_within_one_bucket_reuses_the_cache(demo_edge):
    """The whole point of quantising: a drag must not mint a cache entry per pixel."""
    from app.impact.network import _routing_impact
    _impact(demo_edge, targets=[ClosureTarget.traffic_lane], length_m=100)
    before = _routing_impact.cache_info().hits
    for jitter in (98.0, 101.4, 103.9, 108.2):  # all inside the same 25 m bucket
        _impact(demo_edge, targets=[ClosureTarget.traffic_lane], length_m=jitter)
    assert _routing_impact.cache_info().hits >= before + 4


def test_severity_is_monotone_in_zone_length(demo_edge):
    short = _impact(demo_edge, targets=[ClosureTarget.traffic_lane], length_m=30)
    long = _impact(demo_edge, targets=[ClosureTarget.traffic_lane], length_m=600)
    assert long.avg_extra_min >= short.avg_extra_min


# ---------- measured volume profile ----------
def test_peak_is_directional():
    """Citybound AM peak measured 2,437 veh/h against outbound's 905 at the same hour. A single
    direction-blind peak factor would be wrong by ~2.7x."""
    aadt = 25_365
    toward = capacity.hourly_volume(aadt, "peak", toward_cbd=True)
    away = capacity.hourly_volume(aadt, "peak", toward_cbd=False)
    assert toward > 2 * away


def test_volume_profile_is_ordered():
    aadt = 25_365
    peak = capacity.hourly_volume(aadt, "peak")
    day = capacity.hourly_volume(aadt, "day")
    night = capacity.hourly_volume(aadt, "night")
    assert peak > day > night


def test_measured_night_volume_matches_scats():
    """SCATS site 4463 measured 304-382 veh/h citybound overnight, depending on the window."""
    assert 250 <= capacity.hourly_volume(25_365, "night") <= 450


def test_peak_closure_is_worse_than_offpeak(demo_edge):
    """The model should reproduce why arterial lane closures are restricted to off-peak."""
    peak = _impact(demo_edge, targets=[ClosureTarget.traffic_lane],
                   time_window=TimeWindow.custom, custom_hours=(8, 9))
    off = _impact(demo_edge, targets=[ClosureTarget.traffic_lane],
                  time_window=TimeWindow.custom, custom_hours=(10, 14))
    assert peak.avg_extra_min > off.avg_extra_min


def test_two_way_lanes_are_halved(graph):
    """OSM `lanes` counts both directions unless the way is one-way. Treating it as per-direction
    doubles the capacity of every two-way street."""
    from app.impact.network import _lanes, _is_oneway
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
        got = _lanes(graph, (u, v, k))
        assert got == (total if _is_oneway(d) else max(total // 2, 1))
        checked += 1
        if checked > 200:
            break
    assert checked > 0


def test_lanes_never_below_one(graph, demo_edge):
    from app.impact.network import _lanes
    assert _lanes(graph, demo_edge) >= 1


def test_oneway_parsing_handles_graphml_strings():
    from app.impact.network import _is_oneway
    assert _is_oneway({"oneway": True}) and _is_oneway({"oneway": "True"})
    assert not _is_oneway({"oneway": "False"}) and not _is_oneway({"oneway": None})
