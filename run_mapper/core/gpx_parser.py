"""GPX file parser for extracting elevation profiles."""

from typing import List, Union

import gpxpy
import gpxpy.gpx
from math import radians, sin, cos, sqrt, atan2

from run_mapper.models.schemas import ElevationProfile


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the distance between two points on Earth using the Haversine formula.

    Args:
        lat1: Latitude of first point in degrees
        lon1: Longitude of first point in degrees
        lat2: Latitude of second point in degrees
        lon2: Longitude of second point in degrees

    Returns:
        Distance in kilometers
    """
    R = 6371  # Earth's radius in kilometers

    lat1_rad = radians(lat1)
    lat2_rad = radians(lat2)
    delta_lat = radians(lat2 - lat1)
    delta_lon = radians(lon2 - lon1)

    a = sin(delta_lat / 2) ** 2 + cos(lat1_rad) * cos(lat2_rad) * sin(delta_lon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))

    return R * c


def parse_gpx(gpx_content: Union[str, bytes]) -> ElevationProfile:
    """Parse a GPX file and extract the elevation profile.

    Args:
        gpx_content: GPX file content as string or bytes

    Returns:
        ElevationProfile with distance, elevation metrics, and profile data

    Raises:
        ValueError: If the GPX file is invalid or contains no elevation data
    """
    if isinstance(gpx_content, bytes):
        gpx_content = gpx_content.decode("utf-8")

    gpx = gpxpy.parse(gpx_content)

    points: List[tuple] = []  # (lat, lon, elevation, cumulative_distance)
    cumulative_distance = 0.0

    for track in gpx.tracks:
        for segment in track.segments:
            for i, point in enumerate(segment.points):
                if point.elevation is None:
                    continue

                if points:
                    prev_lat, prev_lon, _, _ = points[-1]
                    distance = haversine_distance(prev_lat, prev_lon, point.latitude, point.longitude)
                    cumulative_distance += distance

                points.append((point.latitude, point.longitude, point.elevation, cumulative_distance))

    # Also check routes (some GPX files use routes instead of tracks)
    for route in gpx.routes:
        for i, point in enumerate(route.points):
            if point.elevation is None:
                continue

            if points:
                prev_lat, prev_lon, _, _ = points[-1]
                distance = haversine_distance(prev_lat, prev_lon, point.latitude, point.longitude)
                cumulative_distance += distance

            points.append((point.latitude, point.longitude, point.elevation, cumulative_distance))

    if not points:
        raise ValueError("GPX file contains no points with elevation data")

    # Calculate elevation metrics
    elevations = [p[2] for p in points]
    elevation_gain = 0.0
    elevation_loss = 0.0

    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i - 1]
        if diff > 0:
            elevation_gain += diff
        else:
            elevation_loss += abs(diff)

    # Create profile data: [[km, elevation_m], ...]
    profile = [[round(p[3], 3), round(p[2], 1)] for p in points]

    return ElevationProfile(
        distance_km=round(cumulative_distance, 3),
        elevation_gain_m=round(elevation_gain, 1),
        elevation_loss_m=round(elevation_loss, 1),
        min_elevation_m=round(min(elevations), 1),
        max_elevation_m=round(max(elevations), 1),
        profile=profile,
    )


def simplify_profile(profile: List[List[float]], num_points: int = 100) -> List[List[float]]:
    """Simplify an elevation profile to a fixed number of points.

    This is useful for comparing profiles of different lengths.

    Args:
        profile: Original profile as [[km, elevation_m], ...]
        num_points: Target number of points

    Returns:
        Simplified profile with num_points evenly spaced samples
    """
    if len(profile) <= num_points:
        return profile

    if not profile:
        return []

    total_distance = profile[-1][0]
    step = total_distance / (num_points - 1)

    simplified = []
    profile_idx = 0

    for i in range(num_points):
        target_distance = i * step

        # Find the surrounding points for interpolation
        while profile_idx < len(profile) - 1 and profile[profile_idx + 1][0] < target_distance:
            profile_idx += 1

        if profile_idx >= len(profile) - 1:
            simplified.append([round(target_distance, 3), profile[-1][1]])
        else:
            # Linear interpolation
            d1, e1 = profile[profile_idx]
            d2, e2 = profile[profile_idx + 1]

            if d2 - d1 > 0:
                ratio = (target_distance - d1) / (d2 - d1)
                elevation = e1 + ratio * (e2 - e1)
            else:
                elevation = e1

            simplified.append([round(target_distance, 3), round(elevation, 1)])

    return simplified
