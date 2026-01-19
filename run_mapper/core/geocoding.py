"""Geocoding service using Nominatim (OpenStreetMap)."""

from typing import Optional, Tuple

import httpx

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "RunMapper/0.1.0 (https://github.com/example/run-mapper)"
REQUEST_TIMEOUT = 10.0


class GeocodingError(Exception):
    """Error from the geocoding service."""

    pass


async def geocode(
    location: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Tuple[float, float]:
    """Convert an address or place name to coordinates.

    Args:
        location: Address or place name (e.g., "Boston, MA")
        client: Optional httpx client to reuse

    Returns:
        Tuple of (latitude, longitude)

    Raises:
        GeocodingError: If the location cannot be found or the API fails
    """
    should_close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    try:
        response = await client.get(
            NOMINATIM_URL,
            params={
                "q": location,
                "format": "json",
                "limit": 1,
            },
            headers={
                "User-Agent": USER_AGENT,
            },
        )
        response.raise_for_status()

        data = response.json()

        if not data:
            raise GeocodingError(f"Location not found: {location}")

        result = data[0]
        latitude = float(result["lat"])
        longitude = float(result["lon"])

        return (latitude, longitude)

    except httpx.HTTPStatusError as e:
        raise GeocodingError(f"Geocoding request failed: {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise GeocodingError(f"Geocoding request failed: {e}") from e
    except (KeyError, ValueError, IndexError) as e:
        raise GeocodingError(f"Invalid geocoding response: {e}") from e
    finally:
        if should_close_client:
            await client.aclose()


async def reverse_geocode(
    latitude: float,
    longitude: float,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    """Convert coordinates to a place name.

    Args:
        latitude: Latitude in degrees
        longitude: Longitude in degrees
        client: Optional httpx client to reuse

    Returns:
        Place name or address

    Raises:
        GeocodingError: If the location cannot be found or the API fails
    """
    should_close_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=REQUEST_TIMEOUT)

    try:
        response = await client.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": latitude,
                "lon": longitude,
                "format": "json",
            },
            headers={
                "User-Agent": USER_AGENT,
            },
        )
        response.raise_for_status()

        data = response.json()
        return data.get("display_name", f"{latitude:.4f}, {longitude:.4f}")

    except httpx.HTTPStatusError as e:
        raise GeocodingError(f"Reverse geocoding request failed: {e.response.status_code}") from e
    except httpx.RequestError as e:
        raise GeocodingError(f"Reverse geocoding request failed: {e}") from e
    finally:
        if should_close_client:
            await client.aclose()
