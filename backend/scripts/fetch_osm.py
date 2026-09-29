"""Fetch the drive/walk networks and sensitive facilities around the demo site (owner: P2).

Run once, then commit the outputs so the demo never depends on a live Overpass call:

    pip install -r requirements-data.txt
    python scripts/fetch_osm.py

osmnx is needed ONLY here. The API reads the saved graphml with plain networkx (see app/graph.py),
so nobody running the backend needs osmnx or geopandas installed.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import osmnx as ox

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402

OUT = Path(__file__).resolve().parents[1] / "app" / "data"

FACILITY_TAGS = {
    "amenity": ["hospital", "school", "fire_station", "kindergarten"],
    "emergency": "ambulance_station",
}

# osmnx 2.0 removed the top-level aliases: the speed helpers moved into ox.routing
# (deprecated in 1.9.2, removed in 2.0.0). Resolve both ways so the script runs on either.
_add_speeds = getattr(ox.routing, "add_edge_speeds", None) or ox.add_edge_speeds
_add_times = getattr(ox.routing, "add_edge_travel_times", None) or ox.add_edge_travel_times
_add_bearings = getattr(ox.bearing, "add_edge_bearings", None) or ox.add_edge_bearings


def fetch_drive(center: tuple[float, float], radius_m: int):
    """Drive graph with speeds, travel times and per-edge bearings baked in.

    Bearings are computed HERE, where osmnx is available, so the runtime never has to derive
    them: P2's citybound/outbound resolution and the AADT direction join both just read the
    `bearing` edge attribute.
    """
    G = ox.graph_from_point(center, dist=radius_m, network_type="drive")
    G = _add_speeds(G)
    G = _add_times(G)
    G = _add_bearings(G)
    return G


def fetch_walk(center: tuple[float, float], radius_m: int):
    """Walk graph for pedestrian detours. Denser than the drive network, hence a tighter radius."""
    return ox.graph_from_point(center, dist=radius_m, network_type="walk")


def fetch_facilities(center: tuple[float, float], radius_m: int) -> list[dict]:
    gdf = ox.features_from_point(center, tags=FACILITY_TAGS, dist=radius_m)
    seen, facilities = set(), []
    for _, row in gdf.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        # .centroid on a geographic CRS warns; projecting one point per feature is not worth it,
        # and a few metres of error is irrelevant against FACILITY_ALERT_RADIUS_M = 200.
        c = geom.centroid
        kind = row.get("amenity") if isinstance(row.get("amenity"), str) else row.get("emergency")
        if not isinstance(kind, str):
            continue
        name = row.get("name") if isinstance(row.get("name"), str) else kind
        key = (name, round(c.y, 5), round(c.x, 5))
        if key in seen:  # a hospital mapped as both a node and a building would appear twice
            continue
        seen.add(key)
        facilities.append({"name": name, "kind": kind, "lat": c.y, "lng": c.x})
    return facilities


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lat", type=float, default=config.DEMO_CENTER[0])
    ap.add_argument("--lng", type=float, default=config.DEMO_CENTER[1])
    ap.add_argument("--radius", type=int, default=config.GRAPH_RADIUS_M)
    ap.add_argument("--walk-radius", type=int, default=config.WALK_RADIUS_M)
    args = ap.parse_args()
    center = (args.lat, args.lng)

    OUT.mkdir(parents=True, exist_ok=True)

    print(f"drive network: {args.radius} m around {center} ...")
    drive = fetch_drive(center, args.radius)
    ox.save_graphml(drive, OUT / "graph_drive.graphml")

    print(f"walk network: {args.walk_radius} m ...")
    walk = fetch_walk(center, args.walk_radius)
    ox.save_graphml(walk, OUT / "graph_walk.graphml")

    print("facilities ...")
    facilities = fetch_facilities(center, args.radius)
    (OUT / "facilities.json").write_text(json.dumps(facilities, indent=2))

    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "osmnx_version": ox.__version__,
        "center": {"lat": center[0], "lng": center[1]},
        "drive_radius_m": args.radius,
        "walk_radius_m": args.walk_radius,
        "drive_nodes": drive.number_of_nodes(),
        "drive_edges": drive.number_of_edges(),
        "walk_nodes": walk.number_of_nodes(),
        "walk_edges": walk.number_of_edges(),
        "source": "OpenStreetMap contributors, ODbL",
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2))

    print(
        f"saved drive {meta['drive_nodes']} nodes / {meta['drive_edges']} edges, "
        f"walk {meta['walk_nodes']} nodes / {meta['walk_edges']} edges, "
        f"{len(facilities)} facilities to {OUT}"
    )


if __name__ == "__main__":
    main()
