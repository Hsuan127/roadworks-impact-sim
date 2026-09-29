"""Cut Victoria's GTFS static feed down to the demo area (owner: P3).

Run: python scripts/build_gtfs_subset.py path/to/feed_dir [path/to/another_feed_dir ...]
See app/data/README.md for where to download the feed and which sub-feeds to extract.
Writes app/data/gtfs/{routes,trips,shapes,stops,stop_routes}.txt limited to a box around the demo site.
"""
import math
import sys
from pathlib import Path

import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
from app import config  # noqa: E402  (needs the sys.path line above)

CENTER = config.DEMO_CENTER
# Cover a little more than the routed study area, so transit data never runs out before
# roads do. A degree of longitude is shorter than one of latitude, so they differ.
_HALF_M = config.STUDY_RADIUS_M + 500
HALF_LAT_DEG = _HALF_M / 111_132.0
HALF_LNG_DEG = _HALF_M / (111_320.0 * math.cos(math.radians(CENTER[0])))
OUT = BACKEND / "app" / "data" / "gtfs"


def in_box(lat, lng):
    return (abs(lat - CENTER[0]) <= HALF_LAT_DEG) & (abs(lng - CENTER[1]) <= HALF_LNG_DEG)


def stop_routes_for(feed_dir, kept_trips):
    """Which routes serve each stop, for the trips we kept.

    stop_times.txt is by far the biggest file in a GTFS feed -- 915 MB for metro bus --
    so stream it in chunks and drop each chunk as soon as the filter has run.
    """
    wanted = dict(zip(kept_trips.trip_id, kept_trips.route_id))
    out = []
    for chunk in pd.read_csv(feed_dir / "stop_times.txt", dtype=str,
                             usecols=["trip_id", "stop_id"], chunksize=500_000):
        chunk = chunk[chunk.trip_id.isin(wanted)]
        if not chunk.empty:
            out.append(chunk.assign(route_id=chunk.trip_id.map(wanted))[["stop_id", "route_id"]])
    if not out:
        return pd.DataFrame(columns=["stop_id", "route_id"])
    return pd.concat(out).drop_duplicates()


def main(feed_dirs):
    OUT.mkdir(parents=True, exist_ok=True)
    routes, trips, shapes, stops, stop_routes = [], [], [], [], []
    for d in map(Path, feed_dirs):
        st = pd.read_csv(d / "stops.txt", dtype={"stop_id": str})
        sh = pd.read_csv(d / "shapes.txt", dtype={"shape_id": str})
        tr = pd.read_csv(d / "trips.txt", dtype=str)
        ro = pd.read_csv(d / "routes.txt", dtype=str)
        keep_shapes = set(sh.loc[in_box(sh.shape_pt_lat, sh.shape_pt_lon), "shape_id"])
        tr = tr[tr.shape_id.isin(keep_shapes)]
        # Only location_type 0 (usually blank) is a boarding location. 1-4 are stations,
        # entrances and pathway nodes, which never appear in stop_times.txt.
        in_stops = st[st.location_type.fillna(0).astype(int).eq(0) & in_box(st.stop_lat, st.stop_lon)]

        sr = stop_routes_for(d, tr)
        stop_routes.append(sr[sr.stop_id.isin(set(in_stops.stop_id))])

        stops.append(in_stops)
        shapes.append(sh[sh.shape_id.isin(keep_shapes)])
        trips.append(tr[["route_id", "shape_id"]].drop_duplicates())
        routes.append(ro[ro.route_id.isin(set(tr.route_id))])
    for name, frames in [("routes", routes), ("trips", trips), ("shapes", shapes),
                         ("stops", stops), ("stop_routes", stop_routes)]:
        pd.concat(frames).to_csv(OUT / f"{name}.txt", index=False)
    print(f"Wrote GTFS subset to {OUT}")


if __name__ == "__main__":
    main(sys.argv[1:])
