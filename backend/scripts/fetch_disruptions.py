"""Feasibility spike: can DTP planned road disruptions sit on our network? (branch feature/real-time)

    VICROADS_API_KEY=... python scripts/fetch_disruptions.py   # download, clip to 3 km, report
    python scripts/fetch_disruptions.py --offline               # reuse app/data/disruptions_raw.json
    python scripts/fetch_disruptions.py --offline --start 2026-10-12 --days 3

Writes app/data/disruptions_raw.json (features within the drive graph radius of its centre, plus
fetched_at) and prints a report: counts, field completeness, time overlap with a work window, and
how well each line matches our OSM drive edges. Nothing in the app reads this yet.

Source: Planned Disruptions - Road, Department of Transport and Planning, Transport Victoria Open
Data (API key from opendata.transport.vic.gov.au). Near real time: only works already listed.
Covers DTP-managed roads, so council-road works are absent.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import config  # noqa: E402
from app.geo import haversine_m, point_segment_distance_m  # noqa: E402
from app.graph import edge_info, load_graph, snap  # noqa: E402
from fetch_aadt import normalise_name  # noqa: E402

URL = "https://api.opendata.transport.vic.gov.au/opendata/roads/disruptions/planned/v1/"
BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "app" / "data"
RAW = OUT / "disruptions_raw.json"
META = json.loads((OUT / "meta.json").read_text())
CENTRE = (META["center"]["lat"], META["center"]["lng"])
DRIVE_RADIUS_M = META["drive_radius_m"]
SAMPLE_STEP_M = 20  # points sampled along each disruption line for the edge match
MATCH_OK_M = 15
MAX_PAGES = 100  # 500 features a page
WINDOWS = {"day": (9.5, 15.5), "night": (20.0, 29.0)}  # night runs past midnight: 20:00-05:00


def api_key() -> str | None:
    if os.environ.get("VICROADS_API_KEY"):
        return os.environ["VICROADS_API_KEY"]
    env = BACKEND / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("VICROADS_API_KEY="):
                return line.split("=", 1)[1].strip() or None
    return None


def download(key: str) -> list[dict]:
    # The published OpenAPI spec says Ocp-Apim-Subscription-Key, ?format=geojson and a NextPageToken
    # query parameter. The live gateway answers 401 to that header, blocks the format parameter and
    # ignores the query token (page 2 repeats page 1). KeyID works, and the token goes in a header.
    features, seen, token = [], set(), None
    for _ in range(MAX_PAGES):
        headers = {"KeyID": key, "User-Agent": "roadworks-impact-sim", **({"NextPageToken": token} if token else {})}
        with urllib.request.urlopen(urllib.request.Request(URL, headers=headers), timeout=60) as r:
            page = json.load(r)
        new = []
        for f in page.get("features", []):  # ids repeat, even within one page
            if f["properties"].get("id") not in seen:
                seen.add(f["properties"].get("id"))
                new.append(f)
        features += new
        print(f"  page {_ + 1}: {len(new)} new, {len(features)} total", flush=True)
        nxt = page.get("nextPageDetails") or {}
        if not nxt.get("hasMoreRecords") or not new:
            return features
        token = nxt["nextPageToken"]
    sys.exit(f"Still more pages after {MAX_PAGES}; raise MAX_PAGES")


# ---------- geometry ----------
def lines(feature: dict) -> list[list[tuple[float, float]]]:
    """Every part of the geometry as a list of (lat, lng); a Point is a one-point line."""
    geom = feature.get("geometry") or {}
    parts = geom.get("geometries") or [geom]
    out = []
    for g in parts:
        c = g.get("coordinates")
        if g.get("type") == "Point":
            out.append([(c[1], c[0])])
        elif g.get("type") == "LineString":
            out.append([(y, x) for x, y in c])
        elif g.get("type") == "MultiLineString":
            out += [[(y, x) for x, y in part] for part in c]
    return out


def geom_kind(feature: dict) -> str:
    kinds = {len(p) > 1 for p in lines(feature)}
    return "line" if True in kinds else "point" if kinds else "none"


def min_dist_to_centre(feature: dict) -> float:
    return min((haversine_m(*CENTRE, *pt) for part in lines(feature) for pt in part), default=float("inf"))


def sample(part: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pts = [part[0]]
    for a, b in zip(part, part[1:]):
        n = max(1, int(haversine_m(*a, *b) // SAMPLE_STEP_M))
        pts += [(a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n) for i in range(1, n + 1)]
    return pts


def match(G, feature: dict) -> dict:
    """Snap sampled points to drive edges: offset in metres, and whether the edge names agree."""
    offsets, names, edges = [], Counter(), set()
    for part in lines(feature):
        if len(part) < 2:
            continue
        for lat, lng in sample(part):
            e = snap(lat, lng)
            info = edge_info(G, e)
            geom = info["geometry"]
            offsets.append(min(point_segment_distance_m(lat, lng, a, b) for a, b in zip(geom, geom[1:])))
            names[normalise_name(info["road_name"])] += 1
            edges.add(e)
    want = normalise_name(feature["properties"].get("closedRoadName"))
    top = names.most_common(1)[0][0] if names else None
    return {"offsets": offsets, "edges": edges, "osm_name": top, "feed_name": want,
            "name_ok": bool(want and top and (want == top or want in top or top in want))}


# ---------- time ----------
def parse_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hours(value) -> float | None:
    """'08:30', '08:30:00' or an ISO time -> 8.5; ISO durations like 'PT6H30M' -> 6.5."""
    if not isinstance(value, str):
        return None
    v = value.strip().upper()
    if v.startswith("PT"):
        total, num = 0.0, ""
        for ch in v[2:]:
            if ch.isdigit() or ch in ".-":
                num += ch
            elif ch in "HMS" and num:
                total += float(num) / {"H": 1, "M": 60, "S": 3600}[ch]
                num = ""
        return total
    if "T" in v:
        v = v.split("T", 1)[1]
    half = "PM" if v.endswith("PM") else "AM" if v.endswith("AM") else None  # the feed writes '9:30 AM'
    try:
        hh, mm = v.removesuffix(half or "").strip().split(":")[:2]
        h = int(hh) % 12 + (12 if half == "PM" else 0) if half else int(hh)
        return h + int(mm) / 60
    except ValueError:
        return None


def overlaps_hours(recurrences: list[dict] | None, window: tuple[float, float]) -> bool | None:
    """None when the feed gives no usable daily hours: we cannot tell, and say so."""
    if not recurrences:
        return None
    w0, w1 = window
    known = False
    for r in recurrences:
        if r.get("allDay"):
            return True
        s, d = hours(r.get("startTime")), hours(r.get("duration"))
        if s is None or d is None:
            continue
        if d < 0:  # the feed writes an overnight shift as end minus start: 9 PM + PT-16H = 8 h to 5 AM
            d += 24
        known = True
        for shift in (0, 24):  # a works shift that crosses midnight
            if s + shift < w1 and s + shift + d > w0:
                return True
    return False if known else None


# ---------- report ----------
def pct(n: int, total: int) -> str:
    return f"{n}/{total} ({100 * n / total:.0f}%)" if total else "0/0"


def report(features: list[dict], fetched_at: str, start: date, days: int) -> None:
    G = load_graph()
    aadt = set(json.loads((OUT / "aadt_by_edge.json").read_text()))
    n = len(features)
    print(f"Snapshot {fetched_at}: {n} features within {DRIVE_RADIUS_M} m of {CENTRE}")
    if not n:
        return
    in_study = [f for f in features if min_dist_to_centre(f) <= config.STUDY_RADIUS_M]
    print(f"  inside study area ({config.STUDY_RADIUS_M} m): {len(in_study)}")
    for key in ("status", "eventType", "eventSubtype", "rmaClass"):
        print(f"  {key}: {dict(Counter(f['properties'].get(key) for f in features))}")
    print(f"  geometry: {dict(Counter(geom_kind(f) for f in features))}")

    props = [f["properties"] for f in features]
    print("\nField completeness")
    fields = {
        "closedRoadName": lambda p: p.get("closedRoadName"),
        "duration.start": lambda p: parse_dt((p.get("duration") or {}).get("start")),
        "duration.end": lambda p: parse_dt((p.get("duration") or {}).get("end")),
        "recurrences (daily hours)": lambda p: (p.get("duration") or {}).get("recurrences"),
        "impact.direction": lambda p: (p.get("impact") or {}).get("direction"),
        "impact.numberLanesImpacted": lambda p: (p.get("impact") or {}).get("numberLanesImpacted"),
        "impact.impactType": lambda p: (p.get("impact") or {}).get("impactType"),
    }
    for name, get in fields.items():
        print(f"  {name:28s} {pct(sum(1 for p in props if get(p)), n)}")
    print("  sample values:")
    for key in ("direction", "numberLanesImpacted", "impactType"):
        vals = Counter((p.get("impact") or {}).get(key) for p in props)
        print(f"    impact.{key}: {dict(vals.most_common(6))}")
    recs = [r for p in props for r in (p.get("duration") or {}).get("recurrences") or []]
    print(f"    recurrences[0:3]: {recs[:3]}")

    starts = [s for p in props if (s := parse_dt((p.get("duration") or {}).get("start")))]
    ends = [e for p in props if (e := parse_dt((p.get("duration") or {}).get("end")))]
    if starts and ends:
        print(f"\nDate spread: starts {min(starts):%Y-%m-%d}..{max(starts):%Y-%m-%d}, "
              f"ends {min(ends):%Y-%m-%d}..{max(ends):%Y-%m-%d}")
    w_start = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    w_end = w_start + timedelta(days=days)
    print(f"Work window {start} + {days} days")
    concurrent = []
    for f in features:
        d = f["properties"].get("duration") or {}
        s, e = parse_dt(d.get("start")), parse_dt(d.get("end"))
        if s and e and s < w_end and e > w_start:
            concurrent.append(f)
    print(f"  date overlap: {len(concurrent)}")
    for label, window in WINDOWS.items():
        res = Counter(overlaps_hours((f["properties"].get("duration") or {}).get("recurrences"), window)
                      for f in concurrent)
        print(f"  {label:5s} hours overlap: yes {res[True]}, no {res[False]}, unknown {res[None]}")

    print("\nEdge match (lines only)")
    matched = [(f, match(G, f)) for f in features if geom_kind(f) == "line"]
    if not matched:
        print("  no LineString features")
        return
    all_off = sorted(o for _, m in matched for o in m["offsets"])
    good = [m for _, m in matched if m["offsets"] and statistics.median(m["offsets"]) <= MATCH_OK_M and m["name_ok"]]
    print(f"  sampled points: {len(all_off)}, median offset {statistics.median(all_off):.1f} m, "
          f"p95 {all_off[int(0.95 * (len(all_off) - 1))]:.1f} m")
    print(f"  features matched (median <= {MATCH_OK_M} m and road name agrees): {pct(len(good), len(matched))}")
    touching = sum(1 for _, m in matched if any(f"{u},{v},{k}" in aadt for u, v, k in m["edges"]))
    print(f"  features touching an AADT edge: {pct(touching, len(matched))}")
    print("  per feature:")
    for f, m in sorted(matched, key=lambda fm: -statistics.median(fm[1]["offsets"] or [0])):
        med = statistics.median(m["offsets"]) if m["offsets"] else float("nan")
        print(f"    {str(f['properties'].get('id', '?'))[:14]:14s} {med:6.1f} m  feed={m['feed_name']!s:24s} "
              f"osm={m['osm_name']!s:24s} {'ok' if m['name_ok'] else 'NAME MISMATCH'}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help=f"reuse {RAW.name}")
    ap.add_argument("--start", type=date.fromisoformat, default=date.today() + timedelta(days=14))
    ap.add_argument("--days", type=int, default=3)
    args = ap.parse_args()

    if args.offline:
        data = json.loads(RAW.read_text())
    else:
        key = api_key()
        if not key:
            sys.exit("Set VICROADS_API_KEY (environment or backend/.env). "
                     "Register at https://opendata.transport.vic.gov.au/ to get one.")
        every = download(key)
        near = [f for f in every if min_dist_to_centre(f) <= DRIVE_RADIUS_M]
        data = {"fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "source": URL,
                "total_statewide": len(every), "radius_m": DRIVE_RADIUS_M, "centre": CENTRE,
                "features": near}
        RAW.write_text(json.dumps(data, indent=1))
        print(f"Kept {len(near)} of {len(every)} statewide features -> {RAW.relative_to(BACKEND)}")
    report(data["features"], data["fetched_at"], args.start, args.days)


if __name__ == "__main__":
    main()
