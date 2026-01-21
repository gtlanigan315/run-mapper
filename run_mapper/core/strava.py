"""Strava API integration for fetching popular running segments."""

import os
from dataclasses import dataclass
from typing import List, Optional, Tuple
from urllib.parse import urlencode

import httpx

# Strava API endpoints
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_API_BASE = "https://www.strava.com/api/v3"


class StravaError(Exception):
    """Error from Strava API operations."""

    pass


@dataclass
class StravaSegment:
    """A Strava segment with its polyline."""

    id: int
    name: str
    distance: float  # meters
    avg_grade: float  # percent
    elev_difference: float  # meters
    climb_category: int
    start_latlng: Tuple[float, float]
    end_latlng: Tuple[float, float]
    points: str  # Encoded polyline
    starred: bool = False


@dataclass
class StravaTokens:
    """OAuth tokens from Strava."""

    access_token: str
    refresh_token: str
    expires_at: int
    athlete_id: int


def get_client_credentials() -> Tuple[str, str]:
    """Get Strava client credentials from environment variables.

    Returns:
        Tuple of (client_id, client_secret)

    Raises:
        StravaError: If credentials are not configured
    """
    client_id = os.environ.get("STRAVA_CLIENT_ID")
    client_secret = os.environ.get("STRAVA_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise StravaError(
            "Strava credentials not configured. "
            "Set STRAVA_CLIENT_ID and STRAVA_CLIENT_SECRET environment variables."
        )

    return client_id, client_secret


def get_authorization_url(redirect_uri: str, state: Optional[str] = None) -> str:
    """Generate Strava OAuth authorization URL.

    Args:
        redirect_uri: URL to redirect to after authorization
        state: Optional state parameter for CSRF protection

    Returns:
        Authorization URL to redirect user to
    """
    client_id, _ = get_client_credentials()

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "read",  # Only need read access for segments
    }

    if state:
        params["state"] = state

    return f"{STRAVA_AUTH_URL}?{urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> StravaTokens:
    """Exchange authorization code for access tokens.

    Args:
        code: Authorization code from OAuth callback

    Returns:
        StravaTokens with access and refresh tokens

    Raises:
        StravaError: If token exchange fails
    """
    client_id, client_secret = get_client_credentials()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
        )

        if response.status_code != 200:
            raise StravaError(f"Token exchange failed: {response.text}")

        data = response.json()

        return StravaTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            athlete_id=data["athlete"]["id"],
        )


async def refresh_access_token(refresh_token: str) -> StravaTokens:
    """Refresh an expired access token.

    Args:
        refresh_token: Refresh token from previous authorization

    Returns:
        New StravaTokens with fresh access token

    Raises:
        StravaError: If refresh fails
    """
    client_id, client_secret = get_client_credentials()

    async with httpx.AsyncClient() as client:
        response = await client.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )

        if response.status_code != 200:
            raise StravaError(f"Token refresh failed: {response.text}")

        data = response.json()

        return StravaTokens(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            expires_at=data["expires_at"],
            athlete_id=0,  # Not returned on refresh
        )


async def explore_segments(
    access_token: str,
    bounds: Tuple[float, float, float, float],
    activity_type: str = "running",
    min_cat: Optional[int] = None,
    max_cat: Optional[int] = None,
) -> List[StravaSegment]:
    """Explore segments in a given area.

    Args:
        access_token: Valid Strava access token
        bounds: Bounding box as (sw_lat, sw_lon, ne_lat, ne_lon)
        activity_type: "running" or "riding"
        min_cat: Minimum climb category (0-5)
        max_cat: Maximum climb category (0-5)

    Returns:
        List of StravaSegment objects

    Raises:
        StravaError: If API request fails
    """
    sw_lat, sw_lon, ne_lat, ne_lon = bounds

    params = {
        "bounds": f"{sw_lat},{sw_lon},{ne_lat},{ne_lon}",
        "activity_type": activity_type,
    }

    if min_cat is not None:
        params["min_cat"] = min_cat
    if max_cat is not None:
        params["max_cat"] = max_cat

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{STRAVA_API_BASE}/segments/explore",
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if response.status_code == 401:
            raise StravaError("Strava token expired or invalid")

        if response.status_code != 200:
            raise StravaError(f"Segment explore failed: {response.text}")

        data = response.json()

        segments = []
        for seg in data.get("segments", []):
            segments.append(
                StravaSegment(
                    id=seg["id"],
                    name=seg["name"],
                    distance=seg["distance"],
                    avg_grade=seg["avg_grade"],
                    elev_difference=seg["elev_difference"],
                    climb_category=seg["climb_category"],
                    start_latlng=tuple(seg["start_latlng"]),
                    end_latlng=tuple(seg["end_latlng"]),
                    points=seg["points"],
                    starred=seg.get("starred", False),
                )
            )

        return segments


async def get_segment_details(access_token: str, segment_id: int) -> dict:
    """Get detailed information about a specific segment.

    Args:
        access_token: Valid Strava access token
        segment_id: Strava segment ID

    Returns:
        Full segment details from API

    Raises:
        StravaError: If API request fails
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{STRAVA_API_BASE}/segments/{segment_id}",
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if response.status_code == 401:
            raise StravaError("Strava token expired or invalid")

        if response.status_code != 200:
            raise StravaError(f"Get segment failed: {response.text}")

        return response.json()


def decode_polyline(polyline: str) -> List[Tuple[float, float]]:
    """Decode a Google-encoded polyline string into lat/lng coordinates.

    Args:
        polyline: Encoded polyline string

    Returns:
        List of (lat, lon) tuples
    """
    coordinates = []
    index = 0
    lat = 0
    lng = 0

    while index < len(polyline):
        # Decode latitude
        shift = 0
        result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break

        dlat = ~(result >> 1) if result & 1 else result >> 1
        lat += dlat

        # Decode longitude
        shift = 0
        result = 0
        while True:
            b = ord(polyline[index]) - 63
            index += 1
            result |= (b & 0x1F) << shift
            shift += 5
            if b < 0x20:
                break

        dlng = ~(result >> 1) if result & 1 else result >> 1
        lng += dlng

        coordinates.append((lat / 1e5, lng / 1e5))

    return coordinates


async def find_segments_in_area(
    access_token: str,
    center_lat: float,
    center_lon: float,
    radius_km: float,
    activity_type: str = "running",
) -> List[StravaSegment]:
    """Find all running segments within a radius of a point.

    Uses multiple queries with overlapping bounding boxes to get more
    than the 10-segment limit per query.

    Args:
        access_token: Valid Strava access token
        center_lat: Center latitude
        center_lon: Center longitude
        radius_km: Search radius in kilometers
        activity_type: "running" or "riding"

    Returns:
        List of unique StravaSegment objects
    """
    # Convert radius to approximate degrees
    # ~111km per degree latitude, longitude varies by latitude
    lat_delta = radius_km / 111.0
    lon_delta = radius_km / (111.0 * abs(cos_deg(center_lat)))

    # Create grid of overlapping bounding boxes
    # Use 55% overlap as suggested for better coverage
    grid_size = 2  # 2x2 grid for moderate coverage
    step_lat = (2 * lat_delta) / grid_size * 0.55
    step_lon = (2 * lon_delta) / grid_size * 0.55

    seen_ids = set()
    all_segments = []

    for i in range(grid_size):
        for j in range(grid_size):
            offset_lat = (i - grid_size / 2 + 0.5) * step_lat
            offset_lon = (j - grid_size / 2 + 0.5) * step_lon

            box_center_lat = center_lat + offset_lat
            box_center_lon = center_lon + offset_lon

            bounds = (
                box_center_lat - lat_delta / grid_size,
                box_center_lon - lon_delta / grid_size,
                box_center_lat + lat_delta / grid_size,
                box_center_lon + lon_delta / grid_size,
            )

            try:
                segments = await explore_segments(
                    access_token, bounds, activity_type
                )

                for seg in segments:
                    if seg.id not in seen_ids:
                        seen_ids.add(seg.id)
                        all_segments.append(seg)

            except StravaError:
                # Continue with other boxes if one fails
                continue

    return all_segments


def cos_deg(degrees: float) -> float:
    """Cosine of angle in degrees."""
    import math

    return math.cos(math.radians(degrees))


def segments_to_routes(
    segments: List[StravaSegment],
    target_distance_km: float,
    distance_tolerance: float = 0.3,
) -> List[List[Tuple[float, float]]]:
    """Convert Strava segments to route coordinate lists.

    Filters segments by distance and decodes their polylines.

    Args:
        segments: List of Strava segments
        target_distance_km: Target distance in km
        distance_tolerance: Acceptable deviation (0.3 = 30%)

    Returns:
        List of routes as coordinate lists
    """
    min_dist = target_distance_km * (1 - distance_tolerance) * 1000
    max_dist = target_distance_km * (1 + distance_tolerance) * 1000

    routes = []

    for segment in segments:
        # Filter by distance
        if min_dist <= segment.distance <= max_dist:
            coords = decode_polyline(segment.points)
            if len(coords) >= 2:
                routes.append(coords)

    return routes
