"""API routes for Run Mapper."""

import asyncio
import logging
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
from run_mapper.core.route_finder import find_candidate_routes, find_routes_smart, get_route_distance_km, RouteFinderError
from run_mapper.core.strava import (
    StravaError,
    decode_polyline,
    find_segments_in_area,
)
from run_mapper.models.schemas import (
    ElevationProfile,
    ErrorResponse,
    FindRoutesRequest,
    FindRoutesResponse,
    HealthResponse,
)

logger = logging.getLogger(__name__)

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
    in that area. If a Strava access token is provided, popular Strava
    segments will be included in the results.
    """
    # Geocode the location
    try:
        lat, lon = await geocode(request.location)
    except GeocodingError as e:
        raise HTTPException(status_code=404, detail=str(e))

    all_routes_with_elevation = []
    popular_paths = []  # Strava segment coords used to weight route generation

    logger.warning(f"[DEBUG] Strava token provided: {bool(request.strava_access_token)}")

    # Try to get Strava segments if token is provided
    if request.strava_access_token:
        try:
            # Search radius based on target distance
            search_radius_km = max(request.target_distance_km * 0.75, 3.0)

            strava_segments = await find_segments_in_area(
                access_token=request.strava_access_token,
                center_lat=lat,
                center_lon=lon,
                radius_km=search_radius_km,
                activity_type="running",
            )

            if strava_segments:
                logger.warning(f"[STRAVA] Found {len(strava_segments)} Strava segments for popularity weighting")

                # Decode all segment polylines to use as popularity data
                for segment in strava_segments:
                    coords = decode_polyline(segment.points)
                    if len(coords) >= 2:
                        popular_paths.append(coords)
                logger.warning(f"[STRAVA] Decoded {len(popular_paths)} segment polylines")
            else:
                logger.warning("[STRAVA] No segments found in area")

        except StravaError as e:
            # Log but don't fail - fall back to unweighted route generation
            logger.warning(f"Strava API error: {e}")

    # Find routes using the smart area-first approach
    loop = asyncio.get_event_loop()
    try:
        # Early termination: if we have good Strava coverage, generate fewer routes
        num_routes_to_generate = request.num_results * 2
        if len(popular_paths) >= 10:
            num_routes_to_generate = min(request.num_results * 2, 15)
            logger.warning(f"[PERF] Good Strava coverage ({len(popular_paths)} segments), limiting to {num_routes_to_generate} routes")

        # Use smart route finding that prioritizes quality running paths
        candidate_routes = await loop.run_in_executor(
            _executor,
            lambda: find_routes_smart(
                lat,
                lon,
                request.target_distance_km,
                num_routes_to_generate,
                popular_paths=popular_paths if popular_paths else None,
            ),
        )

        # Distance pre-filter: remove routes that are too far from target distance
        # This saves expensive elevation API calls
        DISTANCE_TOLERANCE = 0.15  # 15%
        min_dist = request.target_distance_km * (1 - DISTANCE_TOLERANCE)
        max_dist = request.target_distance_km * (1 + DISTANCE_TOLERANCE)

        filtered_routes = []
        for route in candidate_routes:
            route_dist = get_route_distance_km(route)
            if min_dist <= route_dist <= max_dist:
                filtered_routes.append(route)

        logger.warning(f"[PERF] Distance pre-filter: {len(candidate_routes)} -> {len(filtered_routes)} routes")

        # Enrich generated routes with elevation data
        # Mark source as "strava-weighted" if we used Strava data for weighting
        source = "strava-weighted" if popular_paths else "generated"
        generated_enriched = await enrich_routes_with_elevation(
            filtered_routes,
            source=source,
        )
        all_routes_with_elevation.extend(generated_enriched)

    except RouteFinderError as e:
        raise HTTPException(status_code=404, detail=str(e))

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate routes: {e}",
        )

    if not all_routes_with_elevation:
        raise HTTPException(
            status_code=404,
            detail="No routes found in this area",
        )

    # Rank and return results (Strava routes will naturally rank higher if they match better)
    ranked = rank_routes(
        all_routes_with_elevation,
        request.target_distance_km,
        request.target_elevation_gain_m,
        request.num_results,
        target_elevation_loss_m=request.target_elevation_loss_m,
        target_profile=request.target_profile,
    )

    results = routes_to_results(ranked)

    return FindRoutesResponse(routes=results)
