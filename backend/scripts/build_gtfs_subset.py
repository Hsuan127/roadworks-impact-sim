"""Cut Victoria's GTFS static feed down to the demo area (owner: P3).

Run: python scripts/build_gtfs_subset.py path/to/feed_dir [path/to/another_feed_dir ...]
See app/data/README.md for where to download the feed and which sub-feeds to extract.
Writes app/data/gtfs/{routes,trips,shapes,stops}.txt limited to a bounding box around the demo site.
"""
import sys
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app import config  # noqa: E402  (needs the sys.path line above)

CENTER = config.DEMO_CENTER
# Cover a little more than the road graph, so transit data never runs out before roads do.
HALF_SIZE_DEG = (config.GRAPH_RADIUS_M + 500) / 111_000
OUT = BACKEND / "app" / "data" / "gtfs"


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
