"""Route finder using OSMnx for generating candidate running routes."""

import logging
import math
import random
from typing import Dict, List, Optional, Sequence, Set, Tuple

import networkx as nx
import osmnx as ox

logger = logging.getLogger(__name__)


class RouteFinderError(Exception):
    """Error from the route finder."""

    pass


# OSM highway tags that are good for running (in order of preference)
RUNNER_FRIENDLY_HIGHWAYS = [
    'path', 'footway', 'cycleway', 'pedestrian', 'track',
    'living_street', 'residential', 'service', 'unclassified',
]

# Tags that indicate park/trail paths
PARK_TRAIL_TAGS = {'path', 'footway', 'track', 'cycleway'}

# Tags for finding landmarks/parks via ox.features_from_point()
LANDMARK_TAGS = {
    'leisure': ['park', 'nature_reserve', 'garden'],
    'landuse': ['recreation_ground', 'forest'],
    'natural': ['wood', 'grassland'],
}


def _find_landmarks_and_parks(
    center_lat: float,
    center_lon: float,
    radius_m: float,
) -> List[Dict]:
    """Query OSM for parks, trails, and named paths using ox.features_from_point().

    Args:
        center_lat: Center latitude
        center_lon: Center longitude
        radius_m: Search radius in meters

    Returns:
        List of landmark dictionaries with 'name', 'lat', 'lon', 'type' keys
    """
    landmarks = []

    try:
        # Query for leisure features (parks, etc.)
        for tag_key, tag_values in LANDMARK_TAGS.items():
            try:
                tags = {tag_key: tag_values}
                gdf = ox.features_from_point(
                    (center_lat, center_lon),
                    tags=tags,
                    dist=radius_m,
                )

                if gdf is not None and len(gdf) > 0:
                    for idx, row in gdf.iterrows():
                        # Get centroid for polygon features
                        if hasattr(row.geometry, 'centroid'):
                            centroid = row.geometry.centroid
                            lat, lon = centroid.y, centroid.x
                        else:
                            lat, lon = row.geometry.y, row.geometry.x

                        name = row.get('name', None)
                        if name:  # Only include named features
                            landmarks.append({
                                'name': name,
                                'lat': lat,
                                'lon': lon,
                                'type': tag_key,
                            })
            except Exception as e:
                logger.warning(f"[LANDMARKS] Failed to query {tag_key}: {e}")
                continue

    except Exception as e:
        logger.warning(f"[LANDMARKS] Feature query failed: {e}")

    # Deduplicate by name
    seen_names = set()
    unique_landmarks = []
    for lm in landmarks:
        if lm['name'] not in seen_names:
            seen_names.add(lm['name'])
            unique_landmarks.append(lm)

    logger.warning(f"[LANDMARKS] Found {len(unique_landmarks)} named landmarks/parks")
    return unique_landmarks


def _generate_landmark_loops(
    G: nx.MultiDiGraph,
    start_node: int,
    landmarks: List[Dict],
    target_distance_m: float,
    min_distance_m: float,
    max_distance_m: float,
    max_loops: int = 10,
) -> List[List[int]]:
    """Generate routes that pass through named landmarks/parks.

    Args:
        G: NetworkX graph
        start_node: Starting node
        landmarks: List of landmark dictionaries from _find_landmarks_and_parks()
        target_distance_m: Target distance in meters
        min_distance_m: Minimum acceptable distance
        max_distance_m: Maximum acceptable distance
        max_loops: Maximum number of loops to generate

    Returns:
        List of node sequences representing loops through landmarks
    """
    if not landmarks:
        return []

    loops = []
    weight_attr = _get_routing_weight(G)

    # Find the nearest graph node for each landmark
    landmark_nodes = []
    for lm in landmarks:
        try:
            node = ox.distance.nearest_nodes(G, lm['lon'], lm['lat'])
            if node != start_node:
                landmark_nodes.append((node, lm['name']))
        except Exception:
            continue

    if len(landmark_nodes) < 1:
        return []

    logger.warning(f"[LANDMARKS] Mapped {len(landmark_nodes)} landmarks to graph nodes")

    # Strategy 1: Single landmark loops
    for lm_node, lm_name in landmark_nodes[:5]:
        try:
            path_to = nx.shortest_path(G, start_node, lm_node, weight=weight_attr)
            path_back = nx.shortest_path(G, lm_node, start_node, weight=weight_attr)

            route_nodes = path_to + path_back[1:]

            # Calculate distance
            total_distance = 0
            for i in range(len(route_nodes) - 1):
                edge_data = G.get_edge_data(route_nodes[i], route_nodes[i + 1])
                if edge_data:
                    total_distance += list(edge_data.values())[0].get('length', 0)

            if min_distance_m <= total_distance <= max_distance_m:
                loops.append(route_nodes)
                logger.warning(f"[LANDMARKS] Created loop through '{lm_name}' ({total_distance/1000:.1f}km)")

            if len(loops) >= max_loops:
                return loops

        except nx.NetworkXNoPath:
            continue

    # Strategy 2: Multi-landmark loops (visit 2 landmarks)
    if len(landmark_nodes) >= 2 and len(loops) < max_loops:
        for i, (lm1_node, lm1_name) in enumerate(landmark_nodes[:4]):
            for lm2_node, lm2_name in landmark_nodes[i + 1:5]:
                if len(loops) >= max_loops:
                    return loops

                try:
                    path1 = nx.shortest_path(G, start_node, lm1_node, weight=weight_attr)
                    path2 = nx.shortest_path(G, lm1_node, lm2_node, weight=weight_attr)
                    path3 = nx.shortest_path(G, lm2_node, start_node, weight=weight_attr)

                    route_nodes = path1 + path2[1:] + path3[1:]

                    total_distance = 0
                    for j in range(len(route_nodes) - 1):
                        edge_data = G.get_edge_data(route_nodes[j], route_nodes[j + 1])
                        if edge_data:
                            total_distance += list(edge_data.values())[0].get('length', 0)

                    if min_distance_m <= total_distance <= max_distance_m:
                        loops.append(route_nodes)
                        logger.warning(f"[LANDMARKS] Created loop through '{lm1_name}' and '{lm2_name}'")

                except nx.NetworkXNoPath:
                    continue

    return loops


def _score_edge_for_running(edge_data: Dict) -> float:
    """Score an edge based on how good it is for running.

    Higher score = better for running.
    """
    highway = edge_data.get('highway', '')

    # Handle lists (OSM sometimes has multiple values)
    if isinstance(highway, list):
        highway = highway[0] if highway else ''

    # Base score by highway type
    if highway in PARK_TRAIL_TAGS:
        score = 1.0  # Best - dedicated paths
    elif highway in ['residential', 'living_street']:
        score = 0.7  # Good - quiet streets
    elif highway in ['pedestrian', 'service', 'unclassified']:
        score = 0.5  # Okay
    elif highway in ['tertiary', 'secondary']:
        score = 0.2  # Not great - busier roads
    elif highway in ['primary', 'trunk']:
        score = 0.0  # Avoid - major roads
    else:
        score = 0.3  # Unknown - assume okay

    # Bonus for named paths (often indicates a trail)
    if edge_data.get('name') and highway in PARK_TRAIL_TAGS:
        score += 0.1

    return min(score, 1.0)


def _extract_running_network(G: nx.MultiDiGraph, min_score: float = 0.5) -> nx.MultiDiGraph:
    """Extract a subgraph containing only running-quality paths.

    This filters out busy roads and keeps only trails, paths, and quiet streets.

    Args:
        G: Full OSM graph
        min_score: Minimum running score threshold (0-1)

    Returns:
        Filtered graph with only running-quality edges
    """
    # Identify edges to keep
    edges_to_keep = []
    for u, v, key, data in G.edges(keys=True, data=True):
        score = _score_edge_for_running(data)
        if score >= min_score:
            edges_to_keep.append((u, v, key))

    # Create subgraph
    if not edges_to_keep:
        # If nothing passes the threshold, lower it
        return _extract_running_network(G, min_score * 0.7) if min_score > 0.2 else G

    # Build the subgraph by keeping only the good edges
    running_G = G.edge_subgraph(edges_to_keep).copy()

    return running_G


def _find_running_corridors(G: nx.MultiDiGraph) -> List[Set[int]]:
    """Find connected running corridors in the graph.

    Returns list of node sets, each representing a connected running network.
    Sorted by size (largest first).
    """
    # Convert to undirected for component finding
    undirected = G.to_undirected()
    components = list(nx.connected_components(undirected))

    # Sort by size, largest first
    components.sort(key=len, reverse=True)

    return components


def _find_corridor_loops(
    G: nx.MultiDiGraph,
    corridor_nodes: Set[int],
    start_node: int,
    target_distance_m: float,
    min_distance_m: float,
    max_distance_m: float,
    max_loops: int = 10,
) -> List[List[int]]:
    """Find loops within a running corridor.

    Args:
        G: Graph (should be the running network)
        corridor_nodes: Nodes in this corridor
        start_node: Starting node (must be in corridor)
        target_distance_m: Target distance
        min_distance_m: Min acceptable distance
        max_distance_m: Max acceptable distance
        max_loops: Max loops to find

    Returns:
        List of node sequences representing loops
    """
    if start_node not in corridor_nodes:
        return []

    # Create subgraph for this corridor
    corridor_G = G.subgraph(corridor_nodes).copy()

    if corridor_G.number_of_nodes() < 5:
        return []

    loops = []

    # Strategy 1: Find simple cycles that include start_node
    try:
        # Get all simple cycles (can be slow, so limit)
        cycle_generator = nx.simple_cycles(corridor_G)
        cycles_checked = 0
        for cycle in cycle_generator:
            cycles_checked += 1
            if cycles_checked > 500:  # Limit iterations
                break

            if start_node not in cycle:
                continue

            # Calculate distance
            total_dist = 0
            for i in range(len(cycle)):
                u = cycle[i]
                v = cycle[(i + 1) % len(cycle)]
                edge_data = corridor_G.get_edge_data(u, v)
                if edge_data:
                    total_dist += list(edge_data.values())[0].get('length', 0)

            if min_distance_m <= total_dist <= max_distance_m:
                # Rotate cycle to start with start_node
                start_idx = cycle.index(start_node)
                rotated = cycle[start_idx:] + cycle[:start_idx] + [start_node]
                loops.append(rotated)

                if len(loops) >= max_loops:
                    break

    except Exception:
        pass  # Cycle finding can fail on some graphs

    # Strategy 2: DFS-based loop finding (backup)
    if len(loops) < max_loops // 2:
        dfs_loops = _dfs_find_loops(
            corridor_G, start_node, target_distance_m, min_distance_m, max_distance_m,
            max_loops - len(loops)
        )
        loops.extend(dfs_loops)

    return loops[:max_loops]


def _dfs_find_loops(
    G: nx.MultiDiGraph,
    start_node: int,
    target_distance_m: float,
    min_distance_m: float,
    max_distance_m: float,
    max_loops: int,
) -> List[List[int]]:
    """Find loops using depth-first search."""
    loops = []

    def dfs(current: int, path: List[int], distance: float, visited: Set[int]):
        nonlocal loops

        if len(loops) >= max_loops:
            return

        # Check if we can close the loop
        if len(path) > 3 and G.has_edge(current, start_node):
            edge_data = G.get_edge_data(current, start_node)
            if edge_data:
                close_dist = list(edge_data.values())[0].get('length', 0)
                total = distance + close_dist
                if min_distance_m <= total <= max_distance_m:
                    loops.append(path + [start_node])
                    return

        # Stop if we've gone too far
        if distance > max_distance_m * 1.2:
            return

        # Explore neighbors
        neighbors = list(G.neighbors(current))
        random.shuffle(neighbors)

        for neighbor in neighbors[:5]:  # Limit branching
            if neighbor in visited and neighbor != start_node:
                continue

            edge_data = G.get_edge_data(current, neighbor)
            if not edge_data:
                continue

            edge_length = list(edge_data.values())[0].get('length', 0)
            new_dist = distance + edge_length

            if new_dist <= max_distance_m * 1.5:
                new_visited = visited | {neighbor}
                dfs(neighbor, path + [neighbor], new_dist, new_visited)

    # Start DFS from neighbors of start_node
    for neighbor in G.neighbors(start_node):
        if len(loops) >= max_loops:
            break
        edge_data = G.get_edge_data(start_node, neighbor)
        if edge_data:
            edge_length = list(edge_data.values())[0].get('length', 0)
            dfs(neighbor, [start_node, neighbor], edge_length, {start_node, neighbor})

    return loops


def find_routes_smart(
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    num_routes: int = 10,
    distance_tolerance: float = 0.15,
    popular_paths: Optional[List[List[Tuple[float, float]]]] = None,
) -> List[List[Tuple[float, float]]]:
    """Find running routes using the smart area-first approach.

    This approach:
    1. Downloads the OSM network
    2. Extracts only running-quality paths (trails, quiet streets)
    3. Identifies running corridors (connected networks of good paths)
    4. Finds loops within these corridors
    5. Incorporates Strava segment data to prefer popular routes

    Args:
        center_lat: Center latitude
        center_lon: Center longitude
        target_distance_km: Target route distance in kilometers
        num_routes: Number of routes to find
        distance_tolerance: Acceptable distance deviation (0.15 = 15%)
        popular_paths: Optional Strava segment coordinates

    Returns:
        List of routes as coordinate lists
    """
    search_radius_m = max((target_distance_km * 1000) * 0.5, 1000)

    # Step 1: Download full network
    logger.warning("[SMART] Step 1: Downloading area network...")
    G = ox.graph_from_point(
        (center_lat, center_lon),
        dist=search_radius_m,
        network_type="walk",
        simplify=True,
    )

    if G.number_of_nodes() < 10:
        raise RouteFinderError("Not enough road network data in this area")

    # Step 2: Extract running-quality network (only trails, paths - not residential)
    logger.warning("[SMART] Step 2: Extracting running-quality paths...")
    running_G = _extract_running_network(G, min_score=0.8)
    logger.warning(f"[SMART] Running network: {running_G.number_of_nodes()} nodes, {running_G.number_of_edges()} edges")

    # Step 3: Apply Strava popularity weighting if available
    if popular_paths:
        logger.warning("[SMART] Step 3: Applying Strava popularity data...")
        running_G = _apply_popularity_weights(running_G, popular_paths)

    # Step 4: Find running corridors
    logger.warning("[SMART] Step 4: Finding running corridors...")
    corridors = _find_running_corridors(running_G)
    logger.warning(f"[SMART] Found {len(corridors)} corridors, largest has {len(corridors[0]) if corridors else 0} nodes")

    # Find start node
    center_node = ox.distance.nearest_nodes(G, center_lon, center_lat)

    # Try to find start node in running network, or find nearest
    if center_node not in running_G.nodes():
        # Find nearest node that is in the running network
        min_dist = float('inf')
        nearest_running_node = None
        center_coords = (center_lat, center_lon)
        for node in running_G.nodes():
            node_lat = running_G.nodes[node]['y']
            node_lon = running_G.nodes[node]['x']
            dist = ((node_lat - center_lat)**2 + (node_lon - center_lon)**2)**0.5
            if dist < min_dist:
                min_dist = dist
                nearest_running_node = node
        if nearest_running_node:
            center_node = nearest_running_node
        else:
            logger.warning("[SMART] Could not find start node in running network, falling back")
            return find_candidate_routes(center_lat, center_lon, target_distance_km, num_routes, distance_tolerance, popular_paths)

    # Distance bounds
    target_distance_m = target_distance_km * 1000
    min_distance_m = target_distance_km * (1 - distance_tolerance) * 1000
    max_distance_m = target_distance_km * (1 + distance_tolerance) * 1000

    routes = []

    # Step 5: Find loops in the main corridor
    logger.warning("[SMART] Step 5: Finding loops in running corridors...")
    for i, corridor in enumerate(corridors[:5]):  # Check top 5 corridors
        if center_node not in corridor:
            continue

        # Skip corridors that are too large (cycle finding is slow)
        if len(corridor) > 5000:
            logger.warning(f"[SMART] Corridor {i+1} too large ({len(corridor)} nodes), using DFS only")
            # For large corridors, only use DFS (faster)
            corridor_G = running_G.subgraph(corridor).copy()
            corridor_loops = _dfs_find_loops(
                corridor_G, center_node, target_distance_m, min_distance_m, max_distance_m,
                max_loops=num_routes
            )
        else:
            corridor_loops = _find_corridor_loops(
                running_G, corridor, center_node,
                target_distance_m, min_distance_m, max_distance_m,
                max_loops=num_routes
            )

        for loop_nodes in corridor_loops:
            coords = [(running_G.nodes[n]['y'], running_G.nodes[n]['x']) for n in loop_nodes]
            routes.append(coords)

        logger.warning(f"[SMART] Corridor {i+1}: found {len(corridor_loops)} loops")

        if len(routes) >= num_routes:
            break

    # Step 6: If not enough routes, also search in full graph with running preference
    if len(routes) < num_routes // 2:
        logger.warning("[SMART] Step 6: Supplementing with weighted full-graph search...")
        supplemental = _find_natural_loops(
            G, center_node, target_distance_m, min_distance_m, max_distance_m,
            max_loops=num_routes - len(routes)
        )
        for loop_nodes in supplemental:
            coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in loop_nodes]
            routes.append(coords)

    logger.warning(f"[SMART] Total routes found: {len(routes)}")

    if not routes:
        # Fall back to original approach
        logger.warning("[SMART] No routes found, falling back to original approach")
        return find_candidate_routes(center_lat, center_lon, target_distance_km, num_routes, distance_tolerance, popular_paths)

    # Deduplicate
    unique_routes = _deduplicate_routes(routes)

    # Cap the number of candidates to limit elevation API calls
    MAX_CANDIDATES = 20
    unique_routes = unique_routes[:MAX_CANDIDATES]

    return unique_routes


def _find_natural_loops(
    G: nx.MultiDiGraph,
    start_node: int,
    target_distance_m: float,
    min_distance_m: float,
    max_distance_m: float,
    max_loops: int = 10,
) -> List[List[int]]:
    """Find natural loops in the graph using DFS.

    Searches for cycles that:
    - Start and end at the start_node
    - Are within the distance bounds
    - Prefer edges that are good for running

    Args:
        G: NetworkX graph
        start_node: Starting node
        target_distance_m: Target loop distance in meters
        min_distance_m: Minimum acceptable distance
        max_distance_m: Maximum acceptable distance
        max_loops: Maximum number of loops to find

    Returns:
        List of node sequences representing loops
    """
    loops = []

    # Calculate running score for each edge (higher = better for running)
    edge_scores = {}
    for u, v, key, data in G.edges(keys=True, data=True):
        edge_scores[(u, v, key)] = _score_edge_for_running(data)

    # DFS to find loops
    def dfs(current: int, path: List[int], distance: float, visited_edges: Set):
        nonlocal loops

        if len(loops) >= max_loops:
            return

        # Check if we can close the loop
        if len(path) > 3 and current != start_node:
            # Check if there's an edge back to start
            if G.has_edge(current, start_node):
                edge_data = G.get_edge_data(current, start_node)
                if edge_data:
                    first_edge = list(edge_data.values())[0]
                    closing_distance = distance + first_edge.get('length', 0)

                    if min_distance_m <= closing_distance <= max_distance_m:
                        loops.append(path + [start_node])
                        return

        # Don't go too far
        if distance > max_distance_m:
            return

        # Limit path length to avoid infinite loops
        if len(path) > 200:
            return

        # Get neighbors sorted by running score (best first)
        neighbors = []
        for neighbor in G.neighbors(current):
            edge_data = G.get_edge_data(current, neighbor)
            if edge_data:
                for key, data in edge_data.items():
                    edge_id = (current, neighbor, key)
                    if edge_id not in visited_edges:
                        score = edge_scores.get(edge_id, 0.5)
                        length = data.get('length', 0)
                        neighbors.append((neighbor, key, data, score, length))

        # Sort by score (descending) to explore best paths first
        neighbors.sort(key=lambda x: x[3], reverse=True)

        # Limit branching to avoid exponential blowup
        for neighbor, key, data, score, length in neighbors[:5]:
            edge_id = (current, neighbor, key)
            new_distance = distance + length

            # Prune if we're already past target and moving away from start
            if new_distance > target_distance_m * 0.6:
                # Check if we're getting closer to start
                # (simple heuristic: prefer moving toward start after halfway)
                pass

            visited_edges.add(edge_id)
            dfs(neighbor, path + [neighbor], new_distance, visited_edges)
            visited_edges.remove(edge_id)

    # Start DFS from the start node
    dfs(start_node, [start_node], 0, set())

    return loops


def _find_high_centrality_loops(
    G: nx.MultiDiGraph,
    start_node: int,
    target_distance_m: float,
    min_distance_m: float,
    max_distance_m: float,
) -> List[List[int]]:
    """Find loops that use high-degree nodes (popular intersections).

    Uses node degree as a fast proxy for popularity - nodes with many
    connections are likely important intersections.
    """
    # Use degree (fast) instead of betweenness centrality (slow)
    try:
        degree_dict = dict(G.degree())
        sorted_nodes = sorted(degree_dict.items(), key=lambda x: x[1], reverse=True)
        # Get top 20 nodes with at least 3 connections
        high_degree_nodes = [n for n, d in sorted_nodes[:40] if d >= 3][:20]
    except:
        return []

    if len(high_degree_nodes) < 2:
        return []

    logger.warning(f"[DEGREE] Found {len(high_degree_nodes)} high-degree nodes")

    loops = []
    weight_attr = _get_routing_weight(G)

    # For each high-degree node, try to find a loop through it
    for hd_node in high_degree_nodes[:8]:
        try:
            # Path from start to high-degree node
            path_to = nx.shortest_path(G, start_node, hd_node, weight=weight_attr)

            # Find another high-degree node to route through
            for other_node in high_degree_nodes:
                if other_node == hd_node or other_node == start_node:
                    continue

                try:
                    path_middle = nx.shortest_path(G, hd_node, other_node, weight=weight_attr)
                    path_back = nx.shortest_path(G, other_node, start_node, weight=weight_attr)

                    # Combine paths
                    full_path = path_to + path_middle[1:] + path_back[1:]

                    # Calculate distance
                    total_distance = 0
                    for i in range(len(full_path) - 1):
                        edge_data = G.get_edge_data(full_path[i], full_path[i+1])
                        if edge_data:
                            total_distance += list(edge_data.values())[0].get('length', 0)

                    if min_distance_m <= total_distance <= max_distance_m:
                        loops.append(full_path)

                    # Limit loops per starting node
                    if len([l for l in loops if hd_node in l]) >= 3:
                        break

                except nx.NetworkXNoPath:
                    continue

        except nx.NetworkXNoPath:
            continue

        # Stop if we have enough loops
        if len(loops) >= 15:
            break

    return loops


def find_candidate_routes(
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    num_routes: int = 10,
    distance_tolerance: float = 0.15,
    popular_paths: Optional[List[List[Tuple[float, float]]]] = None,
) -> List[List[Tuple[float, float]]]:
    """Find candidate running routes near a location.

    Uses multiple strategies to generate diverse routes:
    1. Directional exploration (N, NE, E, SE, S, SW, W, NW)
    2. Various loop shapes
    3. Out-and-back routes
    4. Multi-waypoint loops

    If popular_paths (e.g., from Strava segments) are provided, the routing
    will prefer edges that are near those popular running corridors.

    Args:
        center_lat: Center latitude
        center_lon: Center longitude
        target_distance_km: Target route distance in kilometers
        num_routes: Number of candidate routes to generate
        distance_tolerance: Acceptable distance deviation (0.3 = 30%)
        popular_paths: Optional list of coordinate lists from popular routes
            (e.g., Strava segments). Used to weight the graph to prefer
            paths where runners actually run.

    Returns:
        List of routes, where each route is a list of (lat, lon) coordinates

    Raises:
        RouteFinderError: If route generation fails
    """
    try:
        # Calculate search radius - reduced for faster queries
        search_radius_m = max((target_distance_km * 1000) * 0.5, 1000)

        # Download the street network (walkable/runnable paths)
        G = ox.graph_from_point(
            (center_lat, center_lon),
            dist=search_radius_m,
            network_type="walk",
            simplify=True,
        )

        if G.number_of_nodes() < 10:
            raise RouteFinderError("Not enough road network data in this area")

        # Apply popularity weighting if we have popular paths data
        # Uses KD-tree for efficient O(E × log S) performance
        if popular_paths:
            G = _apply_popularity_weights(G, popular_paths)

        # Find the node closest to center
        center_node = ox.distance.nearest_nodes(G, center_lon, center_lat)

        # Distance bounds
        min_distance_km = target_distance_km * (1 - distance_tolerance)
        max_distance_km = target_distance_km * (1 + distance_tolerance)

        routes = []
        target_distance_m = target_distance_km * 1000
        min_distance_m = min_distance_km * 1000
        max_distance_m = max_distance_km * 1000

        # STRATEGY 1 (HIGHEST PRIORITY): Find natural loops in the graph
        # These are real loops that exist in the road network
        logger.warning("[ROUTE] Strategy 1: Finding natural loops...")
        natural_loops = _find_natural_loops(
            G, center_node, target_distance_m, min_distance_m, max_distance_m, max_loops=5
        )
        for loop_nodes in natural_loops:
            coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in loop_nodes]
            routes.append(coords)
        logger.warning(f"[ROUTE] Found {len(natural_loops)} natural loops")

        # STRATEGY 2: Find loops using high-degree nodes (popular intersections)
        logger.warning("[ROUTE] Strategy 2: Finding loops through popular intersections...")
        degree_loops = _find_high_centrality_loops(
            G, center_node, target_distance_m, min_distance_m, max_distance_m
        )
        for loop_nodes in degree_loops:
            coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in loop_nodes]
            routes.append(coords)
        logger.warning(f"[ROUTE] Found {len(degree_loops)} intersection-based loops")

        # STRATEGY 3: Trace along Strava segments continuously
        if popular_paths:
            logger.warning("[ROUTE] Strategy 3: Tracing Strava segments...")
            traced_routes = _trace_continuous_popular_paths(
                center_lat, center_lon,
                target_distance_km, min_distance_km, max_distance_km,
                popular_paths
            )
            routes.extend(traced_routes)

        # STRATEGY 4: Find loops through popular Strava nodes
        if popular_paths:
            logger.warning("[ROUTE] Strategy 4: Finding loops through Strava nodes...")
            popular_routes = _generate_popular_path_loops(
                G, center_node, center_lat, center_lon,
                target_distance_km, min_distance_km, max_distance_km,
                popular_paths
            )
            routes.extend(popular_routes)

        # STRATEGY 5: Find loops through named landmarks/parks (skip if we already have enough routes)
        if len(routes) < num_routes:
            try:
                logger.warning("[ROUTE] Strategy 5: Finding loops through landmarks...")
                landmarks = _find_landmarks_and_parks(center_lat, center_lon, search_radius_m)
                if landmarks:
                    landmark_loops = _generate_landmark_loops(
                        G, center_node, landmarks,
                        target_distance_m, min_distance_m, max_distance_m,
                        max_loops=3  # Reduced for speed
                    )
                    for loop_nodes in landmark_loops:
                        coords = [(G.nodes[n]['y'], G.nodes[n]['x']) for n in loop_nodes]
                        routes.append(coords)
                    logger.warning(f"[ROUTE] Found {len(landmark_loops)} landmark-based loops")
            except Exception as e:
                logger.warning(f"[ROUTE] Landmark search failed (non-fatal): {e}")

        logger.warning(f"[ROUTE] Total routes before dedup: {len(routes)}")

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
        path1 = nx.shortest_path(G, start_node, wp1, weight=_get_routing_weight(G))
        path2 = nx.shortest_path(G, wp1, wp2, weight=_get_routing_weight(G))
        path3 = nx.shortest_path(G, wp2, start_node, weight=_get_routing_weight(G))

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
        outbound = nx.shortest_path(G, start_node, turnaround_node, weight=_get_routing_weight(G))
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
        p1 = nx.shortest_path(G, start_node, wp1, weight=_get_routing_weight(G))
        p2 = nx.shortest_path(G, wp1, wp2, weight=_get_routing_weight(G))
        p3 = nx.shortest_path(G, wp2, start_node, weight=_get_routing_weight(G))

        # Second loop
        p4 = nx.shortest_path(G, start_node, wp3, weight=_get_routing_weight(G))
        p5 = nx.shortest_path(G, wp3, wp4, weight=_get_routing_weight(G))
        p6 = nx.shortest_path(G, wp4, start_node, weight=_get_routing_weight(G))

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
            path = nx.shortest_path(G, current_node, waypoint, weight=_get_routing_weight(G))
            route_nodes.extend(path[1:])
            current_node = waypoint
        except nx.NetworkXNoPath:
            return None

    # Close the loop
    try:
        path = nx.shortest_path(G, current_node, start_node, weight=_get_routing_weight(G))
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


def _trace_continuous_popular_paths(
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    min_distance_km: float,
    max_distance_km: float,
    popular_paths: List[List[Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    """Generate routes by tracing along popular paths continuously.

    Instead of using waypoints and shortest paths (which cut across),
    this chains Strava segments together by their endpoints to form
    continuous routes that follow actual popular running paths.

    Args:
        center_lat: Center latitude (starting point)
        center_lon: Center longitude (starting point)
        target_distance_km: Target distance in km
        min_distance_km: Minimum acceptable distance
        max_distance_km: Maximum acceptable distance
        popular_paths: List of coordinate lists from Strava segments

    Returns:
        List of routes as coordinate lists
    """
    import logging
    from run_mapper.core.gpx_parser import haversine_distance

    logger = logging.getLogger(__name__)
    routes = []

    if not popular_paths or len(popular_paths) < 2:
        return routes

    # Calculate the distance of each segment
    segment_info = []
    for i, path in enumerate(popular_paths):
        if len(path) < 2:
            continue

        # Calculate segment distance
        dist = 0.0
        for j in range(1, len(path)):
            dist += haversine_distance(path[j-1][0], path[j-1][1], path[j][0], path[j][1])

        segment_info.append({
            'id': i,
            'path': path,
            'start': path[0],
            'end': path[-1],
            'distance_km': dist,
        })

    if len(segment_info) < 2:
        return routes

    logger.warning(f"[TRACE] Processing {len(segment_info)} segments for continuous tracing")

    # Find segments that start near the center point (potential starting segments)
    starting_segments = []
    for seg in segment_info:
        start_dist = haversine_distance(center_lat, center_lon, seg['start'][0], seg['start'][1])
        end_dist = haversine_distance(center_lat, center_lon, seg['end'][0], seg['end'][1])
        min_dist = min(start_dist, end_dist)
        if min_dist < target_distance_km * 0.3:  # Within 30% of target as radius
            starting_segments.append((seg, min_dist, start_dist < end_dist))

    # Sort by distance from center
    starting_segments.sort(key=lambda x: x[1])

    # Try to build loops starting from different segments
    connection_threshold_km = 0.15  # 150m to connect segments

    for start_seg, _, start_from_start in starting_segments[:5]:  # Try top 5 closest
        # Try building a loop
        for try_reverse in [False, True]:
            used_segments = {start_seg['id']}
            current_path = list(start_seg['path'])
            if try_reverse:
                current_path = list(reversed(current_path))

            total_distance = start_seg['distance_km']
            current_end = current_path[-1]

            # Greedily add segments until we reach target distance or can't continue
            max_iterations = 20
            for _ in range(max_iterations):
                if total_distance >= target_distance_km:
                    break

                # Find the best next segment to connect
                best_next = None
                best_connection_dist = float('inf')
                best_reversed = False

                for seg in segment_info:
                    if seg['id'] in used_segments:
                        continue

                    # Check if this segment's start connects to our current end
                    dist_to_start = haversine_distance(
                        current_end[0], current_end[1],
                        seg['start'][0], seg['start'][1]
                    )
                    dist_to_end = haversine_distance(
                        current_end[0], current_end[1],
                        seg['end'][0], seg['end'][1]
                    )

                    if dist_to_start < connection_threshold_km and dist_to_start < best_connection_dist:
                        best_next = seg
                        best_connection_dist = dist_to_start
                        best_reversed = False
                    elif dist_to_end < connection_threshold_km and dist_to_end < best_connection_dist:
                        best_next = seg
                        best_connection_dist = dist_to_end
                        best_reversed = True

                if best_next is None:
                    break

                # Add the segment
                used_segments.add(best_next['id'])
                next_path = list(best_next['path'])
                if best_reversed:
                    next_path = list(reversed(next_path))

                current_path.extend(next_path)
                current_end = current_path[-1]
                total_distance += best_next['distance_km']

            # Check if we can close the loop (end near start)
            loop_start = current_path[0]
            loop_end = current_path[-1]
            closing_distance = haversine_distance(
                loop_start[0], loop_start[1],
                loop_end[0], loop_end[1]
            )

            # If close enough to close, and distance is in range, add it
            if closing_distance < 0.3:  # Within 300m of start
                # Close the loop by adding start point
                current_path.append(loop_start)
                total_distance += closing_distance

                if min_distance_km <= total_distance <= max_distance_km:
                    logger.warning(f"[TRACE] Found continuous loop: {total_distance:.2f}km with {len(used_segments)} segments")
                    routes.append(current_path)

            # Also check if the path (even not closed) is in range
            elif min_distance_km <= total_distance <= max_distance_km:
                # Try to close it by walking back to start
                return_distance = haversine_distance(
                    current_end[0], current_end[1],
                    center_lat, center_lon
                )
                if total_distance + return_distance <= max_distance_km:
                    # Add return to center
                    current_path.append((center_lat, center_lon))
                    routes.append(current_path)

    logger.warning(f"[TRACE] Generated {len(routes)} routes from continuous tracing")
    return routes


def _generate_popular_path_loops(
    G: nx.MultiDiGraph,
    start_node: int,
    center_lat: float,
    center_lon: float,
    target_distance_km: float,
    min_distance_km: float,
    max_distance_km: float,
    popular_paths: List[List[Tuple[float, float]]],
) -> List[List[Tuple[float, float]]]:
    """Generate loops that follow popular running paths.

    Finds nodes along popular paths and constructs loops through them,
    ensuring routes stay on popular corridors.

    Uses bulk nearest_nodes lookup for O(n) performance instead of O(n²).

    Args:
        G: NetworkX graph
        start_node: Starting node
        center_lat: Center latitude
        center_lon: Center longitude
        target_distance_km: Target distance in km
        min_distance_km: Minimum acceptable distance
        max_distance_km: Maximum acceptable distance
        popular_paths: List of coordinate lists from Strava segments

    Returns:
        List of routes as coordinate lists
    """
    import logging
    import numpy as np

    logger = logging.getLogger(__name__)
    routes = []

    if not popular_paths:
        return routes

    # Collect all coordinates from popular paths, sampling to limit size
    all_coords = []
    for path in popular_paths:
        # Sample every 5th point to reduce while keeping coverage
        for i in range(0, len(path), 5):
            all_coords.append(path[i])

    if len(all_coords) < 3:
        return routes

    # Limit to a reasonable number
    if len(all_coords) > 200:
        indices = np.linspace(0, len(all_coords) - 1, 200, dtype=int)
        all_coords = [all_coords[i] for i in indices]

    # Extract lats and lons for bulk lookup
    lats = np.array([c[0] for c in all_coords])
    lons = np.array([c[1] for c in all_coords])

    # Bulk nearest nodes lookup - much faster than individual calls
    try:
        nodes = ox.distance.nearest_nodes(G, lons, lats)
        popular_nodes = list(set(nodes))
    except Exception as e:
        logger.warning(f"[ROUTE] Failed to find popular nodes: {e}")
        return routes

    logger.warning(f"[ROUTE] Found {len(popular_nodes)} nodes along popular paths")

    if len(popular_nodes) < 3:
        return routes

    # Sort popular nodes by distance from center to find good waypoint candidates
    from run_mapper.core.gpx_parser import haversine_distance

    def node_distance_from_center(node):
        node_data = G.nodes[node]
        return haversine_distance(center_lat, center_lon, node_data["y"], node_data["x"])

    popular_nodes_sorted = sorted(popular_nodes, key=node_distance_from_center)

    # Try different combinations of popular nodes as waypoints
    weight_attr = _get_routing_weight(G)

    for attempt in range(min(5, len(popular_nodes_sorted))):
        try:
            # Pick waypoints at different distances from center
            quarter_dist = target_distance_km / 4
            half_dist = target_distance_km / 2

            # Find nodes at approximately these distances
            waypoints = []
            for target_dist in [quarter_dist, half_dist, quarter_dist * 3]:
                best_node = None
                best_diff = float('inf')
                for node in popular_nodes_sorted:
                    dist = node_distance_from_center(node)
                    diff = abs(dist - target_dist)
                    if diff < best_diff and node not in waypoints and node != start_node:
                        best_diff = diff
                        best_node = node
                if best_node:
                    waypoints.append(best_node)

            if len(waypoints) < 2:
                continue

            # Build loop through waypoints
            route_nodes = []
            current = start_node

            for wp in waypoints:
                try:
                    path = nx.shortest_path(G, current, wp, weight=weight_attr)
                    if route_nodes:
                        route_nodes.extend(path[1:])
                    else:
                        route_nodes.extend(path)
                    current = wp
                except nx.NetworkXNoPath:
                    break

            # Close the loop
            try:
                path = nx.shortest_path(G, current, start_node, weight=weight_attr)
                route_nodes.extend(path[1:])
            except nx.NetworkXNoPath:
                continue

            # Validate and convert
            result = _validate_and_convert_route(G, route_nodes, min_distance_km, max_distance_km)
            if result:
                routes.append(result)

            # Shuffle popular nodes to try different combinations
            random.shuffle(popular_nodes_sorted)

        except Exception:
            continue

    # Strategy B: Use popular nodes as intermediate waypoints in directional loops
    for direction in [0, 90, 180, 270]:  # Reduced directions for speed
        try:
            # Find a popular node roughly in this direction
            best_node = None
            best_score = -1

            for node in popular_nodes:
                node_data = G.nodes[node]
                node_lat, node_lon = node_data["y"], node_data["x"]

                # Calculate bearing from center to node
                dlat = node_lat - center_lat
                dlon = node_lon - center_lon
                bearing = math.degrees(math.atan2(dlon, dlat)) % 360

                # Score based on bearing match and distance
                bearing_diff = min(abs(bearing - direction), 360 - abs(bearing - direction))
                dist = node_distance_from_center(node)

                if bearing_diff < 60 and 0.1 < dist < target_distance_km * 0.6:
                    score = (60 - bearing_diff) / 60 * dist
                    if score > best_score:
                        best_score = score
                        best_node = node

            if best_node is None:
                continue

            # Build a lollipop loop: go to popular node, loop around, come back
            try:
                outbound = nx.shortest_path(G, start_node, best_node, weight=weight_attr)

                # Find another popular node near the first one
                other_nodes = [n for n in popular_nodes if n != best_node and n != start_node]
                if other_nodes:
                    other_node = random.choice(other_nodes[:10])
                    loop_path = nx.shortest_path(G, best_node, other_node, weight=weight_attr)
                    return_path = nx.shortest_path(G, other_node, start_node, weight=weight_attr)

                    route_nodes = outbound + loop_path[1:] + return_path[1:]
                    result = _validate_and_convert_route(G, route_nodes, min_distance_km, max_distance_km)
                    if result:
                        routes.append(result)
            except nx.NetworkXNoPath:
                continue

        except Exception:
            continue

    return routes


def _apply_popularity_weights(
    G: nx.MultiDiGraph,
    popular_paths: List[List[Tuple[float, float]]],
    popularity_boost: float = 0.3,
    proximity_threshold_m: float = 50.0,
) -> nx.MultiDiGraph:
    """Apply popularity-based weights to graph edges.

    Edges that are near popular running paths (e.g., Strava segments) get
    a lower routing cost, making them more likely to be chosen.

    Uses a KD-tree for O(E × log S) performance instead of O(E × S).

    Args:
        G: NetworkX graph with nodes having 'x' (lon) and 'y' (lat) attributes
        popular_paths: List of coordinate lists from popular routes
        popularity_boost: How much to reduce cost for popular edges (0.3 = 30% cheaper)
        proximity_threshold_m: Distance threshold in meters to consider "near"

    Returns:
        Modified graph with 'routing_weight' attribute on edges
    """
    import numpy as np
    from scipy.spatial import cKDTree

    if not popular_paths:
        return G

    # Build a flat array of all popular path coordinates
    popular_coords = []
    for path in popular_paths:
        popular_coords.extend(path)

    if not popular_coords:
        return G

    # Convert to numpy array (lat, lon)
    coords_array = np.array(popular_coords)

    # Get the center latitude for degree-to-meter conversion
    center_lat = np.mean(coords_array[:, 0])

    # Approximate meters per degree at this latitude
    m_per_deg_lat = 111320
    m_per_deg_lon = 111320 * np.cos(np.radians(center_lat))

    # Convert coordinates to approximate meters for the KD-tree
    # This allows us to use euclidean distance in meters
    coords_meters = np.column_stack([
        coords_array[:, 0] * m_per_deg_lat,
        coords_array[:, 1] * m_per_deg_lon
    ])

    # Build KD-tree for fast proximity queries
    tree = cKDTree(coords_meters)

    # For each edge, check if it's near a popular path
    for u, v, key, data in G.edges(keys=True, data=True):
        edge_length = data.get("length", 100)  # Default 100m if missing

        # Get edge midpoint
        u_data = G.nodes[u]
        v_data = G.nodes[v]
        mid_lat = (u_data["y"] + v_data["y"]) / 2
        mid_lon = (u_data["x"] + v_data["x"]) / 2

        # Convert midpoint to meters
        mid_meters = np.array([mid_lat * m_per_deg_lat, mid_lon * m_per_deg_lon])

        # Query KD-tree for nearest point within threshold
        distance, _ = tree.query(mid_meters, distance_upper_bound=proximity_threshold_m)

        # Check if edge is near any popular path point
        is_popular = distance < proximity_threshold_m

        # Calculate routing weight
        # Popular edges get a discount, making them "cheaper" to traverse
        if is_popular:
            routing_weight = edge_length * (1 - popularity_boost)
        else:
            # Slightly penalize non-popular edges
            routing_weight = edge_length * 1.1

        G.edges[u, v, key]["routing_weight"] = routing_weight

    return G


def _get_routing_weight(G: nx.MultiDiGraph) -> str:
    """Get the weight attribute to use for routing.

    Returns 'routing_weight' if available (popularity-weighted),
    otherwise falls back to 'length'.
    """
    # Check if any edge has routing_weight
    for _, _, data in G.edges(data=True):
        if "routing_weight" in data:
            return "routing_weight"
        break
    return "length"
