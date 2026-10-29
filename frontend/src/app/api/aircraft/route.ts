import { NextResponse } from 'next/server';
import { httpJson, optional } from '@/lib/httpJson';
import { cachedSource } from '@/lib/sourceCache';
import {
  type AircraftDetail,
  type TraceFile,
  type AdsbdbResponse,
  shardFor,
  parseTrace,
} from './helpers';

export const maxDuration = 20;

const TRACE_BASE = 'https://adsb.lol/data/traces';
const ADSBDB = 'https://api.adsbdb.com/v0/aircraft';

async function fetchTrace(icao24: string): Promise<TraceFile | null> {
  const kinds = ['recent', 'full'];
  for (const kind of kinds) {
    const url = `${TRACE_BASE}/${shardFor(icao24)}/trace_${kind}_${icao24.toLowerCase()}.json`;
    const json = await optional(httpJson<TraceFile>(url, { timeoutMs: 6000 }));
    if (json && Array.isArray(json.trace) && json.trace.length > 0) return json;
  }
  return null;
}

async function fetchMetadata(icao24: string): Promise<{ model?: string; operator?: string; registration?: string; typeCode?: string } | null> {
  const url = `${ADSBDB}/${encodeURIComponent(icao24.trim().toLowerCase())}`;
  const json = await optional(httpJson<AdsbdbResponse>(url, { timeoutMs: 4000 }));
  const a = json?.response?.aircraft;
  if (!a) return null;
  const model = [a.manufacturer, a.type].filter(Boolean).join(' ') || undefined;
  return {
    model: model || undefined,
    operator: a.registered_owner || undefined,
    registration: a.registration || undefined,
    typeCode: a.icao_type || undefined,
  };
}

export async function GET(request: Request) {
  try {
    const { searchParams } = new URL(request.url);
    const icao24 = (searchParams.get('icao24') || '').trim();

    if (!/^[0-9a-fA-F]{6}$/.test(icao24)) {
      return NextResponse.json({ error: 'Valid 6-character hex ICAO24 required' }, { status: 400 });
    }

    const key = `aircraft:${icao24.toLowerCase()}`;
    const detail = await cachedSource<AircraftDetail>(
      key,
      async () => {
        const [trace, meta] = await Promise.all([
          fetchTrace(icao24),
          fetchMetadata(icao24),
        ]);
        if (!trace) return [];

        const parsed = parseTrace(trace);
        const resolved: AircraftDetail = {
          ...parsed,
          model: parsed.model || meta?.model || null,
          registration: parsed.registration || meta?.registration || null,
          typeCode: parsed.typeCode || meta?.typeCode || null,
          operator: meta?.operator || null,
          source: 'adsb.lol + adsbdb',
        };
        return [resolved];
      },
      30 * 1000,
    )();

    if (!detail.length) {
      return NextResponse.json({ error: 'No recent trace for aircraft' }, { status: 404 });
    }

    return NextResponse.json(detail[0], {
      headers: { 'Cache-Control': 'public, s-maxage=15, stale-while-revalidate=45' },
    });
  } catch (error) {
    console.error('[NexaFreight] Aircraft lookup failed:', error);
    return NextResponse.json({ error: 'Aircraft lookup failed' }, { status: 500 });
  }
}
