#!/usr/bin/env python3
"""Build cached real-path geometry for rail and air edges (day-14c)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import httpx
from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from nexafreight.database import get_session_factory
from nexafreight.models import NetworkEdge
from nexafreight.models.location import Location
from nexafreight.models.network import NetworkNode
from nexafreight.services.rail_geometry import (
    build_rail_graph,
    densify,
    route_rail_path,
    to_geojson_linestring,
)
from nexafreight.services.air_geometry import densify_great_circle

logger = logging.getLogger(__name__)

def merge_bboxes(bboxes):
    import networkx as nx
    G = nx.Graph()
    for i, b1 in enumerate(bboxes):
        G.add_node(i, bbox=b1)
        for j, b2 in enumerate(bboxes):
            if i < j:
                if not (b1[2] < b2[0] or b1[0] > b2[2] or b1[3] < b2[1] or b1[1] > b2[3]):
                    G.add_edge(i, j)
    merged = []
    for comp in nx.connected_components(G):
        c_bboxes = [bboxes[i] for i in comp]
        south = min(b[0] for b in c_bboxes)
        west = min(b[1] for b in c_bboxes)
        north = max(b[2] for b in c_bboxes)
        east = max(b[3] for b in c_bboxes)
        merged.append((south, west, north, east))
    return merged

async def main() -> int:
    logging.basicConfig(level=logging.INFO)
    factory = get_session_factory()
    
    cache_dir = Path(__file__).resolve().parent.parent / "data" / "rail_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    
    async with factory() as session:
        node_rows = (await session.execute(select(NetworkNode))).scalars().all()
        node_xy = {n.id: (n.latitude, n.longitude) for n in node_rows}
        loc_rows = (await session.execute(select(Location))).scalars().all()
        loc_xy = {loc.id: (loc.latitude, loc.longitude) for loc in loc_rows}
        
        rail_edges = (
            await session.execute(
                select(NetworkEdge).where(
                    NetworkEdge.mode == "RAIL",
                    NetworkEdge.geometry_json.is_(None),
                )
            )
        ).scalars().all()
        
        bboxes = []
        edge_data = []
        
        for edge in rail_edges:
            o = node_xy.get(edge.from_node_id) or loc_xy.get(edge.from_node_id)
            d = node_xy.get(edge.to_node_id) or loc_xy.get(edge.to_node_id)
            if o and d:
                south = min(o[0], d[0]) - 1.5
                north = max(o[0], d[0]) + 1.5
                west = min(o[1], d[1]) - 1.5
                east = max(o[1], d[1]) + 1.5
                bbox = (south, west, north, east)
                bboxes.append(bbox)
                edge_data.append((edge, o, d, bbox))
                
        merged_bboxes = merge_bboxes(bboxes)
                
        graphs_by_bbox = {}
        overpass_reachable = True
        queries_fired = 0
        async with httpx.AsyncClient() as client:
            for bbox in merged_bboxes:
                bbox_str = f"{bbox[0]:.4f}_{bbox[1]:.4f}_{bbox[2]:.4f}_{bbox[3]:.4f}"
                cache_file = cache_dir / f"bbox_{bbox_str}.json"
                
                if cache_file.exists():
                    with open(cache_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                else:
                    if not overpass_reachable:
                        continue
                    query = f'[out:json][timeout:90];way["railway"="rail"]({bbox[0]},{bbox[1]},{bbox[2]},{bbox[3]});(._;>;);out geom;'
                    headers = {"User-Agent": "NexaFreight-rail-geometry/1.0 (contact local)"}
                    try:
                        resp = await client.post("https://overpass-api.de/api/interpreter", data=query, headers=headers, timeout=100.0)
                        queries_fired += 1
                        if resp.status_code != 200:
                            logger.warning(f"Overpass returned {resp.status_code}. Retrying...")
                            await asyncio.sleep(2.0)
                            resp = await client.post("https://overpass-api.de/api/interpreter", data=query, headers=headers, timeout=100.0)
                            queries_fired += 1
                            if resp.status_code != 200:
                                logger.error(f"Overpass failed again for {bbox}. Skipping.")
                                continue
                                
                        data = resp.json()
                        with open(cache_file, "w", encoding="utf-8") as f:
                            json.dump(data, f)
                    except Exception as e:
                        logger.error(f"Overpass unreachable: {e}")
                        overpass_reachable = False
                        continue
                    
                    await asyncio.sleep(1.5)
                    
                ways = [el for el in data.get("elements", []) if el.get("type") == "way"]
                graph = build_rail_graph(ways)
                graphs_by_bbox[bbox] = graph

        if not overpass_reachable and not graphs_by_bbox:
            return 2
            
        rail_filled = 0
        rail_failed = 0
        for edge, o, d, bbox in edge_data:
            mb = next((b for b in merged_bboxes if b[0] <= bbox[0] and b[1] <= bbox[1] and b[2] >= bbox[2] and b[3] >= bbox[3]), None)
            if mb and mb in graphs_by_bbox:
                graph = graphs_by_bbox[mb]
                path = route_rail_path(graph, o, d)
                if path:
                    densified = densify(path)
                    geo_json = to_geojson_linestring(densified)
                    edge.geometry_json = geo_json
                    rail_filled += 1
                else:
                    rail_failed += 1
            else:
                rail_failed += 1
                
        air_edges = (
            await session.execute(
                select(NetworkEdge).where(
                    NetworkEdge.mode == "AIR",
                    NetworkEdge.geometry_json.is_(None),
                )
            )
        ).scalars().all()
        
        air_filled = 0
        for edge in air_edges:
            o = node_xy.get(edge.from_node_id) or loc_xy.get(edge.from_node_id)
            d = node_xy.get(edge.to_node_id) or loc_xy.get(edge.to_node_id)
            if o and d:
                geo = densify_great_circle(o, d)
                edge.geometry_json = geo
                air_filled += 1
                
        await session.commit()
        
        print(f"Rail geometry: filled={rail_filled} failed={rail_failed} of {len(rail_edges)}")
        print(f"Air geometry: filled={air_filled} of {len(air_edges)}")
        
    return 0

if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
