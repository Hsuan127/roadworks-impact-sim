"""Cut Victoria's GTFS static feed down to the demo area (owner: P3).

TODO(P3):
1. Download the GTFS schedule zip from the Victorian open data portal (Transport Victoria).
   The zip contains one sub-feed per mode (tram, metro bus, train...); extract the ones needed.
2. Run: python scripts/build_gtfs_subset.py path/to/feed_dir [path/to/another_feed_dir ...]
Writes app/data/gtfs/{routes,trips,shapes,stops}.txt limited to a bounding box around the demo site.
"""
import sys
from pathlib import Path

import pandas as pd

CENTER = (-37.7938, 144.9467)
HALF_SIZE_DEG = 0.02  # ~2 km
OUT = Path(__file__).resolve().parents[1] / "app" / "data" / "gtfs"


def in_box(lat, lng):
    return (abs(lat - CENTER[0]) <= HALF_SIZE_DEG) & (abs(lng - CENTER[1]) <= HALF_SIZE_DEG)


def main(feed_dirs):
    OUT.mkdir(parents=True, exist_ok=True)
    routes, trips, shapes, stops = [], [], [], []
    for d in map(Path, feed_dirs):
        st = pd.read_csv(d / "stops.txt", dtype={"stop_id": str})
        sh = pd.read_csv(d / "shapes.txt", dtype={"shape_id": str})
        tr = pd.read_csv(d / "trips.txt", dtype=str)
        ro = pd.read_csv(d / "routes.txt", dtype=str)
        keep_shapes = set(sh.loc[in_box(sh.shape_pt_lat, sh.shape_pt_lon), "shape_id"])
        tr = tr[tr.shape_id.isin(keep_shapes)]
        stops.append(st[in_box(st.stop_lat, st.stop_lon)])
        shapes.append(sh[sh.shape_id.isin(keep_shapes)])
        trips.append(tr[["route_id", "shape_id"]].drop_duplicates())
        routes.append(ro[ro.route_id.isin(set(tr.route_id))])
    for name, frames in [("routes", routes), ("trips", trips), ("shapes", shapes), ("stops", stops)]:
        pd.concat(frames).to_csv(OUT / f"{name}.txt", index=False)
    print(f"Wrote GTFS subset to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
