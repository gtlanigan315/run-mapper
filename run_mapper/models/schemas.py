"""Pydantic models for API request/response schemas."""

from typing import List, Optional

from pydantic import BaseModel, Field


class ElevationProfile(BaseModel):
    """Elevation profile extracted from a GPX file."""

    distance_km: float = Field(..., description="Total distance in kilometers")
    elevation_gain_m: float = Field(..., description="Total elevation gain in meters")
    elevation_loss_m: float = Field(..., description="Total elevation loss in meters")
    min_elevation_m: float = Field(..., description="Minimum elevation in meters")
    max_elevation_m: float = Field(..., description="Maximum elevation in meters")
    profile: List[List[float]] = Field(
        ..., description="Elevation profile as [[km, elevation_m], ...]"
    )


class FindRoutesRequest(BaseModel):
    """Request body for finding comparable routes."""

    location: str = Field(..., description="Location to search for routes (e.g., 'Boston, MA')")
    target_distance_km: float = Field(..., gt=0, description="Target route distance in kilometers")
    target_elevation_gain_m: float = Field(..., ge=0, description="Target elevation gain in meters")
    target_elevation_loss_m: float = Field(default=0, ge=0, description="Target elevation loss in meters")
    target_profile: Optional[List[List[float]]] = Field(
        default=None,
        description="Target elevation profile as [[km, elevation_m], ...] for shape matching"
    )
    num_results: int = Field(default=5, ge=1, le=20, description="Number of routes to return")
    strava_access_token: Optional[str] = Field(
        default=None,
        description="Strava access token for fetching popular segments"
    )


class RouteResult(BaseModel):
    """A single route result with elevation data."""

    name: str = Field(..., description="Route name/identifier")
    distance_km: float = Field(..., description="Route distance in kilometers")
    elevation_gain_m: float = Field(..., description="Total elevation gain in meters")
    elevation_loss_m: float = Field(..., description="Total elevation loss in meters")
    similarity_score: float = Field(..., ge=0, le=1, description="Similarity score (0-1)")
    coordinates: List[List[float]] = Field(..., description="Route coordinates as [[lat, lon], ...]")
    profile: List[List[float]] = Field(
        ..., description="Elevation profile as [[km, elevation_m], ...]"
    )
    source: str = Field(
        default="generated",
        description="Route source: 'strava' for Strava segments, 'generated' for algorithm-generated"
    )


class FindRoutesResponse(BaseModel):
    """Response containing matching routes."""

    routes: List[RouteResult] = Field(..., description="List of matching routes")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = Field(..., description="Service status")
    version: str = Field(..., description="API version")


class ErrorResponse(BaseModel):
    """Error response."""

    detail: str = Field(..., description="Error message")
