"""Elevation profile matcher for comparing routes."""

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

import httpx

from run_mapper.core.elevation import get_elevations, calculate_elevation_metrics
from run_mapper.core.route_finder import get_route_distance_km, interpolate_route
from run_mapper.models.schemas import RouteResult


@dataclass
class RouteWithElevation:
    """A route with computed elevation data."""

    coordinates: List[Tuple[float, float]]
    distance_km: float
    elevations: List[float]
    elevation_gain_m: float
    elevation_loss_m: float
    min_elevation_m: float
    max_elevation_m: float
    profile: List[List[float]]


async def enrich_routes_with_elevation(
    routes: List[List[Tuple[float, float]]],
    client: Optional[httpx.AsyncClient] = None,
) -> List[RouteWithElevation]:
    """Add elevation data to a list of routes.

    Args:
        routes: List of routes, each as a list of (lat, lon) coordinates
        client: Optional httpx client to reuse

    Returns:
        List of RouteWithElevation objects
    """
    should_close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=60.0)

    try:
        enriched_routes = []

        for route_coords in routes:
            # Interpolate route for more accurate elevation data
            interpolated = interpolate_route(route_coords, interval_m=100.0)

            # Get elevations
            elevations = await get_elevations(interpolated, client)

            # Calculate distance
            distance_km = get_route_distance_km(interpolated)

            # Calculate metrics
            metrics = calculate_elevation_metrics(elevations)

            # Build elevation profile
            profile = _build_profile(interpolated, elevations)

            enriched_routes.append(
                RouteWithElevation(
                    coordinates=list(interpolated),
                    distance_km=round(distance_km, 3),
                    elevations=elevations,
                    elevation_gain_m=metrics["elevation_gain_m"],
                    elevation_loss_m=metrics["elevation_loss_m"],
                    min_elevation_m=metrics["min_elevation_m"],
                    max_elevation_m=metrics["max_elevation_m"],
                    profile=profile,
                )
            )

        return enriched_routes
    finally:
        if should_close_client:
            await client.aclose()


def _build_profile(
    coordinates: Sequence[Tuple[float, float]],
    elevations: Sequence[float],
) -> List[List[float]]:
    """Build an elevation profile from coordinates and elevations.

    Args:
        coordinates: List of (lat, lon) coordinates
        elevations: List of elevation values

    Returns:
        Profile as [[km, elevation_m], ...]
    """
    from run_mapper.core.gpx_parser import haversine_distance

    profile = []
    cumulative_distance = 0.0

    for i, (coord, elev) in enumerate(zip(coordinates, elevations)):
        if i > 0:
            lat1, lon1 = coordinates[i - 1]
            lat2, lon2 = coord
            cumulative_distance += haversine_distance(lat1, lon1, lat2, lon2)

        profile.append([round(cumulative_distance, 3), round(elev, 1)])

    return profile


def score_route(
    route: RouteWithElevation,
    target_distance_km: float,
    target_elevation_gain_m: float,
) -> float:
    """Calculate a similarity score for a route.

    Args:
        route: Route with elevation data
        target_distance_km: Target distance in kilometers
        target_elevation_gain_m: Target elevation gain in meters

    Returns:
        Similarity score between 0 and 1 (1 = perfect match)
    """
    # Distance similarity (penalize deviation)
    distance_diff = abs(route.distance_km - target_distance_km)
    distance_score = max(0, 1 - (distance_diff / target_distance_km))

    # Elevation gain similarity
    if target_elevation_gain_m > 0:
        gain_diff = abs(route.elevation_gain_m - target_elevation_gain_m)
        gain_score = max(0, 1 - (gain_diff / target_elevation_gain_m))
    else:
        # If target is flat, penalize any significant elevation
        gain_score = max(0, 1 - (route.elevation_gain_m / 100))

    # Combined score (weighted average)
    # Distance is slightly more important
    score = 0.4 * distance_score + 0.6 * gain_score

    return round(score, 3)


def rank_routes(
    routes: List[RouteWithElevation],
    target_distance_km: float,
    target_elevation_gain_m: float,
    num_results: int = 5,
) -> List[Tuple[RouteWithElevation, float]]:
    """Rank routes by similarity to target metrics.

    Args:
        routes: List of routes with elevation data
        target_distance_km: Target distance in kilometers
        target_elevation_gain_m: Target elevation gain in meters
        num_results: Number of top results to return

    Returns:
        List of (route, score) tuples, sorted by score descending
    """
    scored_routes = [
        (route, score_route(route, target_distance_km, target_elevation_gain_m))
        for route in routes
    ]

    # Sort by score descending
    scored_routes.sort(key=lambda x: x[1], reverse=True)

    return scored_routes[:num_results]


def routes_to_results(
    ranked_routes: List[Tuple[RouteWithElevation, float]],
) -> List[RouteResult]:
    """Convert ranked routes to API response format.

    Args:
        ranked_routes: List of (route, score) tuples

    Returns:
        List of RouteResult objects
    """
    results = []

    for i, (route, score) in enumerate(ranked_routes, start=1):
        results.append(
            RouteResult(
                name=f"Route {i}",
                distance_km=route.distance_km,
                elevation_gain_m=route.elevation_gain_m,
                elevation_loss_m=route.elevation_loss_m,
                similarity_score=score,
                coordinates=[[lat, lon] for lat, lon in route.coordinates],
                profile=route.profile,
            )
        )

    return results


def profile_correlation(
    profile1: Sequence[Sequence[float]],
    profile2: Sequence[Sequence[float]],
) -> float:
    """Calculate correlation between two elevation profiles.

    This normalizes both profiles to the same length and computes
    Pearson correlation coefficient.

    Args:
        profile1: First profile as [[km, elevation], ...]
        profile2: Second profile as [[km, elevation], ...]

    Returns:
        Correlation coefficient between -1 and 1
    """
    from run_mapper.core.gpx_parser import simplify_profile

    # Normalize to same number of points
    num_points = 50
    p1 = simplify_profile(list(profile1), num_points)
    p2 = simplify_profile(list(profile2), num_points)

    if len(p1) < 2 or len(p2) < 2:
        return 0.0

    # Extract elevations
    e1 = [p[1] for p in p1]
    e2 = [p[1] for p in p2]

    # Calculate means
    mean1 = sum(e1) / len(e1)
    mean2 = sum(e2) / len(e2)

    # Calculate correlation
    numerator = sum((a - mean1) * (b - mean2) for a, b in zip(e1, e2))
    denom1 = sum((a - mean1) ** 2 for a in e1) ** 0.5
    denom2 = sum((b - mean2) ** 2 for b in e2) ** 0.5

    if denom1 == 0 or denom2 == 0:
        return 0.0

    return numerator / (denom1 * denom2)
