"""Elevation profile matcher for comparing routes."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

from run_mapper.core.elevation import get_elevations, calculate_elevation_metrics
from run_mapper.core.route_finder import get_route_distance_km, interpolate_route
from run_mapper.models.schemas import RouteResult


@dataclass
class Hill:
    """A detected hill (climb or descent) in a profile."""
    start_km: float
    end_km: float
    start_elevation_m: float
    end_elevation_m: float

    @property
    def length_km(self) -> float:
        return self.end_km - self.start_km

    @property
    def elevation_change_m(self) -> float:
        return self.end_elevation_m - self.start_elevation_m

    @property
    def grade_percent(self) -> float:
        if self.length_km <= 0:
            return 0.0
        return (self.elevation_change_m / (self.length_km * 1000)) * 100

    @property
    def is_climb(self) -> bool:
        return self.elevation_change_m > 0


@dataclass
class ElevationAnalysis:
    """Detailed analysis of an elevation profile."""
    # Hill metrics
    hill_count: int = 0
    avg_hill_length_km: float = 0.0
    max_climb_grade: float = 0.0
    max_descent_grade: float = 0.0

    # Variability
    grade_variance: float = 0.0  # High = rolling, low = consistent
    elevation_range_m: float = 0.0

    # Position metrics (0-1 scale, 0.5 = evenly distributed)
    climb_position: float = 0.5  # <0.5 = early climbs, >0.5 = late climbs

    # Pattern classification
    pattern: str = "flat"  # "flat", "rolling", "climb_descent", "descent_climb", "big_climb", "big_descent"

    # New pattern matching fields
    gain_distribution: List[float] = field(default_factory=lambda: [33.3, 33.3, 33.3])  # [early%, mid%, late%] by thirds
    max_sustained_grade: float = 0.0  # Max grade over 200m+ distance
    load_pattern: str = "balanced"  # "front_loaded", "back_loaded", "balanced"

    # Raw data for advanced matching
    hills: List[Hill] = field(default_factory=list)


def analyze_elevation_profile(profile: Sequence[Sequence[float]], min_hill_gain_m: float = 10.0) -> ElevationAnalysis:
    """Analyze an elevation profile to extract detailed metrics.

    Args:
        profile: Profile as [[km, elevation_m], ...]
        min_hill_gain_m: Minimum elevation change to count as a hill

    Returns:
        ElevationAnalysis with detailed metrics
    """
    if len(profile) < 2:
        return ElevationAnalysis()

    total_distance_km = profile[-1][0] - profile[0][0]
    if total_distance_km <= 0:
        return ElevationAnalysis()

    # Detect hills using a simple algorithm
    hills = _detect_hills(profile, min_hill_gain_m)
    climbs = [h for h in hills if h.is_climb]
    descents = [h for h in hills if not h.is_climb]

    # Calculate metrics
    hill_count = len(climbs)  # Count climbs as "hills"

    avg_hill_length = 0.0
    if climbs:
        avg_hill_length = sum(h.length_km for h in climbs) / len(climbs)

    max_climb_grade = max((h.grade_percent for h in climbs), default=0.0)
    max_descent_grade = min((h.grade_percent for h in descents), default=0.0)  # Negative

    # Grade variance - calculate grades between consecutive points
    grades = []
    for i in range(1, len(profile)):
        dist_diff = profile[i][0] - profile[i-1][0]
        if dist_diff > 0:
            elev_diff = profile[i][1] - profile[i-1][1]
            grade = (elev_diff / (dist_diff * 1000)) * 100
            grades.append(grade)

    grade_variance = 0.0
    if grades:
        mean_grade = sum(grades) / len(grades)
        grade_variance = sum((g - mean_grade) ** 2 for g in grades) / len(grades)

    # Elevation range
    elevations = [p[1] for p in profile]
    elevation_range = max(elevations) - min(elevations)

    # Climb position - weighted average of climb positions
    climb_position = 0.5
    if climbs:
        total_climb_gain = sum(h.elevation_change_m for h in climbs)
        if total_climb_gain > 0:
            weighted_pos = sum(
                ((h.start_km + h.end_km) / 2 / total_distance_km) * h.elevation_change_m
                for h in climbs
            )
            climb_position = weighted_pos / total_climb_gain

    # Calculate new pattern matching fields
    gain_distribution = _calculate_gain_distribution(profile, num_sections=3)
    max_sustained_grade = _calculate_max_sustained_grade(profile, min_distance_km=0.2)

    # Pattern classification (now returns tuple)
    pattern, load_pattern = _classify_pattern(profile, climbs, descents, elevation_range, grade_variance)

    return ElevationAnalysis(
        hill_count=hill_count,
        avg_hill_length_km=round(avg_hill_length, 2),
        max_climb_grade=round(max_climb_grade, 1),
        max_descent_grade=round(max_descent_grade, 1),
        grade_variance=round(grade_variance, 2),
        elevation_range_m=round(elevation_range, 1),
        climb_position=round(climb_position, 2),
        pattern=pattern,
        gain_distribution=gain_distribution,
        max_sustained_grade=max_sustained_grade,
        load_pattern=load_pattern,
        hills=hills,
    )


def _detect_hills(profile: Sequence[Sequence[float]], min_gain_m: float) -> List[Hill]:
    """Detect hills in an elevation profile using a peak/valley algorithm.

    Args:
        profile: Profile as [[km, elevation_m], ...]
        min_gain_m: Minimum elevation change to count as a hill

    Returns:
        List of Hill objects
    """
    if len(profile) < 2:
        return []

    hills = []

    # Find local minima and maxima
    extrema = []  # [(km, elevation, is_max), ...]

    for i in range(len(profile)):
        km, elev = profile[i][0], profile[i][1]

        if i == 0 or i == len(profile) - 1:
            # Endpoints are always extrema
            extrema.append((km, elev, None))
            continue

        prev_elev = profile[i-1][1]
        next_elev = profile[i+1][1]

        if elev >= prev_elev and elev >= next_elev and elev > prev_elev:
            extrema.append((km, elev, True))  # Local max
        elif elev <= prev_elev and elev <= next_elev and elev < prev_elev:
            extrema.append((km, elev, False))  # Local min

    # Filter out insignificant extrema
    filtered = [extrema[0]]
    for i in range(1, len(extrema)):
        last = filtered[-1]
        curr = extrema[i]

        elev_diff = abs(curr[1] - last[1])
        if elev_diff >= min_gain_m:
            filtered.append(curr)
        elif i == len(extrema) - 1:
            # Always include endpoint
            filtered.append(curr)

    # Create hills from consecutive extrema
    for i in range(1, len(filtered)):
        start_km, start_elev, _ = filtered[i-1]
        end_km, end_elev, _ = filtered[i]

        elev_change = abs(end_elev - start_elev)
        if elev_change >= min_gain_m:
            hills.append(Hill(
                start_km=start_km,
                end_km=end_km,
                start_elevation_m=start_elev,
                end_elevation_m=end_elev,
            ))

    return hills


def _calculate_gain_distribution(profile: Sequence[Sequence[float]], num_sections: int = 3) -> List[float]:
    """Calculate the percentage of total elevation gain in each section of the route.

    Args:
        profile: Profile as [[km, elevation_m], ...]
        num_sections: Number of sections to divide route into (default 3 for thirds)

    Returns:
        List of percentages for each section (e.g., [40.0, 35.0, 25.0] for 3 sections)
    """
    if len(profile) < 2:
        return [100.0 / num_sections] * num_sections  # Equal distribution

    total_distance = profile[-1][0] - profile[0][0]
    if total_distance <= 0:
        return [100.0 / num_sections] * num_sections

    section_length = total_distance / num_sections
    section_gains = [0.0] * num_sections
    total_gain = 0.0

    for i in range(1, len(profile)):
        # Determine which section this point is in
        distance_from_start = profile[i][0] - profile[0][0]
        section_idx = min(int(distance_from_start / section_length), num_sections - 1)

        # Calculate gain for this segment
        elev_diff = profile[i][1] - profile[i - 1][1]
        if elev_diff > 0:
            section_gains[section_idx] += elev_diff
            total_gain += elev_diff

    # Convert to percentages
    if total_gain > 0:
        return [round((gain / total_gain) * 100, 1) for gain in section_gains]
    else:
        return [100.0 / num_sections] * num_sections


def _calculate_max_sustained_grade(profile: Sequence[Sequence[float]], min_distance_km: float = 0.2) -> float:
    """Find the steepest sustained grade over at least the minimum distance.

    Args:
        profile: Profile as [[km, elevation_m], ...]
        min_distance_km: Minimum distance to consider "sustained" (default 200m)

    Returns:
        Maximum sustained grade as a percentage (positive = uphill)
    """
    if len(profile) < 2:
        return 0.0

    max_grade = 0.0

    # Use a sliding window approach
    for i in range(len(profile)):
        start_km, start_elev = profile[i][0], profile[i][1]

        # Find all points at least min_distance_km away
        for j in range(i + 1, len(profile)):
            end_km, end_elev = profile[j][0], profile[j][1]
            distance = end_km - start_km

            if distance >= min_distance_km:
                # Calculate grade over this segment
                elev_change = end_elev - start_elev
                grade = (elev_change / (distance * 1000)) * 100  # Convert to percentage

                if abs(grade) > abs(max_grade):
                    max_grade = grade

                # Once we've passed the minimum distance, break to next start point
                # (we want the steepest section starting from each point)
                break

    return round(max_grade, 1)


def _classify_pattern(
    profile: Sequence[Sequence[float]],
    climbs: List[Hill],
    descents: List[Hill],
    elevation_range: float,
    grade_variance: float,
) -> Tuple[str, str]:
    """Classify the overall pattern of an elevation profile.

    Returns:
        Tuple of (pattern, load_pattern) where:
        - pattern: "flat", "rolling", "climb_descent", "descent_climb", "big_climb", "big_descent"
        - load_pattern: "front_loaded", "back_loaded", "balanced"
    """
    # Calculate load pattern based on gain distribution
    gain_distribution = _calculate_gain_distribution(profile, num_sections=3)
    if gain_distribution[0] > 50:
        load_pattern = "front_loaded"
    elif gain_distribution[2] > 50:
        load_pattern = "back_loaded"
    else:
        load_pattern = "balanced"

    # Determine main pattern
    if elevation_range < 20:
        return ("flat", load_pattern)

    # Rolling = many small hills with high variance
    if len(climbs) >= 3 and grade_variance > 1.0:
        return ("rolling", load_pattern)

    # Check for dominant single features
    if len(climbs) == 1 and len(descents) <= 1:
        climb = climbs[0]
        if climb.elevation_change_m > elevation_range * 0.7:
            return ("big_climb", load_pattern)

    if len(descents) == 1 and len(climbs) <= 1:
        descent = descents[0]
        if abs(descent.elevation_change_m) > elevation_range * 0.7:
            return ("big_descent", load_pattern)

    # Check for climb-then-descent or descent-then-climb patterns
    if climbs and descents:
        avg_climb_pos = sum(c.start_km for c in climbs) / len(climbs)
        avg_descent_pos = sum(d.start_km for d in descents) / len(descents)

        if avg_climb_pos < avg_descent_pos:
            return ("climb_descent", load_pattern)
        else:
            return ("descent_climb", load_pattern)

    # Default to rolling if there's elevation change
    if elevation_range > 30:
        return ("rolling", load_pattern)

    return ("flat", load_pattern)


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
    analysis: Optional[ElevationAnalysis] = None  # Detailed elevation analysis
    name: Optional[str] = None  # Optional name (e.g., Strava segment name)
    source: str = "generated"  # "strava" or "generated"


async def enrich_routes_with_elevation(
    routes: List[List[Tuple[float, float]]],
    client: Optional[httpx.AsyncClient] = None,
    names: Optional[List[str]] = None,
    source: str = "generated",
    max_routes: int = 6,  # Further reduced since we generate better candidates now
) -> List[RouteWithElevation]:
    """Add elevation data to a list of routes using batched API calls.

    This function batches all elevation lookups into a single API call
    for better performance.

    Args:
        routes: List of routes, each as a list of (lat, lon) coordinates
        client: Optional httpx client to reuse
        names: Optional list of names for each route
        source: Source of the routes ("strava" or "generated")
        max_routes: Maximum number of routes to enrich (for performance)

    Returns:
        List of RouteWithElevation objects
    """
    import logging
    logger = logging.getLogger(__name__)

    # Limit routes to process for performance
    routes_to_process = routes[:max_routes]
    logger.warning(f"[ELEVATION] Enriching {len(routes_to_process)} routes (of {len(routes)} total)")

    if not routes_to_process:
        return []

    should_close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=60.0)  # Longer timeout for batched requests

    try:
        # PHASE 1: Interpolate all routes and collect all coordinates
        interpolated_routes = []
        all_coordinates = []
        route_boundaries = []  # (start_idx, end_idx) for each route

        current_idx = 0
        for route_coords in routes_to_process:
            # Use 150m interval - balance between accuracy and API speed
            interpolated = interpolate_route(route_coords, interval_m=150.0)
            interpolated_routes.append(interpolated)

            start_idx = current_idx
            all_coordinates.extend(interpolated)
            current_idx = len(all_coordinates)
            route_boundaries.append((start_idx, current_idx))

        logger.warning(f"[ELEVATION] Batching {len(all_coordinates)} total points from {len(routes_to_process)} routes")

        # PHASE 2: Make ONE batched elevation API call
        try:
            all_elevations = await get_elevations(all_coordinates, client)
        except Exception as e:
            logger.warning(f"[ELEVATION] Batched elevation call failed: {e}")
            return []

        # PHASE 3: Distribute elevations back to individual routes
        enriched_routes = []

        for i, (interpolated, (start_idx, end_idx)) in enumerate(zip(interpolated_routes, route_boundaries)):
            try:
                # Extract this route's elevations from the batched result
                elevations = all_elevations[start_idx:end_idx]

                # Calculate distance
                distance_km = get_route_distance_km(interpolated)

                # Calculate metrics
                metrics = calculate_elevation_metrics(elevations)

                # Build elevation profile
                profile = _build_profile(interpolated, elevations)

                # Analyze the elevation profile
                analysis = analyze_elevation_profile(profile)

                # Get name if provided
                name = names[i] if names and i < len(names) else None

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
                        analysis=analysis,
                        name=name,
                        source=source,
                    )
                )

            except Exception as e:
                logger.warning(f"[ELEVATION] Failed to process route {i+1}: {e}")
                continue

        logger.warning(f"[ELEVATION] Successfully enriched {len(enriched_routes)}/{len(routes_to_process)} routes")
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


def _score_pattern_match(route_analysis: ElevationAnalysis, target_analysis: ElevationAnalysis) -> float:
    """Score how well a route's elevation pattern matches the target.

    Scoring breakdown:
    - Pattern type match (50%): flat, rolling, big_climb, etc.
    - Load pattern match (30%): front/back/balanced
    - Gain distribution similarity (20%): compare thirds

    Args:
        route_analysis: Analysis of the candidate route
        target_analysis: Analysis of the target route

    Returns:
        Score between 0 and 1
    """
    scores = []

    # 1. Pattern type match (50% weight)
    if route_analysis.pattern == target_analysis.pattern:
        pattern_score = 1.0
    elif _patterns_similar(route_analysis.pattern, target_analysis.pattern):
        pattern_score = 0.7
    else:
        pattern_score = 0.3
    scores.append(pattern_score * 0.50)

    # 2. Load pattern match (30% weight)
    if route_analysis.load_pattern == target_analysis.load_pattern:
        load_score = 1.0
    elif (route_analysis.load_pattern == "balanced" or target_analysis.load_pattern == "balanced"):
        # Balanced is somewhat compatible with front/back loaded
        load_score = 0.6
    else:
        # front_loaded vs back_loaded is a poor match
        load_score = 0.2
    scores.append(load_score * 0.30)

    # 3. Gain distribution similarity (20% weight)
    # Compare the percentage of gain in each third
    route_dist = route_analysis.gain_distribution
    target_dist = target_analysis.gain_distribution

    if len(route_dist) == len(target_dist) == 3:
        # Calculate mean absolute difference
        diff_sum = sum(abs(r - t) for r, t in zip(route_dist, target_dist))
        # Max possible diff is 200 (100-0 vs 0-100 in each section)
        dist_score = max(0, 1 - (diff_sum / 200))
    else:
        dist_score = 0.5
    scores.append(dist_score * 0.20)

    return sum(scores)


def _score_route_realism(route: "RouteWithElevation") -> float:
    """Score how "real" a route is (vs synthetic/generated).

    Bonus points for:
    - Strava-weighted source: +20-30%
    - Named route (not 'Route N'): +10%
    - Base score: 50%

    Args:
        route: Route with elevation data

    Returns:
        Score between 0 and 1
    """
    score = 0.5  # Base score

    # Bonus for Strava-weighted routes
    if route.source == "strava":
        score += 0.30
    elif route.source == "strava-weighted":
        score += 0.20

    # Bonus for named routes (not generic "Route N")
    if route.name and not route.name.startswith("Route "):
        score += 0.10

    return min(score, 1.0)


def score_route(
    route: RouteWithElevation,
    target_distance_km: float,
    target_elevation_gain_m: float,
    target_elevation_loss_m: float = 0.0,
    target_profile: Optional[List[List[float]]] = None,
    target_analysis: Optional[ElevationAnalysis] = None,
) -> float:
    """Calculate a similarity score for a route.

    New simplified scoring weights:
    - Distance match: 25%
    - Elevation gain: 15%
    - Pattern match: 30%
    - Max grade match: 15%
    - Route realism: 15%

    Args:
        route: Route with elevation data
        target_distance_km: Target distance in kilometers
        target_elevation_gain_m: Target elevation gain in meters
        target_elevation_loss_m: Target elevation loss in meters
        target_profile: Optional target elevation profile for shape matching
        target_analysis: Optional detailed elevation analysis for advanced matching

    Returns:
        Similarity score between 0 and 1 (1 = perfect match)
    """
    # Distance similarity (25% weight)
    distance_diff = abs(route.distance_km - target_distance_km)
    distance_score = max(0, 1 - (distance_diff / target_distance_km))

    # Elevation gain similarity (15% weight)
    if target_elevation_gain_m > 0:
        gain_diff = abs(route.elevation_gain_m - target_elevation_gain_m)
        gain_score = max(0, 1 - (gain_diff / target_elevation_gain_m))
    else:
        # If target is flat, penalize any significant elevation
        gain_score = max(0, 1 - (route.elevation_gain_m / 100))

    # Pattern match scoring (30% weight)
    pattern_score = 0.5  # Neutral default
    if target_analysis and route.analysis:
        pattern_score = _score_pattern_match(route.analysis, target_analysis)

    # Max grade match (15% weight)
    max_grade_score = 0.5  # Neutral default
    if target_analysis and route.analysis:
        target_grade = abs(target_analysis.max_sustained_grade)
        route_grade = abs(route.analysis.max_sustained_grade)
        if target_grade > 0:
            grade_diff = abs(route_grade - target_grade)
            max_grade_score = max(0, 1 - (grade_diff / max(target_grade, 1)))
        else:
            # Target is flat, penalize steep routes
            max_grade_score = max(0, 1 - (route_grade / 10))

    # Route realism scoring (15% weight)
    realism_score = _score_route_realism(route)

    # Combined score (weighted average)
    # New weights: distance=25%, gain=15%, pattern=30%, max_grade=15%, realism=15%
    score = (
        0.25 * distance_score +
        0.15 * gain_score +
        0.30 * pattern_score +
        0.15 * max_grade_score +
        0.15 * realism_score
    )

    return round(score, 3)


def _score_elevation_analysis(route_analysis: ElevationAnalysis, target_analysis: ElevationAnalysis) -> float:
    """Score how well a route's elevation characteristics match the target.

    Args:
        route_analysis: Analysis of the candidate route
        target_analysis: Analysis of the target route

    Returns:
        Score between 0 and 1
    """
    scores = []

    # 1. Hill count similarity (how many distinct climbs)
    if target_analysis.hill_count > 0:
        hill_diff = abs(route_analysis.hill_count - target_analysis.hill_count)
        hill_score = max(0, 1 - (hill_diff / max(target_analysis.hill_count, 1)))
    else:
        # Target is flat, penalize having hills
        hill_score = max(0, 1 - (route_analysis.hill_count / 3))
    scores.append(("hill_count", hill_score, 0.15))

    # 2. Average hill length similarity (short steep vs long gradual)
    if target_analysis.avg_hill_length_km > 0:
        length_diff = abs(route_analysis.avg_hill_length_km - target_analysis.avg_hill_length_km)
        length_score = max(0, 1 - (length_diff / target_analysis.avg_hill_length_km))
    else:
        length_score = 0.5  # Neutral if no hills
    scores.append(("avg_hill_length", length_score, 0.10))

    # 3. Max climb grade similarity (steepest section)
    if target_analysis.max_climb_grade > 0:
        grade_diff = abs(route_analysis.max_climb_grade - target_analysis.max_climb_grade)
        grade_score = max(0, 1 - (grade_diff / max(target_analysis.max_climb_grade, 1)))
    else:
        # Target has no significant climbs
        grade_score = max(0, 1 - (route_analysis.max_climb_grade / 5))
    scores.append(("max_grade", grade_score, 0.15))

    # 4. Grade variance similarity (rolling vs consistent)
    if target_analysis.grade_variance > 0.1:
        variance_diff = abs(route_analysis.grade_variance - target_analysis.grade_variance)
        variance_score = max(0, 1 - (variance_diff / target_analysis.grade_variance))
    else:
        # Target is flat/consistent, penalize high variance
        variance_score = max(0, 1 - (route_analysis.grade_variance / 2))
    scores.append(("grade_variance", variance_score, 0.15))

    # 5. Climb position similarity (early vs late climbs)
    position_diff = abs(route_analysis.climb_position - target_analysis.climb_position)
    position_score = max(0, 1 - (position_diff * 2))  # Scale: 0.5 diff = 0 score
    scores.append(("climb_position", position_score, 0.20))

    # 6. Pattern type match (categorical)
    if route_analysis.pattern == target_analysis.pattern:
        pattern_score = 1.0
    elif _patterns_similar(route_analysis.pattern, target_analysis.pattern):
        pattern_score = 0.7
    else:
        pattern_score = 0.3
    scores.append(("pattern", pattern_score, 0.25))

    # Weighted average
    total_weight = sum(weight for _, _, weight in scores)
    weighted_sum = sum(score * weight for _, score, weight in scores)

    return weighted_sum / total_weight if total_weight > 0 else 0.5


def _patterns_similar(pattern1: str, pattern2: str) -> bool:
    """Check if two elevation patterns are similar (not exact match but compatible)."""
    similar_groups = [
        {"flat"},
        {"rolling"},
        {"climb_descent", "descent_climb"},  # Both are out-and-back style
        {"big_climb", "big_descent"},  # Both are single dominant feature
    ]

    for group in similar_groups:
        if pattern1 in group and pattern2 in group:
            return True

    return False


def rank_routes(
    routes: List[RouteWithElevation],
    target_distance_km: float,
    target_elevation_gain_m: float,
    num_results: int = 5,
    target_elevation_loss_m: float = 0.0,
    target_profile: Optional[List[List[float]]] = None,
) -> List[Tuple[RouteWithElevation, float]]:
    """Rank routes by similarity to target metrics.

    Args:
        routes: List of routes with elevation data
        target_distance_km: Target distance in kilometers
        target_elevation_gain_m: Target elevation gain in meters
        num_results: Number of top results to return
        target_elevation_loss_m: Target elevation loss in meters
        target_profile: Optional target elevation profile for shape matching

    Returns:
        List of (route, score) tuples, sorted by score descending
    """
    # Analyze the target profile if provided
    target_analysis = None
    if target_profile and len(target_profile) >= 2:
        target_analysis = analyze_elevation_profile(target_profile)

    scored_routes = [
        (route, score_route(
            route,
            target_distance_km,
            target_elevation_gain_m,
            target_elevation_loss_m,
            target_profile,
            target_analysis,
        ))
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
    generated_count = 0

    for route, score in ranked_routes:
        # Use the route's name if available, otherwise generate one
        if route.name:
            name = route.name
        else:
            generated_count += 1
            name = f"Route {generated_count}"

        results.append(
            RouteResult(
                name=name,
                distance_km=route.distance_km,
                elevation_gain_m=route.elevation_gain_m,
                elevation_loss_m=route.elevation_loss_m,
                similarity_score=score,
                coordinates=[[lat, lon] for lat, lon in route.coordinates],
                profile=route.profile,
                source=route.source,
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
