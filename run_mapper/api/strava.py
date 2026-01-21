"""Strava OAuth and API routes."""

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from run_mapper.core.strava import (
    StravaError,
    decode_polyline,
    exchange_code_for_tokens,
    explore_segments,
    find_segments_in_area,
    get_authorization_url,
    refresh_access_token,
)

router = APIRouter(prefix="/strava", tags=["strava"])


class StravaAuthURL(BaseModel):
    """Response containing Strava authorization URL."""

    url: str = Field(..., description="URL to redirect user to for Strava authorization")


class StravaTokenResponse(BaseModel):
    """Response containing Strava tokens."""

    access_token: str
    refresh_token: str
    expires_at: int
    athlete_id: int


class StravaSegmentResponse(BaseModel):
    """A Strava segment with decoded coordinates."""

    id: int
    name: str
    distance_m: float
    avg_grade: float
    elev_difference_m: float
    coordinates: list[list[float]]  # [[lat, lon], ...]


class StravaSegmentsResponse(BaseModel):
    """Response containing Strava segments."""

    segments: list[StravaSegmentResponse]


def get_redirect_uri() -> str:
    """Get the OAuth redirect URI based on environment."""
    frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:5173")
    return frontend_url  # Callback is handled on the root path


@router.get("/auth-url", response_model=StravaAuthURL)
async def get_strava_auth_url(
    state: Optional[str] = Query(None, description="Optional state for CSRF protection"),
) -> StravaAuthURL:
    """Get the Strava OAuth authorization URL.

    Returns a URL that the frontend should redirect the user to.
    After authorization, Strava will redirect back to /strava/callback
    with an authorization code.
    """
    try:
        redirect_uri = get_redirect_uri()
        url = get_authorization_url(redirect_uri, state)
        return StravaAuthURL(url=url)
    except StravaError as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/exchange-token", response_model=StravaTokenResponse)
async def exchange_strava_token(
    code: str = Query(..., description="Authorization code from Strava callback"),
) -> StravaTokenResponse:
    """Exchange authorization code for access tokens.

    Called by frontend after user completes Strava OAuth flow.
    """
    try:
        tokens = await exchange_code_for_tokens(code)
        return StravaTokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=tokens.expires_at,
            athlete_id=tokens.athlete_id,
        )
    except StravaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/refresh-token", response_model=StravaTokenResponse)
async def refresh_strava_token(
    refresh_token: str = Query(..., description="Refresh token from previous authorization"),
) -> StravaTokenResponse:
    """Refresh an expired Strava access token."""
    try:
        tokens = await refresh_access_token(refresh_token)
        return StravaTokenResponse(
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=tokens.expires_at,
            athlete_id=0,
        )
    except StravaError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/segments", response_model=StravaSegmentsResponse)
async def get_strava_segments(
    access_token: str = Query(..., description="Strava access token"),
    lat: float = Query(..., description="Center latitude"),
    lon: float = Query(..., description="Center longitude"),
    radius_km: float = Query(5.0, description="Search radius in kilometers"),
) -> StravaSegmentsResponse:
    """Get popular running segments near a location.

    Returns segments with their decoded polyline coordinates.
    """
    try:
        segments = await find_segments_in_area(
            access_token=access_token,
            center_lat=lat,
            center_lon=lon,
            radius_km=radius_km,
            activity_type="running",
        )

        response_segments = []
        for seg in segments:
            coords = decode_polyline(seg.points)
            response_segments.append(
                StravaSegmentResponse(
                    id=seg.id,
                    name=seg.name,
                    distance_m=seg.distance,
                    avg_grade=seg.avg_grade,
                    elev_difference_m=seg.elev_difference,
                    coordinates=[[lat, lon] for lat, lon in coords],
                )
            )

        return StravaSegmentsResponse(segments=response_segments)

    except StravaError as e:
        raise HTTPException(status_code=400, detail=str(e))
