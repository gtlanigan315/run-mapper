"""Elevation service using Open-Elevation API."""

import asyncio
from typing import Dict, List, Optional, Sequence, Tuple

import httpx

OPEN_ELEVATION_URL = "https://api.open-elevation.com/api/v1/lookup"
BATCH_SIZE = 100  # Max locations per request
REQUEST_TIMEOUT = 30.0


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
                await asyncio.sleep(0.5)

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


def calculate_elevation_metrics(elevations: Sequence[float]) -> Dict[str, float]:
    """Calculate elevation metrics from a list of elevations.

    Args:
        elevations: List of elevation values in meters

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

    elevation_gain = 0.0
    elevation_loss = 0.0

    for i in range(1, len(elevations)):
        diff = elevations[i] - elevations[i - 1]
        if diff > 0:
            elevation_gain += diff
        else:
            elevation_loss += abs(diff)

    return {
        "elevation_gain_m": round(elevation_gain, 1),
        "elevation_loss_m": round(elevation_loss, 1),
        "min_elevation_m": round(min(elevations), 1),
        "max_elevation_m": round(max(elevations), 1),
    }
