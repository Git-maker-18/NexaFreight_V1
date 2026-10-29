import { NextResponse } from 'next/server';
import { httpJson, optional } from '@/lib/httpJson';
import {
  type TravelMode,
  type ValhallaResponse,
  type OsrmResponse,
  type DirectionsResult,
  type AvoidOptions,
  type ElevationPoint,
  buildCostingOptions,
  normalizeValhallaAll,
  normalizeOsrm,
} from './helpers';

export const maxDuration = 30;

const VALHALLA_BASE = 'https://valhalla1.openstreetmap.de';
const VALHALLA = `${VALHALLA_BASE}/route`;
const OSRM = 'https://router.project-osrm.org/route/v1';

function parsePoint(raw: string | null): { lat: number; lng: number } | null {
  if (!raw) return null;
  const [a, b] = raw.split(',').map((n) => parseFloat(n.trim()));
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  if (a < -90 || a > 90 || b < -180 || b > 180) return null;
  return { lat: a, lng: b };
}

async function tryValhalla(
  points: Array<{ lat: number; lng: number }>,
  mode: TravelMode,
  avoid: AvoidOptions,
): Promise<DirectionsResult[]> {
  const costingOptions = buildCostingOptions(mode, avoid);
  const body = {
    locations: points.map((p) => ({ lat: p.lat, lon: p.lng })),
    costing: mode,
    ...(Object.keys(costingOptions).length ? { costing_options: costingOptions } : {}),
    alternates: 2,
    directions_options: { units: 'kilometers' },
  };
  const url = `${VALHALLA}?json=${encodeURIComponent(JSON.stringify(body))}`;
  return normalizeValhallaAll(await httpJson<ValhallaResponse>(url), mode);
}

async function tryOsrm(
  points: Array<{ lat: number; lng: number }>,
  mode: TravelMode,
): Promise<DirectionsResult[]> {
  const coords = points.map((p) => `${p.lng},${p.lat}`).join(';');
  const url = `${OSRM}/driving/${coords}?steps=true&overview=full&geometries=geojson`;
  const r = normalizeOsrm(await httpJson<OsrmResponse>(url), mode);
  return r ? [r] : [];
}

async function fetchElevation(
  coords: [number, number][],
): Promise<{ elevation: ElevationPoint[]; ascent: number; descent: number } | null> {
  const MAX = 120;
  const stride = Math.max(1, Math.ceil(coords.length / MAX));
  const shape = coords.filter((_, i) => i % stride === 0).map(([lon, lat]) => ({ lat, lon }));
  if (shape.length < 2) return null;

  const url = `${VALHALLA_BASE}/height?json=${encodeURIComponent(JSON.stringify({ range: true, shape }))}`;
  const json = await httpJson<{ range_height?: [number, number][] }>(url, { timeoutMs: 10000 });
  const pairs = json?.range_height;
  if (!Array.isArray(pairs) || pairs.length < 2) return null;

  const elevation: ElevationPoint[] = [];
  let ascent = 0;
  let descent = 0;
  let prev: number | null = null;
  for (const [distance, height] of pairs) {
    if (!Number.isFinite(distance) || !Number.isFinite(height)) continue;
    elevation.push({ distance, height });
    if (prev !== null) {
      const d = height - prev;
      if (d > 1) ascent += d;
      else if (d < -1) descent += -d;
    }
    prev = height;
  }
  if (elevation.length < 2) return null;
  return { elevation, ascent: Math.round(ascent), descent: Math.round(descent) };
}

export async function GET(request: Request) {
  try {
    const url = new URL(request.url);
    const pointsParam = url.searchParams.get('points');
    const fromParam = url.searchParams.get('from');
    const toParam = url.searchParams.get('to');
    const modeParam = (url.searchParams.get('mode') || 'auto') as TravelMode;
    const mode: TravelMode = ['auto', 'bicycle', 'pedestrian'].includes(modeParam) ? modeParam : 'auto';

    const avoid: AvoidOptions = {
      tolls: url.searchParams.get('avoid_tolls') === '1',
      highways: url.searchParams.get('avoid_highways') === '1',
      ferries: url.searchParams.get('avoid_ferries') === '1',
    };

    let points: Array<{ lat: number; lng: number }> = [];
    if (pointsParam) {
      points = pointsParam
        .split(';')
        .map(parsePoint)
        .filter((p): p is { lat: number; lng: number } => p !== null);
    } else if (fromParam && toParam) {
      const from = parsePoint(fromParam);
      const to = parsePoint(toParam);
      if (from && to) points = [from, to];
    }

    if (points.length < 2) {
      return NextResponse.json(
        { error: 'At least two valid coordinates are required (use ?points=lat,lng;lat,lng or ?from=&to=)' },
        { status: 400 },
      );
    }

    let routes: DirectionsResult[] = [];
    try {
      routes = await tryValhalla(points, mode, avoid);
    } catch {
      // Fall through to OSRM on any Valhalla failure
    }

    if (!routes.length && mode === 'auto') {
      try {
        routes = await tryOsrm(points, mode);
      } catch {
        // Upstream failed
      }
    }

    if (!routes.length) {
      return NextResponse.json(
        { error: 'No route found between the requested points across both routing engines' },
        { status: 502 },
      );
    }

    if (mode !== 'auto' && routes[0]?.geometry?.coordinates) {
      const elev = await fetchElevation(routes[0].geometry.coordinates).catch(() => null);
      if (elev) {
        routes[0].elevation = elev.elevation;
        routes[0].ascent = elev.ascent;
        routes[0].descent = elev.descent;
      }
    }

    return NextResponse.json({
      routes,
      waypoints: points,
      mode,
      provider: routes[0].provider,
    });
  } catch (err) {
    const message = err instanceof Error ? err.message : 'Directions request failed';
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
