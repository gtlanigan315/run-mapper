"""Elevation service using Open-Elevation API."""

import asyncio
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
BATCH_SIZE = 100  # Max locations per request
REQUEST_TIMEOUT = 60.0  # Increased timeout for slow API


class ElevationServiceError(Exception):
    """Error from the elevation service."""

    pass


async def get_elevations(
    coordinates: Sequence[Tuple[float, float]],
    client: Optional[httpx.AsyncClient] = None,
) -> List[float]:
    """Get elevation data for a list of coordinates.

    Args:
        coordinates: List of (latitude, longitude) tuples
        client: Optional httpx client to reuse

    Returns:
        List of elevations in meters, in the same order as input coordinates

    Raises:
        ElevationServiceError: If the API request fails
    """
    if not coordinates:
        return []

    should_close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    try:
        all_elevations: list[float] = []

        # Process in batches to avoid overwhelming the API
        for i in range(0, len(coordinates), BATCH_SIZE):
            batch = coordinates[i : i + BATCH_SIZE]
            elevations = await _fetch_batch_elevations(batch, client)
            all_elevations.extend(elevations)

            # Rate limiting: small delay between batches
            if i + BATCH_SIZE < len(coordinates):
                await asyncio.sleep(0.1)  # Reduced delay

        return all_elevations
    finally:
        if should_close_client:
            await client.aclose()


async def _fetch_batch_elevations(
    coordinates: Sequence[Tuple[float, float]],
    client: httpx.AsyncClient,
) -> List[float]:
    """Fetch elevations for a batch of coordinates.

    Args:
        coordinates: List of (latitude, longitude) tuples
        client: httpx client to use

    Returns:
        List of elevations in meters

    Raises:
        ElevationServiceError: If the API request fails
    """
    locations = [{"latitude": lat, "longitude": lon} for lat, lon in coordinates]

    try:
        response = await client.post(
            OPEN_ELEVATION_URL,
            json={"locations": locations},
        )
        response.raise_for_status()

        data = response.json()
        results = data.get("results", [])

        if len(results) != len(coordinates):
            raise ElevationServiceError(
                f"Expected {len(coordinates)} results, got {len(results)}"
            )

        return [r.get("elevation", 0.0) for r in results]

    except httpx.HTTPStatusError as e:
        raise ElevationServiceError(f"API request failed: {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise ElevationServiceError(f"API request failed: {e}") from e
    except (KeyError, ValueError) as e:
        raise ElevationServiceError(f"Invalid API response: {e}") from e


def smooth_elevations(elevations: Sequence[float], window_size: int = 5) -> List[float]:
    """Apply rolling average to remove GPS noise from elevation data.

    Args:
        elevations: List of elevation values in meters
        window_size: Number of points to average (must be odd, default 5)

    Returns:
        Smoothed list of elevations
    """
    if not elevations:
        return []

    if len(elevations) <= window_size:
        return list(elevations)

    # Ensure window size is odd for symmetric smoothing
    if window_size % 2 == 0:
        window_size += 1

    half_window = window_size // 2
    smoothed = []

    for i in range(len(elevations)):
        # Calculate window bounds
        start = max(0, i - half_window)
        end = min(len(elevations), i + half_window + 1)

        # Calculate average of window
        window_values = elevations[start:end]
        smoothed.append(sum(window_values) / len(window_values))

    return smoothed


def calculate_elevation_metrics(
    elevations: Sequence[float],
    min_change_threshold_m: float = 2.0,
    apply_smoothing: bool = True,
) -> Dict[str, float]:
    """Calculate elevation metrics from a list of elevations.

    Args:
        elevations: List of elevation values in meters
        min_change_threshold_m: Minimum elevation change to count (filters GPS noise)
        apply_smoothing: Whether to apply rolling average smoothing first

    Returns:
        Dictionary with elevation_gain_m, elevation_loss_m, min_elevation_m, max_elevation_m
    """
    if not elevations:
        return {
            "elevation_gain_m": 0.0,
            "elevation_loss_m": 0.0,
            "min_elevation_m": 0.0,
            "max_elevation_m": 0.0,
        }

    # Apply smoothing to reduce GPS noise
    working_elevations = smooth_elevations(elevations) if apply_smoothing else list(elevations)

    elevation_gain = 0.0
    elevation_loss = 0.0

    for i in range(1, len(working_elevations)):
        diff = working_elevations[i] - working_elevations[i - 1]
        # Only count changes above the threshold to filter out noise
        if diff > min_change_threshold_m:
            elevation_gain += diff
        elif diff < -min_change_threshold_m:
            elevation_loss += abs(diff)

    return {
        "elevation_gain_m": round(elevation_gain, 1),
        "elevation_loss_m": round(elevation_loss, 1),
        "min_elevation_m": round(min(elevations), 1),
        "max_elevation_m": round(max(elevations), 1),
    }
