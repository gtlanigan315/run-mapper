"""Route finder using OSMnx for generating candidate running routes."""

import math
import random
from typing import List, Optional, Sequence, Tuple

import networkx as nx
import osmnx as ox


class RouteFinderError(Exception):
    """Error from the route finder."""

    pass


def find_candidate_routes(
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    num_routes: int = 10,
    distance_tolerance: float = 0.3,
) -> List[List[Tuple[float, float]]]:
    """Find candidate running routes near a location.

    Uses multiple strategies to generate diverse routes:
    1. Directional exploration (N, NE, E, SE, S, SW, W, NW)
    2. Various loop shapes
    3. Out-and-back routes
    4. Multi-waypoint loops

    Args:
        center_lat: Center latitude
        center_lon: Center longitude
        target_distance_km: Target route distance in kilometers
        num_routes: Number of candidate routes to generate
        distance_tolerance: Acceptable distance deviation (0.3 = 30%)

    Returns:
        List of routes, where each route is a list of (lat, lon) coordinates

    Raises:
        RouteFinderError: If route generation fails
    """
    try:
        # Calculate search radius - need larger area to find good routes
        search_radius_m = max((target_distance_km * 1000) * 0.75, 1500)

        # Download the street network (walkable/runnable paths)
        G = ox.graph_from_point(
            (center_lat, center_lon),
            dist=search_radius_m,
            network_type="walk",
            simplify=True,
        )

        if G.number_of_nodes() < 10:
            raise RouteFinderError("Not enough road network data in this area")

        # Find the node closest to center
        center_node = ox.distance.nearest_nodes(G, center_lon, center_lat)

        # Distance bounds
        min_distance_km = target_distance_km * (1 - distance_tolerance)
        max_distance_km = target_distance_km * (1 + distance_tolerance)

        routes = []

        # Strategy 1: Directional loops - explore 4 main compass directions
        directions = [0, 90, 180, 270]  # N, E, S, W
        for direction in directions:
            route = _generate_directional_loop(
                G, center_node, center_lat, center_lon,
                target_distance_km, min_distance_km, max_distance_km,
                direction, direction_spread=45
            )
            if route:
                routes.append(route)

        # Strategy 2: Out-and-back routes (3 directions)
        for direction in [0, 120, 240]:
            route = _generate_out_and_back(
                G, center_node, center_lat, center_lon,
                target_distance_km, min_distance_km, max_distance_km,
                direction
            )
            if route:
                routes.append(route)

        # Strategy 3: Random multi-waypoint loops
        attempts = 0
        max_attempts = 20
        while len(routes) < 15 and attempts < max_attempts:
            attempts += 1
            try:
                route = _generate_random_loop(
                    G, center_node, target_distance_km, min_distance_km, max_distance_km
                )
                if route:
                    routes.append(route)
            except (nx.NetworkXNoPath, nx.NodeNotFound):
                continue

        if not routes:
            raise RouteFinderError("Could not generate any valid routes in this area")

        # Remove duplicates (routes that are too similar)
        unique_routes = _deduplicate_routes(routes)

        return unique_routes

    except ox._errors.InsufficientResponseError:
        raise RouteFinderError("No road network data available for this location")
    except Exception as e:
        if isinstance(e, RouteFinderError):
            raise
        raise RouteFinderError(f"Route finding failed: {e}") from e


def _get_node_at_bearing(
    G: nx.MultiDiGraph,
    center_node: int,
    center_lat: float,
    center_lon: float,
    bearing: float,
    target_distance_m: float,
) -> Optional[int]:
    """Find a node approximately at a given bearing and distance from center.

    Args:
        G: NetworkX graph
        center_node: Starting node
        center_lat: Center latitude
        center_lon: Center longitude
        bearing: Direction in degrees (0 = North, 90 = East)
        target_distance_m: Target distance from center in meters

    Returns:
        Node ID or None if not found
    """
    # Calculate target coordinates
    bearing_rad = math.radians(bearing)

    # Approximate meters per degree at this latitude
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * math.cos(math.radians(center_lat))

    delta_lat = (target_distance_m * math.cos(bearing_rad)) / m_per_deg_lat
    delta_lon = (target_distance_m * math.sin(bearing_rad)) / m_per_deg_lon

    target_lat = center_lat + delta_lat
    target_lon = center_lon + delta_lon

    # Find nearest node to target
    try:
        return ox.distance.nearest_nodes(G, target_lon, target_lat)
    except Exception:
        return None


def _generate_directional_loop(
    G: nx.MultiDiGraph,
    start_node: int,
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    min_distance_km: float,
    max_distance_km: float,
    primary_direction: float,
    direction_spread: float = 30,
) -> Optional[List[Tuple[float, float]]]:
    """Generate a loop that primarily goes in a specific direction.

    Creates a teardrop or lollipop shaped route.
    """
    target_distance_m = target_distance_km * 1000

    # First waypoint: go out in the primary direction
    outbound_distance = target_distance_m * random.uniform(0.25, 0.4)
    wp1 = _get_node_at_bearing(
        G, start_node, center_lat, center_lon,
        primary_direction + random.uniform(-direction_spread/2, direction_spread/2),
        outbound_distance
    )
    if not wp1 or wp1 == start_node:
        return None

    # Second waypoint: continue but curve to one side
    side = random.choice([-1, 1])
    wp2 = _get_node_at_bearing(
        G, start_node, center_lat, center_lon,
        primary_direction + side * random.uniform(45, 90),
        outbound_distance * random.uniform(0.8, 1.2)
    )
    if not wp2 or wp2 == start_node:
        return None

    # Build path
    try:
        path1 = nx.shortest_path(G, start_node, wp1, weight="length")
        path2 = nx.shortest_path(G, wp1, wp2, weight="length")
        path3 = nx.shortest_path(G, wp2, start_node, weight="length")

        route_nodes = path1 + path2[1:] + path3[1:]

        return _validate_and_convert_route(G, route_nodes, min_distance_km, max_distance_km)
    except nx.NetworkXNoPath:
        return None


def _generate_out_and_back(
    G: nx.MultiDiGraph,
    start_node: int,
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    min_distance_km: float,
    max_distance_km: float,
    direction: float,
) -> Optional[List[Tuple[float, float]]]:
    """Generate an out-and-back route (same path out and back)."""
    target_distance_m = target_distance_km * 1000

    # Find a turnaround point at half the target distance
    turnaround_distance = target_distance_m / 2

    turnaround_node = _get_node_at_bearing(
        G, start_node, center_lat, center_lon,
        direction,
        turnaround_distance * random.uniform(0.9, 1.1)
    )

    if not turnaround_node or turnaround_node == start_node:
        return None

    try:
        outbound = nx.shortest_path(G, start_node, turnaround_node, weight="length")
        # Return path is reverse
        route_nodes = outbound + list(reversed(outbound[:-1]))

        return _validate_and_convert_route(G, route_nodes, min_distance_km, max_distance_km)
    except nx.NetworkXNoPath:
        return None


def _generate_figure_eight(
    G: nx.MultiDiGraph,
    start_node: int,
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    min_distance_km: float,
    max_distance_km: float,
    direction: float,
) -> Optional[List[Tuple[float, float]]]:
    """Generate a figure-8 shaped route (two connected loops)."""
    target_distance_m = target_distance_km * 1000
    loop_radius = target_distance_m / 8  # Each loop is about 1/4 of total distance

    # First loop waypoints
    wp1 = _get_node_at_bearing(
        G, start_node, center_lat, center_lon,
        direction,
        loop_radius
    )
    wp2 = _get_node_at_bearing(
        G, start_node, center_lat, center_lon,
        direction + 90,
        loop_radius
    )

    # Second loop waypoints (opposite direction)
    wp3 = _get_node_at_bearing(
        G, start_node, center_lat, center_lon,
        direction + 180,
        loop_radius
    )
    wp4 = _get_node_at_bearing(
        G, start_node, center_lat, center_lon,
        direction + 270,
        loop_radius
    )

    if not all([wp1, wp2, wp3, wp4]):
        return None

    try:
        # First loop
        p1 = nx.shortest_path(G, start_node, wp1, weight="length")
        p2 = nx.shortest_path(G, wp1, wp2, weight="length")
        p3 = nx.shortest_path(G, wp2, start_node, weight="length")

        # Second loop
        p4 = nx.shortest_path(G, start_node, wp3, weight="length")
        p5 = nx.shortest_path(G, wp3, wp4, weight="length")
        p6 = nx.shortest_path(G, wp4, start_node, weight="length")

        route_nodes = p1 + p2[1:] + p3[1:] + p4[1:] + p5[1:] + p6[1:]

        return _validate_and_convert_route(G, route_nodes, min_distance_km, max_distance_km)
    except nx.NetworkXNoPath:
        return None


def _generate_random_loop(
    G: nx.MultiDiGraph,
    start_node: int,
    target_distance_km: float,
    min_distance_km: float,
    max_distance_km: float,
) -> Optional[List[Tuple[float, float]]]:
    """Generate a loop route with random waypoints (original algorithm)."""
    nodes = list(G.nodes())
    if len(nodes) < 3:
        return None

    # Pick random intermediate waypoints
    num_waypoints = random.randint(2, 5)
    available_nodes = [n for n in nodes if n != start_node]
    if len(available_nodes) < num_waypoints:
        return None

    waypoint_nodes = random.sample(available_nodes, num_waypoints)

    # Build the route: start -> waypoint1 -> waypoint2 -> ... -> start
    route_nodes = [start_node]
    current_node = start_node

    for waypoint in waypoint_nodes:
        try:
            path = nx.shortest_path(G, current_node, waypoint, weight="length")
            route_nodes.extend(path[1:])
            current_node = waypoint
        except nx.NetworkXNoPath:
            return None

    # Close the loop
    try:
        path = nx.shortest_path(G, current_node, start_node, weight="length")
        route_nodes.extend(path[1:])
    except nx.NetworkXNoPath:
        return None

    return _validate_and_convert_route(G, route_nodes, min_distance_km, max_distance_km)


def _validate_and_convert_route(
    G: nx.MultiDiGraph,
    route_nodes: List[int],
    min_distance_km: float,
    max_distance_km: float,
) -> Optional[List[Tuple[float, float]]]:
    """Validate route distance and convert to coordinates."""
    # Calculate total distance
    total_distance_m = 0.0
    for i in range(len(route_nodes) - 1):
        edge_data = G.get_edge_data(route_nodes[i], route_nodes[i + 1])
        if edge_data:
            first_edge = list(edge_data.values())[0]
            total_distance_m += first_edge.get("length", 0)

    total_distance_km = total_distance_m / 1000

    # Check if distance is within tolerance
    if min_distance_km <= total_distance_km <= max_distance_km:
        # Convert node IDs to coordinates
        coords = []
        for node in route_nodes:
            node_data = G.nodes[node]
            coords.append((node_data["y"], node_data["x"]))  # lat, lon
        return coords

    return None


def _deduplicate_routes(
    routes: List[List[Tuple[float, float]]],
    similarity_threshold: float = 0.8,
) -> List[List[Tuple[float, float]]]:
    """Remove routes that are too similar to each other.

    Uses a simple overlap metric based on shared coordinates.
    """
    if len(routes) <= 1:
        return routes

    unique_routes = [routes[0]]

    for route in routes[1:]:
        is_unique = True
        route_set = set(route)

        for existing_route in unique_routes:
            existing_set = set(existing_route)

            # Calculate Jaccard similarity
            intersection = len(route_set & existing_set)
            union = len(route_set | existing_set)

            if union > 0 and intersection / union > similarity_threshold:
                is_unique = False
                break

        if is_unique:
            unique_routes.append(route)

    return unique_routes


def get_route_distance_km(coordinates: Sequence[Tuple[float, float]]) -> float:
    """Calculate the total distance of a route in kilometers.

    Args:
        coordinates: List of (lat, lon) coordinates

    Returns:
        Total distance in kilometers
    """
    from run_mapper.core.gpx_parser import haversine_distance

    total_distance = 0.0
    for i in range(len(coordinates) - 1):
        lat1, lon1 = coordinates[i]
        lat2, lon2 = coordinates[i + 1]
        total_distance += haversine_distance(lat1, lon1, lat2, lon2)

    return total_distance


def interpolate_route(
    coordinates: Sequence[Tuple[float, float]],
    interval_m: float = 50.0,
) -> List[Tuple[float, float]]:
    """Interpolate a route to have evenly spaced points.

    Args:
        coordinates: List of (lat, lon) coordinates
        interval_m: Target interval between points in meters

    Returns:
        Interpolated route with evenly spaced points
    """
    from run_mapper.core.gpx_parser import haversine_distance

    if len(coordinates) < 2:
        return list(coordinates)

    interpolated = [coordinates[0]]
    interval_km = interval_m / 1000

    for i in range(1, len(coordinates)):
        lat1, lon1 = coordinates[i - 1]
        lat2, lon2 = coordinates[i]
        segment_distance = haversine_distance(lat1, lon1, lat2, lon2)

        if segment_distance == 0:
            continue

        # How many points to add in this segment
        points_in_segment = int(segment_distance / interval_km)

        for j in range(1, points_in_segment + 1):
            ratio = j / (points_in_segment + 1)
            new_lat = lat1 + ratio * (lat2 - lat1)
            new_lon = lon1 + ratio * (lon2 - lon1)
            interpolated.append((new_lat, new_lon))

        interpolated.append(coordinates[i])

    return interpolated
