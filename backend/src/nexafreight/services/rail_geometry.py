"""Rail geometry builder using OpenStreetMap graph routing."""

import json
import math
import networkx as nx
from geopy.distance import geodesic


def build_rail_graph(ways: list) -> nx.Graph:
    """Build a networkx Graph from Overpass ways.
    
    Input: Overpass way elements with tag railway=rail, each with 'nodes' ids 
    and 'geometry' [{lat,lon},...]. Add an edge between consecutive way nodes.
    """
    graph = nx.Graph()
    for way in ways:
        geometry = way.get("geometry", [])
        if not geometry:
            continue
        nodes = way.get("nodes", [])
        if len(geometry) != len(nodes):
            continue
            
        for i in range(len(nodes) - 1):
            u = nodes[i]
            v = nodes[i+1]
            u_coord = (geometry[i]["lat"], geometry[i]["lon"])
            v_coord = (geometry[i+1]["lat"], geometry[i+1]["lon"])
            
            if u not in graph:
                graph.add_node(u, lat=u_coord[0], lon=u_coord[1])
            if v not in graph:
                graph.add_node(v, lat=v_coord[0], lon=v_coord[1])
                
            dist_km = geodesic(u_coord, v_coord).kilometers
            graph.add_edge(u, v, weight=dist_km)
            
    return graph


def snap_to_graph(graph: nx.Graph, coord: tuple[float, float], max_km: float = 55.0) -> int | None:
    """Find the nearest graph node within max_km of coord."""
    best_node = None
    min_dist = max_km
    for node, data in graph.nodes(data=True):
        node_coord = (data["lat"], data["lon"])
        dist = geodesic(coord, node_coord).kilometers
        if dist < min_dist:
            min_dist = dist
            best_node = node
    return best_node


def route_rail_path(graph: nx.Graph, o_coord: tuple[float, float], d_coord: tuple[float, float]) -> list[tuple[float, float]] | None:
    """Snap coords, find shortest path, return list of (lat, lon) or None."""
    u = snap_to_graph(graph, o_coord)
    v = snap_to_graph(graph, d_coord)
    
    if u is None or v is None:
        return None
        
    try:
        path = nx.shortest_path(graph, source=u, target=v, weight="weight")
    except nx.NetworkXNoPath:
        return None
        
    return [(graph.nodes[node]["lat"], graph.nodes[node]["lon"]) for node in path]


def densify(points: list[tuple[float, float]], step_deg: float = 0.05) -> list[tuple[float, float]]:
    """Interpolate so consecutive points are at most ~0.05 deg apart."""
    if not points:
        return []
    result = [points[0]]
    for i in range(1, len(points)):
        prev = result[-1]
        curr = points[i]
        
        lat_diff = curr[0] - prev[0]
        lon_diff = curr[1] - prev[1]
        dist_deg = math.hypot(lat_diff, lon_diff)
        
        if dist_deg > step_deg:
            num_steps = math.ceil(dist_deg / step_deg)
            for step in range(1, num_steps):
                f = step / num_steps
                interp_lat = prev[0] + lat_diff * f
                interp_lon = prev[1] + lon_diff * f
                result.append((interp_lat, interp_lon))
        result.append(curr)
    return result


def to_geojson_linestring(points: list[tuple[float, float]]) -> str:
    """Convert [(lat, lon)] to GeoJSON LineString string with 5-decimal rounding."""
    coords = [[round(p[1], 5), round(p[0], 5)] for p in points]
    return json.dumps({"type": "LineString", "coordinates": coords})
