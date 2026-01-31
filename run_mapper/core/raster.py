"""Raster-based route finding with multi-dimensional analysis.

This module implements raster analysis for route finding, considering:
- Distance
- Elevation gain/loss
- Slope
- Hill distribution over the route
- Park/trail boundaries
"""

import logging
import math
from dataclasses import dataclass
from heapq import heappush, heappop
from typing import Dict, List, Optional, Tuple, Set

import numpy as np
from scipy import ndimage
from skimage import morphology, measure

logger = logging.getLogger(__name__)

# Constants
DEFAULT_RESOLUTION = 10  # meters per cell
EARTH_RADIUS_M = 6371000  # Earth radius in meters


@dataclass
class RasterBounds:
    """Geographic bounds for a raster grid."""
    min_lat: float
    max_lat: float
    min_lon: float
    max_lon: float
    resolution: float  # meters per cell

    @property
    def width_m(self) -> float:
        """Width in meters."""
        return haversine_distance(
            self.min_lat, self.min_lon,
            self.min_lat, self.max_lon
        )

    @property
    def height_m(self) -> float:
        """Height in meters."""
        return haversine_distance(
            self.min_lat, self.min_lon,
            self.max_lat, self.min_lon
        )

    @property
    def cols(self) -> int:
        """Number of columns in grid."""
        return max(1, int(self.width_m / self.resolution))

    @property
    def rows(self) -> int:
        """Number of rows in grid."""
        return max(1, int(self.height_m / self.resolution))


@dataclass
class RasterLayers:
    """Collection of raster layers for route analysis."""
    bounds: RasterBounds
    elevation: np.ndarray  # DEM in meters
    cost: np.ndarray  # Running cost surface (lower = better)
    slope: np.ndarray  # Slope in degrees
    parks: np.ndarray  # Park mask (1 = park, 0 = not park)
    trails: np.ndarray  # Trail mask (1 = trail, 0 = not trail)


@dataclass
class RouteCandidate:
    """A candidate route with multi-dimensional metrics."""
    path_cells: List[Tuple[int, int]]  # (row, col) cells
    path_coords: List[Tuple[float, float]]  # (lat, lon) coordinates
    distance_m: float
    elevation_gain_m: float
    elevation_loss_m: float
    elevation_profile: List[float]
    hill_distribution: str  # 'flat', 'rolling', 'front_loaded', 'back_loaded', 'climb_descent'
    score: float  # 0-100 match score


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two points in meters using Haversine formula."""
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lat = math.radians(lat2 - lat1)
    delta_lon = math.radians(lon2 - lon1)

    a = (math.sin(delta_lat / 2) ** 2 +
         math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(delta_lon / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def create_bounds_from_center(
    center_lat: float,
    center_lon: float,
    radius_m: float,
    resolution: float = DEFAULT_RESOLUTION
) -> RasterBounds:
    """Create raster bounds from center point and radius."""
    # Approximate degrees per meter at this latitude
    lat_per_m = 1 / 111320
    lon_per_m = 1 / (111320 * math.cos(math.radians(center_lat)))

    lat_offset = radius_m * lat_per_m
    lon_offset = radius_m * lon_per_m

    return RasterBounds(
        min_lat=center_lat - lat_offset,
        max_lat=center_lat + lat_offset,
        min_lon=center_lon - lon_offset,
        max_lon=center_lon + lon_offset,
        resolution=resolution
    )


def latlon_to_cell(
    lat: float,
    lon: float,
    bounds: RasterBounds
) -> Tuple[int, int]:
    """Convert lat/lon to raster cell (row, col)."""
    # Row increases from top (max_lat) to bottom (min_lat)
    row_frac = (bounds.max_lat - lat) / (bounds.max_lat - bounds.min_lat)
    row = int(row_frac * bounds.rows)
    row = max(0, min(bounds.rows - 1, row))

    # Col increases from left (min_lon) to right (max_lon)
    col_frac = (lon - bounds.min_lon) / (bounds.max_lon - bounds.min_lon)
    col = int(col_frac * bounds.cols)
    col = max(0, min(bounds.cols - 1, col))

    return (row, col)


def cell_to_latlon(
    row: int,
    col: int,
    bounds: RasterBounds
) -> Tuple[float, float]:
    """Convert raster cell (row, col) to lat/lon."""
    lat = bounds.max_lat - (row / bounds.rows) * (bounds.max_lat - bounds.min_lat)
    lon = bounds.min_lon + (col / bounds.cols) * (bounds.max_lon - bounds.min_lon)
    return (lat, lon)


async def download_elevation_dem(
    bounds: RasterBounds,
    client=None
) -> np.ndarray:
    """Download elevation DEM for the given bounds.

    Uses Open-Elevation API to get elevation data.
    """
    import httpx

    logger.info(f"[RASTER] Downloading DEM for {bounds.rows}x{bounds.cols} grid")

    # Create grid of sample points
    # Sample at lower resolution for API efficiency, then interpolate
    sample_step = max(1, min(bounds.rows, bounds.cols) // 50)  # Max ~50 samples per dimension

    sample_rows = range(0, bounds.rows, sample_step)
    sample_cols = range(0, bounds.cols, sample_step)

    # Collect coordinates for API call
    coordinates = []
    for row in sample_rows:
        for col in sample_cols:
            lat, lon = cell_to_latlon(row, col, bounds)
            coordinates.append({"latitude": lat, "longitude": lon})

    logger.info(f"[RASTER] Fetching {len(coordinates)} elevation points")

    # Fetch elevations from API
    should_close = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=60.0)

    try:
        # Batch into chunks of 100
        elevations_dict = {}
        batch_size = 100

        for i in range(0, len(coordinates), batch_size):
            batch = coordinates[i:i + batch_size]

            response = await client.post(
                "https://api.open-elevation.com/api/v1/lookup",
                json={"locations": batch}
            )
            response.raise_for_status()

            results = response.json().get("results", [])
            for j, result in enumerate(results):
                coord = batch[j]
                key = (coord["latitude"], coord["longitude"])
                elevations_dict[key] = result.get("elevation", 0)

        # Create sparse elevation grid from samples
        sparse_elevation = np.zeros((len(sample_rows), len(sample_cols)))
        for i, row in enumerate(sample_rows):
            for j, col in enumerate(sample_cols):
                lat, lon = cell_to_latlon(row, col, bounds)
                sparse_elevation[i, j] = elevations_dict.get((lat, lon), 0)

        # Interpolate to full resolution using scipy zoom
        from scipy.ndimage import zoom

        zoom_factors = (bounds.rows / len(sample_rows), bounds.cols / len(sample_cols))
        elevation = zoom(sparse_elevation, zoom_factors, order=1)

        # Ensure correct shape
        elevation = elevation[:bounds.rows, :bounds.cols]

        logger.info(f"[RASTER] DEM created: shape={elevation.shape}, "
                   f"min={elevation.min():.1f}m, max={elevation.max():.1f}m")

        return elevation

    finally:
        if should_close:
            await client.aclose()


def calculate_slope(elevation: np.ndarray, resolution: float) -> np.ndarray:
    """Calculate slope in degrees from elevation DEM.

    Uses gradient calculation with proper scaling for resolution.
    """
    # Calculate gradients in x and y directions
    gy, gx = np.gradient(elevation, resolution)

    # Calculate slope magnitude
    slope_rad = np.arctan(np.sqrt(gx**2 + gy**2))
    slope_deg = np.degrees(slope_rad)

    logger.info(f"[RASTER] Slope calculated: min={slope_deg.min():.1f}°, "
               f"max={slope_deg.max():.1f}°, mean={slope_deg.mean():.1f}°")

    return slope_deg


def create_cost_surface(
    bounds: RasterBounds,
    osm_data: dict
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create cost surface from OSM data.

    Returns:
        cost: Running cost grid (lower = better for running)
        parks: Park mask
        trails: Trail mask
    """
    rows, cols = bounds.rows, bounds.cols

    # Initialize grids
    cost = np.full((rows, cols), 10.0)  # Default medium cost
    parks = np.zeros((rows, cols), dtype=np.uint8)
    trails = np.zeros((rows, cols), dtype=np.uint8)

    # Cost values (lower = better for running)
    COST_VALUES = {
        'park': 1.0,
        'trail': 1.5,
        'path': 2.0,
        'footway': 2.0,
        'cycleway': 3.0,
        'pedestrian': 3.0,
        'residential': 5.0,
        'living_street': 4.0,
        'service': 6.0,
        'unclassified': 7.0,
        'tertiary': 8.0,
        'secondary': 15.0,
        'primary': 25.0,
        'trunk': 50.0,
        'motorway': 100.0,
        'water': 999.0,
        'building': 999.0,
    }

    # Process park areas
    if 'parks' in osm_data:
        for park in osm_data['parks']:
            if 'geometry' in park:
                rasterize_polygon(park['geometry'], parks, bounds, value=1)
                rasterize_polygon(park['geometry'], cost, bounds, value=COST_VALUES['park'])

    # Process trails and paths
    if 'edges' in osm_data:
        for edge in osm_data['edges']:
            highway = edge.get('highway', '')
            if highway in COST_VALUES:
                cost_val = COST_VALUES[highway]
            else:
                cost_val = 10.0

            if 'geometry' in edge:
                rasterize_line(edge['geometry'], cost, bounds, value=cost_val)

                # Mark trails
                if highway in ['path', 'footway', 'track', 'cycleway']:
                    rasterize_line(edge['geometry'], trails, bounds, value=1)

    logger.info(f"[RASTER] Cost surface created: "
               f"park_cells={parks.sum()}, trail_cells={trails.sum()}")

    return cost, parks, trails


def rasterize_polygon(
    coords: List[Tuple[float, float]],
    grid: np.ndarray,
    bounds: RasterBounds,
    value: float
):
    """Rasterize a polygon onto a grid."""
    from skimage.draw import polygon as draw_polygon

    # Convert coordinates to cell indices
    rows = []
    cols = []
    for lat, lon in coords:
        row, col = latlon_to_cell(lat, lon, bounds)
        rows.append(row)
        cols.append(col)

    if len(rows) < 3:
        return

    # Fill polygon
    try:
        rr, cc = draw_polygon(rows, cols, shape=grid.shape)
        grid[rr, cc] = value
    except Exception as e:
        logger.warning(f"[RASTER] Failed to rasterize polygon: {e}")


def rasterize_line(
    coords: List[Tuple[float, float]],
    grid: np.ndarray,
    bounds: RasterBounds,
    value: float,
    width: int = 1
):
    """Rasterize a line onto a grid."""
    from skimage.draw import line as draw_line

    for i in range(len(coords) - 1):
        lat1, lon1 = coords[i]
        lat2, lon2 = coords[i + 1]

        r1, c1 = latlon_to_cell(lat1, lon1, bounds)
        r2, c2 = latlon_to_cell(lat2, lon2, bounds)

        try:
            rr, cc = draw_line(r1, c1, r2, c2)
            # Clip to grid bounds
            valid = (rr >= 0) & (rr < grid.shape[0]) & (cc >= 0) & (cc < grid.shape[1])
            grid[rr[valid], cc[valid]] = value
        except Exception:
            pass


def cost_distance_with_elevation(
    cost: np.ndarray,
    elevation: np.ndarray,
    start_cell: Tuple[int, int],
    resolution: float,
    max_distance_m: float = None
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Multi-dimensional cost-distance accumulation.

    Computes accumulated distance, elevation gain, and elevation loss
    from the start cell to all reachable cells.

    Returns:
        distance_grid: Accumulated distance in meters
        gain_grid: Accumulated elevation gain in meters
        loss_grid: Accumulated elevation loss in meters
    """
    rows, cols = cost.shape

    # Initialize output grids
    distance_grid = np.full((rows, cols), np.inf)
    gain_grid = np.full((rows, cols), np.inf)
    loss_grid = np.full((rows, cols), np.inf)

    # Track parent for path reconstruction
    parent = {}

    # Start cell initialization
    start_row, start_col = start_cell
    distance_grid[start_row, start_col] = 0
    gain_grid[start_row, start_col] = 0
    loss_grid[start_row, start_col] = 0

    # Priority queue: (priority, row, col, distance, gain, loss)
    # Priority combines distance and terrain cost
    queue = [(0, start_row, start_col, 0, 0, 0)]

    # 8-directional neighbors
    neighbors = [
        (-1, 0, 1.0),    # N
        (1, 0, 1.0),     # S
        (0, -1, 1.0),    # W
        (0, 1, 1.0),     # E
        (-1, -1, 1.414), # NW
        (-1, 1, 1.414),  # NE
        (1, -1, 1.414),  # SW
        (1, 1, 1.414),   # SE
    ]

    visited = set()

    while queue:
        priority, row, col, dist, gain, loss = heappop(queue)

        if (row, col) in visited:
            continue
        visited.add((row, col))

        # Early termination if we've exceeded max distance
        if max_distance_m and dist > max_distance_m:
            continue

        current_elev = elevation[row, col]

        for dr, dc, diag_factor in neighbors:
            nr, nc = row + dr, col + dc

            # Bounds check
            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue

            if (nr, nc) in visited:
                continue

            # Skip impassable cells
            if cost[nr, nc] >= 100:
                continue

            # Calculate movement metrics
            move_dist = resolution * diag_factor
            neighbor_elev = elevation[nr, nc]
            elev_change = neighbor_elev - current_elev

            # Accumulate elevation gain/loss
            new_gain = gain + max(0, elev_change)
            new_loss = loss + max(0, -elev_change)
            new_dist = dist + move_dist

            # Calculate priority (combines distance and terrain cost)
            terrain_cost = cost[nr, nc]
            slope_penalty = 1 + abs(elev_change) / move_dist * 0.5 if move_dist > 0 else 1
            new_priority = new_dist * terrain_cost * slope_penalty

            # Update if better path found
            if new_dist < distance_grid[nr, nc]:
                distance_grid[nr, nc] = new_dist
                gain_grid[nr, nc] = new_gain
                loss_grid[nr, nc] = new_loss
                parent[(nr, nc)] = (row, col)
                heappush(queue, (new_priority, nr, nc, new_dist, new_gain, new_loss))

    logger.info(f"[RASTER] Cost-distance computed: visited {len(visited)} cells, "
               f"max_dist={distance_grid[distance_grid < np.inf].max():.0f}m")

    return distance_grid, gain_grid, loss_grid


def find_loop_candidates(
    distance_grid: np.ndarray,
    gain_grid: np.ndarray,
    start_cell: Tuple[int, int],
    target_distance_m: float,
    target_gain_m: float = None,
    tolerance: float = 0.15
) -> List[Tuple[int, int]]:
    """Find cells that could form loops matching the criteria.

    These are cells at approximately half the target distance that
    could form a complete loop back to start.
    """
    # Look for cells at approximately target_distance / 2
    # (outbound leg of the loop)
    half_dist = target_distance_m / 2
    min_half = half_dist * (1 - tolerance)
    max_half = half_dist * (1 + tolerance)

    # Distance criteria
    distance_match = (distance_grid >= min_half) & (distance_grid <= max_half)

    # Elevation gain criteria (if specified)
    if target_gain_m is not None and target_gain_m > 0:
        half_gain = target_gain_m / 2
        min_gain = half_gain * (1 - tolerance * 2)  # More lenient on elevation
        max_gain = half_gain * (1 + tolerance * 2)
        gain_match = (gain_grid >= min_gain) & (gain_grid <= max_gain)
        candidates_mask = distance_match & gain_match
    else:
        candidates_mask = distance_match

    # Get candidate cells
    candidates = np.argwhere(candidates_mask)

    logger.info(f"[RASTER] Found {len(candidates)} loop candidates at ~{half_dist:.0f}m")

    return [tuple(c) for c in candidates]


def detect_park_boundaries(
    parks: np.ndarray,
    elevation: np.ndarray,
    bounds: RasterBounds,
    target_distance_m: float,
    target_gain_m: float = None,
    tolerance: float = 0.15
) -> List[RouteCandidate]:
    """Detect park perimeters that match the target criteria.

    This is key for finding obvious routes like Central Park!
    """
    routes = []

    # Label connected park regions
    labeled, num_parks = ndimage.label(parks)

    logger.info(f"[RASTER] Analyzing {num_parks} park regions for boundary loops")

    for park_id in range(1, num_parks + 1):
        park_mask = (labeled == park_id)

        # Skip tiny parks
        if park_mask.sum() < 100:  # Less than ~10,000 sq meters
            continue

        # Find park boundary using contour detection
        contours = measure.find_contours(park_mask.astype(float), 0.5)

        for contour in contours:
            if len(contour) < 10:
                continue

            # Calculate perimeter distance
            perimeter_m = 0
            for i in range(len(contour)):
                r1, c1 = contour[i]
                r2, c2 = contour[(i + 1) % len(contour)]

                # Distance in cells * resolution
                cell_dist = np.sqrt((r2 - r1)**2 + (c2 - c1)**2)
                perimeter_m += cell_dist * bounds.resolution

            # Check if perimeter matches target distance
            if abs(perimeter_m - target_distance_m) > target_distance_m * tolerance:
                continue

            # Calculate elevation profile along boundary
            elevations = []
            for r, c in contour:
                ri, ci = int(r), int(c)
                if 0 <= ri < elevation.shape[0] and 0 <= ci < elevation.shape[1]:
                    elevations.append(elevation[ri, ci])

            if not elevations:
                continue

            # Calculate elevation metrics
            total_gain = 0
            total_loss = 0
            for i in range(1, len(elevations)):
                diff = elevations[i] - elevations[i - 1]
                if diff > 0:
                    total_gain += diff
                else:
                    total_loss += abs(diff)

            # Check elevation gain criteria
            if target_gain_m is not None and target_gain_m > 0:
                if abs(total_gain - target_gain_m) > target_gain_m * tolerance:
                    continue

            # Convert contour to path cells and coordinates
            path_cells = [(int(r), int(c)) for r, c in contour]
            path_coords = [cell_to_latlon(int(r), int(c), bounds) for r, c in contour]

            # Analyze hill distribution
            distribution = analyze_hill_distribution(elevations)

            # Calculate match score
            dist_match = 1 - abs(perimeter_m - target_distance_m) / target_distance_m
            if target_gain_m and target_gain_m > 0:
                gain_match = 1 - abs(total_gain - target_gain_m) / target_gain_m
                score = (dist_match * 0.5 + gain_match * 0.5) * 100
            else:
                score = dist_match * 100

            routes.append(RouteCandidate(
                path_cells=path_cells,
                path_coords=path_coords,
                distance_m=perimeter_m,
                elevation_gain_m=total_gain,
                elevation_loss_m=total_loss,
                elevation_profile=elevations,
                hill_distribution=distribution,
                score=score
            ))

            logger.info(f"[RASTER] Found park boundary loop: "
                       f"dist={perimeter_m:.0f}m, gain={total_gain:.0f}m, score={score:.0f}")

    # Sort by score
    routes.sort(key=lambda r: r.score, reverse=True)

    return routes


def analyze_hill_distribution(elevations: List[float]) -> str:
    """Analyze the distribution of hills over a route.

    Returns classification:
    - 'flat': Minimal elevation change
    - 'rolling': Many small hills evenly distributed
    - 'front_loaded': Big climbs early
    - 'back_loaded': Big climbs late
    - 'climb_descent': Steady climb then descent
    """
    if not elevations or len(elevations) < 3:
        return 'flat'

    # Calculate cumulative gain at different segments
    n = len(elevations)
    third = n // 3

    def segment_gain(start_idx, end_idx):
        gain = 0
        for i in range(start_idx + 1, min(end_idx, len(elevations))):
            diff = elevations[i] - elevations[i - 1]
            if diff > 0:
                gain += diff
        return gain

    gain_first = segment_gain(0, third)
    gain_middle = segment_gain(third, 2 * third)
    gain_last = segment_gain(2 * third, n)

    total_gain = gain_first + gain_middle + gain_last

    # Classify based on gain distribution
    if total_gain < 20:  # Less than 20m total gain
        return 'flat'

    # Check for front-loaded (most gain in first third)
    if gain_first > total_gain * 0.5:
        return 'front_loaded'

    # Check for back-loaded (most gain in last third)
    if gain_last > total_gain * 0.5:
        return 'back_loaded'

    # Check for climb-descent pattern
    mid_point = n // 2
    first_half_trend = elevations[mid_point] - elevations[0]
    second_half_trend = elevations[-1] - elevations[mid_point]

    if first_half_trend > total_gain * 0.3 and second_half_trend < -total_gain * 0.3:
        return 'climb_descent'

    # Count local maxima for rolling detection
    local_maxima = 0
    for i in range(1, n - 1):
        if elevations[i] > elevations[i - 1] and elevations[i] > elevations[i + 1]:
            local_maxima += 1

    if local_maxima >= 3:
        return 'rolling'

    return 'rolling'  # Default to rolling


def trace_route_astar(
    cost: np.ndarray,
    elevation: np.ndarray,
    start_cell: Tuple[int, int],
    end_cell: Tuple[int, int],
    resolution: float
) -> Tuple[List[Tuple[int, int]], List[float], float]:
    """Trace optimal route using A* with elevation awareness.

    Returns:
        path: List of (row, col) cells
        elevations: Elevation at each point
        distance: Total distance in meters
    """
    rows, cols = cost.shape
    start_row, start_col = start_cell
    end_row, end_col = end_cell

    def heuristic(r1, c1, r2, c2):
        """Euclidean distance heuristic."""
        return np.sqrt((r2 - r1)**2 + (c2 - c1)**2) * resolution

    # A* search
    came_from = {}
    g_score = {start_cell: 0}
    f_score = {start_cell: heuristic(start_row, start_col, end_row, end_col)}

    queue = [(f_score[start_cell], start_cell)]

    neighbors = [
        (-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
        (-1, -1, 1.414), (-1, 1, 1.414), (1, -1, 1.414), (1, 1, 1.414),
    ]

    while queue:
        _, current = heappop(queue)

        if current == end_cell:
            # Reconstruct path
            path = []
            while current in came_from:
                path.append(current)
                current = came_from[current]
            path.append(start_cell)
            path.reverse()

            # Extract elevations and calculate distance
            elevations = [elevation[r, c] for r, c in path]
            distance = sum(
                np.sqrt((path[i+1][0] - path[i][0])**2 +
                       (path[i+1][1] - path[i][1])**2) * resolution
                for i in range(len(path) - 1)
            )

            return path, elevations, distance

        cr, cc = current

        for dr, dc, diag_factor in neighbors:
            nr, nc = cr + dr, cc + dc
            neighbor = (nr, nc)

            if nr < 0 or nr >= rows or nc < 0 or nc >= cols:
                continue

            if cost[nr, nc] >= 100:  # Impassable
                continue

            # Calculate movement cost
            move_dist = resolution * diag_factor
            elev_change = elevation[nr, nc] - elevation[cr, cc]
            slope_cost = 1 + abs(elev_change) / move_dist * 0.3 if move_dist > 0 else 1

            tentative_g = g_score[current] + move_dist * cost[nr, nc] * slope_cost

            if tentative_g < g_score.get(neighbor, np.inf):
                came_from[neighbor] = current
                g_score[neighbor] = tentative_g
                f = tentative_g + heuristic(nr, nc, end_row, end_col)
                f_score[neighbor] = f
                heappush(queue, (f, neighbor))

    # No path found
    return [], [], 0


class RasterRouteFinder:
    """Main class for raster-based route finding."""

    def __init__(
        self,
        center_lat: float,
        center_lon: float,
        radius_m: float,
        resolution: float = DEFAULT_RESOLUTION
    ):
        self.bounds = create_bounds_from_center(
            center_lat, center_lon, radius_m, resolution
        )
        self.layers: Optional[RasterLayers] = None
        self.osm_data: Optional[dict] = None

    async def initialize(self, osm_data: dict = None):
        """Initialize raster layers with OSM data and elevation."""
        logger.info(f"[RASTER] Initializing {self.bounds.rows}x{self.bounds.cols} grid "
                   f"at {self.bounds.resolution}m resolution")

        # Download elevation DEM
        elevation = await download_elevation_dem(self.bounds)

        # Calculate slope
        slope = calculate_slope(elevation, self.bounds.resolution)

        # Create cost surface from OSM data
        if osm_data:
            self.osm_data = osm_data
            cost, parks, trails = create_cost_surface(self.bounds, osm_data)
        else:
            # Default cost surface (uniform)
            cost = np.full((self.bounds.rows, self.bounds.cols), 5.0)
            parks = np.zeros((self.bounds.rows, self.bounds.cols), dtype=np.uint8)
            trails = np.zeros((self.bounds.rows, self.bounds.cols), dtype=np.uint8)

        self.layers = RasterLayers(
            bounds=self.bounds,
            elevation=elevation,
            cost=cost,
            slope=slope,
            parks=parks,
            trails=trails
        )

        logger.info("[RASTER] Initialization complete")

    async def find_routes(
        self,
        start_lat: float,
        start_lon: float,
        target_distance_m: float,
        target_gain_m: float = None,
        target_profile: dict = None,
        num_routes: int = 10,
        tolerance: float = 0.15
    ) -> List[RouteCandidate]:
        """Find routes matching the specified criteria.

        Args:
            start_lat: Starting latitude
            start_lon: Starting longitude
            target_distance_m: Target distance in meters
            target_gain_m: Target elevation gain in meters (optional)
            target_profile: Target elevation profile characteristics (optional)
            num_routes: Maximum number of routes to return
            tolerance: Acceptable deviation from targets (0.15 = 15%)

        Returns:
            List of RouteCandidate objects sorted by match score
        """
        if self.layers is None:
            raise ValueError("RasterRouteFinder not initialized. Call initialize() first.")

        routes = []

        # Convert start location to cell
        start_cell = latlon_to_cell(start_lat, start_lon, self.bounds)
        logger.info(f"[RASTER] Finding routes from cell {start_cell}")

        # STRATEGY 1: Check park boundary loops first (fast!)
        # This catches obvious routes like Central Park
        park_routes = detect_park_boundaries(
            self.layers.parks,
            self.layers.elevation,
            self.bounds,
            target_distance_m,
            target_gain_m,
            tolerance
        )
        routes.extend(park_routes)

        if len(routes) >= num_routes:
            logger.info(f"[RASTER] Found {len(routes)} park boundary routes")
            return routes[:num_routes]

        # STRATEGY 2: Multi-dimensional cost-distance search
        logger.info("[RASTER] Running cost-distance analysis...")
        distance_grid, gain_grid, loss_grid = cost_distance_with_elevation(
            self.layers.cost,
            self.layers.elevation,
            start_cell,
            self.bounds.resolution,
            max_distance_m=target_distance_m * 1.5
        )

        # Find loop candidates
        candidates = find_loop_candidates(
            distance_grid,
            gain_grid,
            start_cell,
            target_distance_m,
            target_gain_m,
            tolerance
        )

        # Trace routes through candidates
        for end_cell in candidates[:50]:  # Limit candidates
            # Trace outbound path
            path_out, elev_out, dist_out = trace_route_astar(
                self.layers.cost,
                self.layers.elevation,
                start_cell,
                end_cell,
                self.bounds.resolution
            )

            if not path_out:
                continue

            # Trace return path
            path_back, elev_back, dist_back = trace_route_astar(
                self.layers.cost,
                self.layers.elevation,
                end_cell,
                start_cell,
                self.bounds.resolution
            )

            if not path_back:
                continue

            # Combine into loop
            full_path = path_out + path_back[1:]  # Avoid duplicating midpoint
            full_elev = elev_out + elev_back[1:]
            total_dist = dist_out + dist_back

            # Check distance match
            if abs(total_dist - target_distance_m) > target_distance_m * tolerance:
                continue

            # Calculate elevation metrics
            total_gain = sum(max(0, full_elev[i] - full_elev[i-1])
                           for i in range(1, len(full_elev)))
            total_loss = sum(max(0, full_elev[i-1] - full_elev[i])
                           for i in range(1, len(full_elev)))

            # Check elevation gain match
            if target_gain_m and target_gain_m > 0:
                if abs(total_gain - target_gain_m) > target_gain_m * tolerance:
                    continue

            # Analyze hill distribution
            distribution = analyze_hill_distribution(full_elev)

            # Calculate score
            dist_match = 1 - abs(total_dist - target_distance_m) / target_distance_m
            if target_gain_m and target_gain_m > 0:
                gain_match = 1 - abs(total_gain - target_gain_m) / target_gain_m
                score = (dist_match * 0.5 + gain_match * 0.5) * 100
            else:
                score = dist_match * 100

            # Bonus for matching target profile
            if target_profile and target_profile.get('pattern'):
                if distribution == target_profile['pattern']:
                    score += 10

            # Convert path to coordinates
            path_coords = [cell_to_latlon(r, c, self.bounds) for r, c in full_path]

            routes.append(RouteCandidate(
                path_cells=full_path,
                path_coords=path_coords,
                distance_m=total_dist,
                elevation_gain_m=total_gain,
                elevation_loss_m=total_loss,
                elevation_profile=full_elev,
                hill_distribution=distribution,
                score=score
            ))

        # Sort by score and return top routes
        routes.sort(key=lambda r: r.score, reverse=True)

        # Deduplicate similar routes
        unique_routes = []
        for route in routes:
            is_duplicate = False
            for existing in unique_routes:
                # Check if routes are too similar
                if abs(route.distance_m - existing.distance_m) < 100:
                    if abs(route.elevation_gain_m - existing.elevation_gain_m) < 20:
                        is_duplicate = True
                        break

            if not is_duplicate:
                unique_routes.append(route)

            if len(unique_routes) >= num_routes:
                break

        logger.info(f"[RASTER] Found {len(unique_routes)} unique routes")

        return unique_routes
