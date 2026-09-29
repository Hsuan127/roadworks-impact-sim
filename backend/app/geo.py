import math

EARTH_R = 6_371_000.0


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def point_segment_distance_m(lat: float, lng: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    """Distance from a point to segment a-b (lat, lng pairs), using a local equirectangular projection."""
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 110_540
    px, py = 0.0, 0.0
    ax, ay = (a[1] - lng) * kx, (a[0] - lat) * ky
    bx, by = (b[1] - lng) * kx, (b[0] - lat) * ky
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax - px, ay - py)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(ax + t * dx - px, ay + t * dy - py)


def meters_to_degrees(m: float) -> float:
    """Rough conversion for buffers at Melbourne's latitude (good enough for 10-500 m)."""
    return m / 111_000.0
