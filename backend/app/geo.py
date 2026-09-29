import math

EARTH_R = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def project_on_segment(lat: float, lng: float, a: tuple[float, float], b: tuple[float, float]) -> tuple[float, float]:
    """(t, distance_m): where the nearest point on segment a-b lies (0 = a, 1 = b) and how far away it is.
    Uses a local equirectangular projection; points are (lat, lng)."""
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 110_540
    ax, ay = (a[1] - lng) * kx, (a[0] - lat) * ky
    bx, by = (b[1] - lng) * kx, (b[0] - lat) * ky
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return 0.0, math.hypot(ax, ay)
    t = max(0.0, min(1.0, -(ax * dx + ay * dy) / (dx * dx + dy * dy)))
    return t, math.hypot(ax + t * dx, ay + t * dy)


def point_segment_distance_m(lat: float, lng: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    return project_on_segment(lat, lng, a, b)[1]


def interpolate(a: tuple[float, float], b: tuple[float, float], t: float) -> tuple[float, float]:
    return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)


def polyline_length_m(pts: list[tuple[float, float]]) -> float:
    return sum(haversine_m(*a, *b) for a, b in zip(pts, pts[1:]))


def locate_on_polyline(pts: list[tuple[float, float]], lat: float, lng: float) -> float:
    """Distance (m) from the start of the polyline to the point on it nearest to (lat, lng)."""
    best_d, best_off, offset = math.inf, 0.0, 0.0
    for a, b in zip(pts, pts[1:]):
        seg = haversine_m(*a, *b)
        t, d = project_on_segment(lat, lng, a, b)
        if d < best_d:
            best_d, best_off = d, offset + t * seg
        offset += seg
    return best_off


def slice_polyline(pts: list[tuple[float, float]], start_m: float, end_m: float) -> list[tuple[float, float]]:
    """The part of the polyline between two distances from its start."""
    out: list[tuple[float, float]] = []
    offset = 0.0
    for a, b in zip(pts, pts[1:]):
        seg = haversine_m(*a, *b)
        lo, hi = offset, offset + seg
        offset = hi
        if seg == 0 or hi < start_m or lo > end_m:
            continue
        if not out:
            out.append(interpolate(a, b, max(0.0, (start_m - lo) / seg)))
        out.append(interpolate(a, b, min(1.0, (end_m - lo) / seg)))
    return out


def meters_to_degrees(m: float) -> float:
    """Rough conversion for buffers at Melbourne's latitude (good enough for 10-500 m)."""
    return m / 111_000.0
