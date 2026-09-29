"""Join VicRoads Annual Average Daily Traffic volumes onto our OSM edges (owner: P2).

    python scripts/fetch_aadt.py            # download, clip, join
    python scripts/fetch_aadt.py --offline  # reuse app/data/aadt_raw.geojson

Writes app/data/aadt_by_edge.json: {"u,v,k": {aadt, heavy, year, ...}}.

Source: Historical Annual Average Daily Traffic Volume, Department of Transport and Planning,
CC BY 4.0. 2019 is the newest year published; every later Victorian volume dataset either does not
cover this site (TIRTL nearest 3.6 km, Telemetry 17.6 km) or cannot be geolocated from open data
(SCATS publishes no site-location table). Checked 2026-09-29.

Only arterial ("declared") roads are in this dataset, so most residential detour streets will have
no match. That is the truth and the UI shows nothing rather than a zero.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from pathlib import Path

from shapely.geometry import shape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402
from app.geo import haversine_m  # noqa: E402
from app.graph import edge_info, load_graph  # noqa: E402

YEAR = 2019
URL = (
    "https://opendata.transport.vic.gov.au/dataset/26fafd1a-8d59-4da0-93cd-29f371147d8f/"
    "resource/425799c9-658c-41cf-b9b0-6c9a145856cf/download/yearly_aadt_volume_2019.geojson"
)
OUT = Path(__file__).resolve().parents[1] / "app" / "data"
RAW = OUT / "aadt_raw.geojson"

# 'SOUTH EAST BOUND' -> 135. Eight values, exactly matching OSM-style compass bearings.
COMPASS = {
    "NORTH": 0, "NORTH EAST": 45, "EAST": 90, "SOUTH EAST": 135,
    "SOUTH": 180, "SOUTH WEST": 225, "WEST": 270, "NORTH WEST": 315,
}
SUFFIX = {
    "ROAD": "RD", "STREET": "ST", "AVENUE": "AVE", "PARADE": "PDE", "HIGHWAY": "HWY",
    "DRIVE": "DR", "COURT": "CT", "CRESCENT": "CR", "BOULEVARD": "BLVD", "TERRACE": "TCE",
    "PLACE": "PL", "LANE": "LA", "FREEWAY": "FWY", "ESPLANADE": "ESP",
}


def normalise_name(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    if not isinstance(value, str):
        return None
    words = [w for w in "".join(c if c.isalnum() or c.isspace() else " " for c in value).upper().split() if w]
    if not words:
        return None
    words[-1] = SUFFIX.get(words[-1], words[-1])
    return " ".join(words)


def direction_bearing(value) -> float | None:
    if not isinstance(value, str):
        return None
    words = value.upper().replace("BOUND", " ").split()
    return COMPASS.get(" ".join(words))


def angular_diff(a: float, b: float) -> float:
    return abs((a - b + 180) % 360 - 180)


def download() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    print(f"downloading {YEAR} AADT ...")
    with urllib.request.urlopen(URL, timeout=600) as r, RAW.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    print(f"  {RAW.stat().st_size / 1e6:.1f} MB")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--offline", action="store_true", help="reuse the already-downloaded raw file")
    args = ap.parse_args()

    if not args.offline or not RAW.exists():
        download()

    G = load_graph()
    lats = [d["y"] for _, d in G.nodes(data=True)]
    lngs = [d["x"] for _, d in G.nodes(data=True)]
    pad = 0.01
    box = (min(lats) - pad, max(lats) + pad, min(lngs) - pad, max(lngs) + pad)

    print("reading and clipping ...")
    features = json.loads(RAW.read_text())["features"]
    by_name: dict[str, list[dict]] = {}
    kept = 0
    for f in features:
        geom = shape(f["geometry"])
        clat, clng = geom.centroid.y, geom.centroid.x
        if not (box[0] <= clat <= box[1] and box[2] <= clng <= box[3]):
            continue
        p = f["properties"]
        name = normalise_name(p.get("Road Name"))
        if name is None:
            continue
        by_name.setdefault(name, []).append({
            "geom": geom,
            "bearing": direction_bearing(p.get("Travel Direction")),
            "aadt": int(p.get("Average Annual Daily Traffic Volume") or 0),
            "heavy": int(p.get("Average Annual Daily Heavy Vehicle Volume") or 0),
            "direction": p.get("Travel Direction"),
            "section": p.get("Road Section Description"),
            "method": p.get("Calculation Methodology"),
        })
        kept += 1
    print(f"  {kept} segments in the study area, {len(by_name)} distinct road names")

    # Degrees -> metres at this latitude, so the shapely distance can be compared to a tolerance.
    mid_lat = (box[0] + box[1]) / 2
    deg_to_m_lat = 110_540.0
    deg_to_m_lng = 111_320.0 * math.cos(math.radians(mid_lat))

    print("joining to OSM edges ...")
    out: dict[str, dict] = {}
    misses = 0
    for u, v, k, d in G.edges(keys=True, data=True):
        name = normalise_name(d.get("name"))
        if name is None or name not in by_name:
            continue
        pts = edge_info(G, (u, v, k))["geometry"]
        mlat, mlng = (pts[0][0] + pts[-1][0]) / 2, (pts[0][1] + pts[-1][1]) / 2
        bearing = d.get("bearing")

        best, best_score = None, -1.0
        for cand in by_name[name]:
            dx = (cand["geom"].distance(_point(mlng, mlat)))
            dist_m = dx * math.hypot(deg_to_m_lng, deg_to_m_lat) / math.sqrt(2)
            if dist_m > config.AADT_MATCH_RADIUS_M:
                continue
            ang = None
            if bearing is not None and cand["bearing"] is not None:
                ang = angular_diff(float(bearing), cand["bearing"])
                if ang > config.AADT_BEARING_TOLERANCE_DEG:
                    continue
            score = 0.6 * (1 - dist_m / config.AADT_MATCH_RADIUS_M)
            score += 0.4 * (1 - (ang or 0) / config.AADT_BEARING_TOLERANCE_DEG)
            if score > best_score:
                best, best_score = cand, score
        if best is None:
            misses += 1
            continue
        out[f"{u},{v},{k}"] = {
            "aadt": best["aadt"],
            "heavy": best["heavy"],
            "year": YEAR,
            "direction": best["direction"],
            "both_directions": best["bearing"] is None,
            "section": best["section"],
            "method": best["method"],
            "match_confidence": round(best_score, 3),
            "source": f"VicRoads yearly AADT volume {YEAR} (CC BY 4.0)",
        }

    (OUT / "aadt_by_edge.json").write_text(json.dumps(out, indent=1))
    print(f"matched {len(out)} edges ({misses} named-but-unmatched) -> {OUT / 'aadt_by_edge.json'}")


def _point(x, y):
    from shapely.geometry import Point
    return Point(x, y)


if __name__ == "__main__":
    main()
