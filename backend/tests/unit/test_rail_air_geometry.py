import json
import math

import networkx as nx
from geopy.distance import geodesic
import pytest

from nexafreight.services.rail_geometry import (
    build_rail_graph,
    route_rail_path,
    densify,
    to_geojson_linestring,
    snap_to_graph
)
from nexafreight.services.air_geometry import densify_great_circle


def test_rail_geometry_routing():
    # 4-node synthetic rail graph
    # Node 1: (10.0, 10.0)
    # Node 2: (10.1, 10.1)
    # Node 3: (10.2, 10.2)
    # Node 4: (10.3, 10.3)
    
    ways = [
        {
            "type": "way",
            "nodes": [1, 2, 3, 4],
            "geometry": [
                {"lat": 10.0, "lon": 10.0},
                {"lat": 10.1, "lon": 10.1},
                {"lat": 10.2, "lon": 10.2},
                {"lat": 10.3, "lon": 10.3},
            ]
        }
    ]
    
    graph = build_rail_graph(ways)
    assert len(graph.nodes) == 4
    assert len(graph.edges) == 3
    
    # Route across it
    path = route_rail_path(graph, (10.0, 10.0), (10.3, 10.3))
    assert path is not None
    assert len(path) == 4
    assert path[0] == (10.0, 10.0)
    assert path[1] == (10.1, 10.1)
    assert path[2] == (10.2, 10.2)
    assert path[3] == (10.3, 10.3)
    
    # Densify and geojson
    densified = densify(path)
    geo_json = to_geojson_linestring(densified)
    data = json.loads(geo_json)
    
    assert data["type"] == "LineString"
    assert len(data["coordinates"]) >= 4
    # Check [lon, lat] order
    assert data["coordinates"][0] == [10.0, 10.0]
    assert data["coordinates"][-1] == [10.3, 10.3]


def test_snap_failure_beyond_max_km():
    ways = [
        {
            "type": "way",
            "nodes": [1, 2],
            "geometry": [
                {"lat": 10.0, "lon": 10.0},
                {"lat": 10.1, "lon": 10.1},
            ]
        }
    ]
    graph = build_rail_graph(ways)
    
    # Very far coord (80.0, 100.0)
    # This should fail snapping
    node = snap_to_graph(graph, (80.0, 100.0), max_km=55.0)
    assert node is None
    
    path = route_rail_path(graph, (10.0, 10.0), (80.0, 100.0))
    assert path is None


def test_densify_great_circle():
    delhi = (28.6, 77.2)
    chennai = (13.1, 80.3)
    
    geo_json = densify_great_circle(delhi, chennai, step_km=30.0)
    data = json.loads(geo_json)
    
    assert data["type"] == "LineString"
    coords = data["coordinates"]
    
    assert len(coords) >= 50
    
    # Check endpoints (approx due to rounding, but it shouldn't drift too much)
    # The output format is [lon, lat] rounded to 5 decimals
    assert coords[0] == [77.2, 28.6]
    assert coords[-1] == [80.3, 13.1]
    
    # Check spacing <= 35 km
    for i in range(len(coords) - 1):
        c1 = coords[i]
        c2 = coords[i+1]
        # c is [lon, lat], geodesic takes (lat, lon)
        dist = geodesic((c1[1], c1[0]), (c2[1], c2[0])).kilometers
        assert dist <= 35.0
