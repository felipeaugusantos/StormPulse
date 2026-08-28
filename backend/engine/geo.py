"""Great-circle geometry helpers (pure math, no dependencies).

All angles in degrees, distances in kilometres, WGS84 sphere approximation.
Coordinate order in signatures is (lat, lon) to match the rest of the app;
remember PostGIS stores points as (lon, lat).
"""

from __future__ import annotations

import math

EARTH_RADIUS_KM = 6371.0088

# Portuguese compass points, 8-wind.
_COMPASS_PT = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in kilometres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Initial bearing from point 1 to point 2, degrees clockwise from North [0,360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)
    x = math.sin(dlambda) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlambda)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def destination_point(
    lat: float, lon: float, bearing: float, distance_km: float
) -> tuple[float, float]:
    """Project a point a given distance along a bearing. Returns (lat, lon)."""
    ang = distance_km / EARTH_RADIUS_KM
    br = math.radians(bearing)
    p1 = math.radians(lat)
    l1 = math.radians(lon)
    p2 = math.asin(math.sin(p1) * math.cos(ang) + math.cos(p1) * math.sin(ang) * math.cos(br))
    l2 = l1 + math.atan2(
        math.sin(br) * math.sin(ang) * math.cos(p1),
        math.cos(ang) - math.sin(p1) * math.sin(p2),
    )
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0


def compass_label(bearing: float) -> str:
    """8-wind Portuguese compass label for a bearing in degrees."""
    idx = int((bearing % 360.0) / 45.0 + 0.5) % 8
    return _COMPASS_PT[idx]


def angle_difference(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, in [0, 180]."""
    diff = abs((a - b) % 360.0)
    return min(diff, 360.0 - diff)


def polygon_area_km2(ring: list[tuple[float, float]]) -> float:
    """Area enclosed by a polygon ring of (lat, lon) points, in km².

    Projects to a local equirectangular plane centered on the ring's own
    mean latitude, then applies the shoelace formula — accurate for
    field-sized polygons (talhões are hundreds of metres to a few km
    across). The alternative (spherical excess, exact on a sphere at any
    scale) is actually *less* numerically stable here: it subtracts
    near-equal large numbers for a small polygon, which is exactly the
    scale this function is for. Same "no reprojection library needed"
    reasoning already used for NDVI's pixel sizing
    (``app/ndvi/sentinel_hub.py``).
    """
    if len(ring) < 3:
        return 0.0
    mean_lat = sum(lat for lat, _lon in ring) / len(ring)
    cos_mean_lat = math.cos(math.radians(mean_lat))
    km_per_deg_lat = math.radians(1.0) * EARTH_RADIUS_KM
    points_km = [(lon * km_per_deg_lat * cos_mean_lat, lat * km_per_deg_lat) for lat, lon in ring]
    n = len(points_km)
    signed_area = 0.0
    for i in range(n):
        x1, y1 = points_km[i]
        x2, y2 = points_km[(i + 1) % n]
        signed_area += x1 * y2 - x2 * y1
    return abs(signed_area) / 2.0
