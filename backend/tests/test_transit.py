"""Public transport impact (owner: P3).

The GTFS subset is not committed (see app/data/README.md), so anything that needs real
routes is skipped when it is missing, rather than failing on a machine that never built it.
"""
import pytest

from app.impact.transit import ROUTE_TYPE_MODE, _route_order, is_demo, load_transit

needs_gtfs = pytest.mark.skipif(is_demo(), reason="no GTFS subset; see app/data/README.md")


def test_extended_route_types_are_mapped():
    """PTV publishes the extended (HVT) route types, not only the basic 0-7 set."""
    assert ROUTE_TYPE_MODE[0] == "tram"
    assert ROUTE_TYPE_MODE[3] == "bus"
    assert ROUTE_TYPE_MODE[400] == "train"  # Urban Railway Service: every metro train line
    assert ROUTE_TYPE_MODE[701] == "bus"  # Regional Bus Service


def test_route_order_puts_numbers_before_names():
    """Plain sorted() would read '402' as less than '57' and bury the train lines."""
    names = ["Upfield", "402", "57", "City Circle", "5"]
    assert sorted(names, key=_route_order) == ["5", "57", "402", "City Circle", "Upfield"]


@needs_gtfs
def test_every_real_route_gets_a_mode():
    routes, _ = load_transit()
    assert routes, "subset is present but loaded no routes"
    unmapped = sorted({r.short_name for r in routes if r.mode == "other"})
    assert not unmapped, f"route_type not in ROUTE_TYPE_MODE for: {unmapped}"


@needs_gtfs
def test_most_stops_know_which_routes_serve_them():
    """stop_routes.txt comes from stop_times.txt; a few feed orphans have no trips at all."""
    _, stops = load_transit()
    covered = sum(1 for s in stops if s.route_ids)
    assert covered / len(stops) > 0.8, f"only {covered}/{len(stops)} stops mapped to a route"


@needs_gtfs
def test_stops_are_boarding_locations_only():
    """location_type 1-4 are stations, entrances and pathway nodes; they never carry trips."""
    _, stops = load_transit()
    assert len({s.name for s in stops}) < len(stops), "expected both directions of some stops"
    assert not [s for s in stops if "Railway Station" in s.name and not s.route_ids], (
        "station buildings should have been filtered out of the subset"
    )
