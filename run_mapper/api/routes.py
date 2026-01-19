"""API routes for Run Mapper."""

import asyncio
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, File, HTTPException, UploadFile

from run_mapper import __version__
from run_mapper.core.geocoding import geocode, GeocodingError
from run_mapper.core.gpx_parser import parse_gpx
from run_mapper.core.matcher import (
    enrich_routes_with_elevation,
    rank_routes,
    routes_to_results,
)
from run_mapper.core.route_finder import find_candidate_routes, RouteFinderError
from run_mapper.models.schemas import (
    ElevationProfile,
    ErrorResponse,
    FindRoutesRequest,
    FindRoutesResponse,
    HealthResponse,
)

router = APIRouter()

# Thread pool for running synchronous OSMnx operations
_executor = ThreadPoolExecutor(max_workers=4)


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="healthy", version=__version__)


@router.post(
    "/analyze-gpx",
    response_model=ElevationProfile,
    responses={400: {"model": ErrorResponse}},
)
async def analyze_gpx(file: UploadFile = File(...)) -> ElevationProfile:
    """Analyze a GPX file and extract its elevation profile.

    Upload a GPX file to get distance, elevation gain/loss, and a detailed
    elevation profile.
    """
    if not file.filename or not file.filename.lower().endswith(".gpx"):
        raise HTTPException(
            status_code=400,
            detail="File must be a GPX file (.gpx extension)",
        )

    try:
        content = await file.read()
        profile = parse_gpx(content)
        return profile
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse GPX file: {e}")


@router.post(
    "/find-routes",
    response_model=FindRoutesResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def find_routes(request: FindRoutesRequest) -> FindRoutesResponse:
    """Find running routes that match the specified criteria.

    Given a location and target distance/elevation, find comparable routes
    in that area.
    """
    # Geocode the location
    try:
        lat, lon = await geocode(request.location)
    except GeocodingError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Find candidate routes (synchronous, run in thread pool)
    loop = asyncio.get_event_loop()
    try:
        candidate_routes = await loop.run_in_executor(
            _executor,
            find_candidate_routes,
            lat,
            lon,
            request.target_distance_km,
            request.num_results * 2,  # Generate more than needed for filtering
        )
    except RouteFinderError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Enrich routes with elevation data
    try:
        routes_with_elevation = await enrich_routes_with_elevation(candidate_routes)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to fetch elevation data: {e}",
        )

    # Rank and return results
    ranked = rank_routes(
        routes_with_elevation,
        request.target_distance_km,
        request.target_elevation_gain_m,
        request.num_results,
    )

    results = routes_to_results(ranked)

    return FindRoutesResponse(routes=results)
