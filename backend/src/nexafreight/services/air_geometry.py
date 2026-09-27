"""Air geometry densification (honest great circles)."""

import json
import math


def densify_great_circle(o_coord: tuple[float, float], d_coord: tuple[float, float], step_km: float = 30.0) -> str:
    """Spherical interpolation between two coords."""
    lat1 = math.radians(o_coord[0])
    lon1 = math.radians(o_coord[1])
    lat2 = math.radians(d_coord[0])
    lon2 = math.radians(d_coord[1])

    dlon = lon2 - lon1
    dlat = lat2 - lat1
    a = math.sin(dlat/2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon/2)**2
    
    # Avoid domain errors if a goes slightly above 1 due to floating point inaccuracies
    a = min(1.0, max(0.0, a))
    c = 2 * math.asin(math.sqrt(a))
    
    EARTH_RADIUS_KM = 6371.0
    dist_km = c * EARTH_RADIUS_KM
    
    if dist_km <= step_km or c == 0:
        points = [o_coord, d_coord]
    else:
        num_steps = math.ceil(dist_km / step_km)
        points = []
        for i in range(num_steps + 1):
            f = i / num_steps
            A = math.sin((1 - f) * c) / math.sin(c)
            B = math.sin(f * c) / math.sin(c)
            x = A * math.cos(lat1) * math.cos(lon1) + B * math.cos(lat2) * math.cos(lon2)
            y = A * math.cos(lat1) * math.sin(lon1) + B * math.cos(lat2) * math.sin(lon2)
            z = A * math.sin(lat1) + B * math.sin(lat2)
            
            interp_lat = math.atan2(z, math.hypot(x, y))
            interp_lon = math.atan2(y, x)
            
            points.append((math.degrees(interp_lat), math.degrees(interp_lon)))
            
    coords = [[round(p[1], 5), round(p[0], 5)] for p in points]
    return json.dumps({"type": "LineString", "coordinates": coords})
