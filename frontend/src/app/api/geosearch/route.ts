import { NextResponse } from 'next/server';
import { httpJson, optional } from '@/lib/httpJson';
import { cachedSource } from '@/lib/sourceCache';
import {
  type GeoResult,
  type PhotonFeature,
  type NominatimRow,
  normalizePhoton,
  normalizeNominatim,
  mergeResults,
} from './helpers';

export const maxDuration = 20;

const PHOTON = 'https://photon.komoot.io/api';
const NOMINATIM = 'https://nominatim.openstreetmap.org/search';

async function searchPhoton(q: string, lat?: number, lng?: number): Promise<GeoResult[]> {
  let url = `${PHOTON}/?q=${encodeURIComponent(q)}&limit=8&lang=en`;
  if (Number.isFinite(lat) && Number.isFinite(lng)) url += `&lat=${lat}&lon=${lng}`;
  const json = await httpJson<{ features?: PhotonFeature[] }>(url, { timeoutMs: 8000 });
  return (json.features || []).map(normalizePhoton).filter((r): r is GeoResult => r !== null);
}

async function searchNominatim(q: string): Promise<GeoResult[]> {
  const url = `${NOMINATIM}?q=${encodeURIComponent(q)}&format=json&limit=6&addressdetails=0`;
  const json = await httpJson<NominatimRow[]>(url, { timeoutMs: 8000 });
  return (Array.isArray(json) ? json : []).map(normalizeNominatim).filter((r): r is GeoResult => r !== null);
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const q = (searchParams.get('q') || '').trim();
    const lat = parseFloat(searchParams.get('lat') || '');
    const lng = parseFloat(searchParams.get('lng') || '');

    if (q.length < 2) return NextResponse.json({ results: [] });

    const biasKey = Number.isFinite(lat) && Number.isFinite(lng)
      ? `${lat.toFixed(1)},${lng.toFixed(1)}`
      : 'global';
    const key = `geosearch:${q.toLowerCase()}|${biasKey}`;

    const results = await cachedSource<GeoResult>(
      key,
      async () => {
        const [photon, nominatim] = await Promise.all([
          optional(searchPhoton(q, lat, lng)),
          optional(searchNominatim(q)),
        ]);
        return mergeResults(photon || [], nominatim || []);
      },
      10 * 60 * 1000,
    )();

    return NextResponse.json(
      { results },
      { headers: { 'Cache-Control': 'public, s-maxage=600, stale-while-revalidate=1800' } },
    );
  } catch (error) {
    console.error('[NexaFreight] Geosearch error:', error);
    return NextResponse.json({ results: [], error: 'Search failed' }, { status: 500 });
  }
}
