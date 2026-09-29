"""Fetch the drive network and sensitive facilities around the demo site (owner: P2).

TODO(P2): run once before the hackathon (needs internet + requirements-data.txt).
    pip install -r requirements-data.txt
    python scripts/fetch_osm.py
"""
import json
from pathlib import Path

import osmnx as ox

CENTER = (-37.7938, 144.9467)  # Flemington Rd x Racecourse Rd, approximate
RADIUS_M = 1500
OUT = Path(__file__).resolve().parents[1] / "app" / "data"


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    G = ox.graph_from_point(CENTER, dist=RADIUS_M, network_type="drive")
    G = ox.add_edge_speeds(G)
    G = ox.add_edge_travel_times(G)
    ox.save_graphml(G, OUT / "graph_drive.graphml")

    tags = {"amenity": ["hospital", "school", "fire_station", "kindergarten"], "emergency": "ambulance_station"}
    gdf = ox.features_from_point(CENTER, tags=tags, dist=RADIUS_M)
    facilities = []
    for _, row in gdf.iterrows():
        c = row.geometry.centroid
        kind = row.get("amenity") if isinstance(row.get("amenity"), str) else row.get("emergency")
        facilities.append({"name": row.get("name") if isinstance(row.get("name"), str) else kind,
                           "kind": kind, "lat": c.y, "lng": c.x})
    (OUT / "facilities.json").write_text(json.dumps(facilities, indent=2))
    print(f"Saved {len(G.edges)} edges and {len(facilities)} facilities to {OUT}")


if __name__ == "__main__":
    main()
