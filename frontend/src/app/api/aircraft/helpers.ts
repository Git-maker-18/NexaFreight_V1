import { nearestAirport, type Airport } from '@/lib/airports';

export interface AircraftDetail {
  icao24: string;
  registration: string | null;
  typeCode: string | null;
  model: string | null;
  operator: string | null;
  track: [number, number][];
  altitudes: (number | null)[];
  points: number;
  departure: Airport | null;
  arrival: Airport | null;
  source: string;
}

export function shardFor(icao24: string): string {
  return icao24.trim().toLowerCase().slice(-2);
}

export interface TraceFile {
  icao?: string;
  r?: string;
  t?: string;
  desc?: string;
  ownOp?: string;
  timestamp?: number;
  trace?: Array<Array<number | string | null>>;
}

export function currentLeg(
  rows: Array<Array<number | string | null>>,
  minGroundRun = 4,
): Array<Array<number | string | null>> {
  if (rows.length === 0) return rows;
  const isGround = (r: Array<number | string | null>) => r?.[3] === 'ground';

  let i = rows.length - 1;
  while (i >= 0 && isGround(rows[i])) i--;
  if (i < 0) return rows.slice(-2);
  const end = i;

  let run = 0;
  let runNewest = -1;
  let start = 0;
  while (i >= 0) {
    if (isGround(rows[i])) {
      if (run === 0) runNewest = i;
      if (++run >= minGroundRun) { start = runNewest + 1; break; }
    } else {
      run = 0;
    }
    i--;
  }
  const leg = rows.slice(start, end + 1);
  return leg.length > 1 ? leg : rows;
}

const DEPARTURE_CEILING_FT = 10_000;

export function legEndpoints(
  track: [number, number][],
  altitudes: (number | null)[],
  landed: boolean,
): { departure: Airport | null; arrival: Airport | null } {
  if (track.length < 2) return { departure: null, arrival: null };

  const firstAlt = altitudes[0];
  const lowStart = firstAlt === null || (typeof firstAlt === 'number' && firstAlt <= DEPARTURE_CEILING_FT);
  const departure = lowStart ? nearestAirport(track[0][1], track[0][0]) : null;

  const last = track[track.length - 1];
  const arrival = landed ? nearestAirport(last[1], last[0]) : null;

  return { departure, arrival };
}

export function downsample<T>(points: T[], max: number): T[] {
  if (points.length <= max) return points;
  const step = (points.length - 1) / (max - 1);
  const out: T[] = [];
  for (let i = 0; i < max; i++) out.push(points[Math.round(i * step)]);
  return out;
}

export function parseTrace(
  json: TraceFile,
  maxPoints = 700,
  legOnly = true,
): Omit<AircraftDetail, 'operator' | 'source'> {
  const track: [number, number][] = [];
  const altitudes: (number | null)[] = [];

  const rows = legOnly ? currentLeg(json?.trace || []) : (json?.trace || []);
  for (const row of rows) {
    const lat = row?.[1];
    const lng = row?.[2];
    if (typeof lat !== 'number' || typeof lng !== 'number') continue;
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) continue;
    track.push([lng, lat]);
    const alt = row?.[3];
    altitudes.push(typeof alt === 'number' ? alt : null);
  }

  const idx = track.map((_, i) => i);
  const keep = downsample(idx, maxPoints);

  const raw = json?.trace || [];
  const landed = raw.length > 0 && raw[raw.length - 1]?.[3] === 'ground';

  return {
    icao24: (json?.icao || '').toLowerCase(),
    registration: json?.r?.trim() || null,
    typeCode: json?.t?.trim() || null,
    model: json?.desc?.trim() || null,
    track: keep.map((i) => track[i]),
    altitudes: keep.map((i) => altitudes[i]),
    points: keep.length,
    ...legEndpoints(track, altitudes, landed),
  };
}

export interface AdsbdbResponse {
  response?: {
    aircraft?: {
      manufacturer?: string;
      type?: string;
      registered_owner?: string;
      registration?: string;
      icao_type?: string;
    };
  };
}
