"""Nearby planned works from the DTP feed, ranked by how much they share our time and place.

Display only. A permit says works MAY run in its hours, not that a crew is on site on a given night,
and lanes affected is missing on over half the records, so nothing here feeds the traffic model
(docs/research/planned-disruptions-feasibility.md). The snapshot is written by
scripts/fetch_disruptions.py; without it the endpoint says so and returns nothing.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache

from .. import config
from ..geo import point_segment_distance_m
from ..schemas import Disruption, DisruptionsRequest, DisruptionsResult, TimeWindow


@lru_cache(maxsize=1)
def load_snapshot() -> dict | None:
    path = config.DATA_DIR / "disruptions.json"
    return json.loads(path.read_text()) if path.exists() else None


def work_hours(window: TimeWindow, custom_hours: tuple[int, int] | None) -> tuple[float, float]:
    """Our daily window as clock hours from midnight; the end may pass 24 (night runs to 05:00)."""
    if window == TimeWindow.night:
        start, end = config.NIGHT_HOURS
    elif window == TimeWindow.custom and custom_hours:
        start, end = custom_hours
    else:
        return config.DAY_HOURS
    return float(start), float(end + 24 if end <= start else end)


def _local(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=None)  # already Melbourne local time


def _intersect(a0: datetime, a1: datetime, b0: datetime, b1: datetime) -> float:
    return max(0.0, (min(a1, b1) - max(a0, b0)).total_seconds() / 3600)


def overlap(d: dict, start: date, days: int, hours: tuple[float, float]) -> float:
    """Share of our working hours, over every work day, that fall inside this permit's hours.

    Shifts belong to the weekday they start on, so an overnight shift from the day before, or an
    all-day shift the day after, can still meet our window. Without published hours the whole permit
    period counts: we cannot rule the works out, so they are not hidden."""
    p0, p1 = _local(d["start"]), _local(d["end"])
    h0, h1 = hours
    shared = 0.0
    for i in range(days):
        day = datetime.combine(start + timedelta(days=i), datetime.min.time())
        w0, w1 = day + timedelta(hours=h0), day + timedelta(hours=h1)
        if d["shifts"] is None:
            shared += _intersect(w0, w1, p0, p1)
            continue
        spans = []
        for base in (day - timedelta(days=1), day, day + timedelta(days=1)):
            for s in d["shifts"]:
                if s["weekday"] == base.weekday():
                    s0 = max(base + timedelta(hours=s["start_h"]), p0)
                    s1 = min(base + timedelta(hours=s["start_h"] + s["hours"]), p1)
                    if s1 > s0:
                        spans.append((s0, s1))
        # Shifts can overlap each other (several recurrences): merge before measuring.
        spans.sort()
        merged: list[list[datetime]] = []
        for s0, s1 in spans:
            if merged and s0 <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], s1)
            else:
                merged.append([s0, s1])
        shared += sum(_intersect(w0, w1, s0, s1) for s0, s1 in merged)
    return min(1.0, shared / (days * (h1 - h0)))


def distance_m(d: dict, works: list[tuple[float, float]]) -> float:
    best = float("inf")
    for line in d["lines"]:
        for a, b in zip(line, line[1:]):
            for lat, lng in works:
                best = min(best, point_segment_distance_m(lat, lng, tuple(a), tuple(b)))
    return best


def level(ov: float, relevance: float) -> int:
    if ov <= 0:
        return 0
    return 3 if relevance >= 0.5 else 2 if relevance >= 0.2 else 1


def nearby_disruptions(req: DisruptionsRequest) -> DisruptionsResult:
    snap = load_snapshot()
    if snap is None:
        return DisruptionsResult(available=False, fetched_at=None, source=None, disruptions=[])
    hours = work_hours(req.time_window, req.custom_hours)
    out = []
    for d in snap["disruptions"]:
        dist = distance_m(d, req.works)
        if dist > config.DISRUPTION_RADIUS_M:
            continue
        ov = overlap(d, req.start_date, req.duration_days, hours)
        rel = ov / (1 + dist / config.DISRUPTION_HALF_M)
        out.append(Disruption(**d, distance_m=round(dist), overlap=round(ov, 3), relevance=round(rel, 3),
                              level=level(ov, rel)))
    out.sort(key=lambda x: (-x.relevance, x.distance_m))
    return DisruptionsResult(available=True, fetched_at=snap["fetched_at"], source=snap["source"], disruptions=out)
