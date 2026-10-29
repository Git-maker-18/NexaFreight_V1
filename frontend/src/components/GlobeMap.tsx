'use client';

import { useEffect, useRef, useState, useCallback, memo } from 'react';
import * as maplibregl from 'maplibre-gl';

// Configure local static MapLibre GL worker to prevent worker resolution failures
if (typeof window !== 'undefined' && typeof (maplibregl as any).setWorkerUrl === 'function') {
  (maplibregl as any).setWorkerUrl('/maplibre-gl-worker.mjs');
}


/* Map pigment constants — were lib/map-palette.ts before Phase 0 removed it.
 * Values mirror the `--map-*` custom properties in globals.css; the palette is
 * read once statically now that Style Studio's map section is gone (Definitive
 * Plan Phase 0: "map color palette — not needed"). */
interface MapPalette {
  cctv: string;
  flightCivil: string;
  flightPrivate: string;
  flightGov: string;
  flightMilitary: string;
  flightUnknown: string;
}
const MAP_DEFAULTS: MapPalette = {
  cctv: '#00e676',
  flightCivil: '#2547C8',
  flightPrivate: '#2547C8',
  flightGov: '#B4452F',
  flightMilitary: '#B4452F',
  flightUnknown: '#5A5D66',
};


import { getPorts, getWarehouses, getAllRoutes, getShipmentDetail, getAlerts, type PositionReport } from '@/lib/nexafreight';
import { useSSEPositions } from '@/hooks/useSSEPositions';
import { getProvenanceBadgeHtml } from '@/components/ProvenanceBadge';
import { freightMarkerHtml, freightNodeHtml, CHARTROOM, type MarkerState } from '@/lib/map/freightMarkers';
import { waybillCard, waybillAction, waybillLoading, provenanceChip, esc as wesc, type WaybillRow } from '@/lib/map/waybill';

/** The catalogue fields the satellite layer and its popup actually read. */
interface SatelliteRow {
  name: string;
  lat: number;
  lng: number;
  alt: number;
  color?: string;
  mission?: string;
  category?: string;
  noradId?: string;
}
import 'maplibre-gl/dist/maplibre-gl.css';

interface GlobeMapProps {
  data: any;
  activeLayers: Record<string, boolean>;
  onEntityClick?: (entity: any) => void;
  onMouseCoords?: (coords: { lat: number; lng: number }) => void;
  onRightClick?: (coords: { lat: number; lng: number }) => void;
  onViewStateChange?: (vs: { zoom: number; latitude: number }) => void;
  flyToLocation?: { lat: number; lng: number; zoom?: number; ts: number } | null;
  projection?: 'mercator' | 'globe';
  mapStyle?: string;
  demoMode?: boolean;
  theme?: 'core' | 'ghost';
  drawnPolygons?: Array<{ id: string; name: string; geojson: GeoJSON.Feature<GeoJSON.Polygon | GeoJSON.LineString>; color: string }>;
  arcgisLayers?: Array<{ id: string; title: string; geojson: any; color?: string; opacity?: number }>;
  onMapCenter?: (coords: { lat: number; lng: number; bounds?: { west: number; south: number; east: number; north: number } }) => void;
  /** Active turn-by-turn route drawn as a line with origin/destination pins. */
  route?: {
    geometry: { type: 'LineString'; coordinates: [number, number][] };
    from: { lat: number; lng: number };
    to: { lat: number; lng: number };
    /** Unselected alternatives, drawn dimmed behind the active line. */
    alternates?: Array<{ type: 'LineString'; coordinates: [number, number][] }>;
    /** Highlighted portion for the step the operator has selected. */
    activeSegment?: [number, number][] | null;
  } | null;
  /** Live position from the browser — drawn as a pulsing dot with accuracy ring. */
  userLocation?: { lat: number; lng: number; accuracy?: number; heading?: number | null } | null;
  /** Keep the camera centred on userLocation as it moves. */
  followUser?: boolean;
  /** Fired when the operator pans/zooms/rotates while follow mode is on. */
  onFollowInterrupt?: () => void;
  /** Live navigation: tighter zoom and the map turned to face travel direction. */
  navigating?: boolean;
  /** Corroborated endpoint airports for watched aircraft, keyed by icao24. */
  aircraftAirports?: Record<string, Array<{ icao: string; iata?: string; city?: string; lat: number; lng: number }>>;
}

function computeSolarTerminator(): [number, number][] {
  const now = new Date();
  const dayOfYear = Math.floor((now.getTime() - new Date(now.getFullYear(), 0, 0).getTime()) / 86400000);
  const declination = -23.44 * Math.cos((2 * Math.PI / 365) * (dayOfYear + 10));
  const decRad = declination * Math.PI / 180;
  const utcHours = now.getUTCHours() + now.getUTCMinutes() / 60;
  const subsolarLng = (12 - utcHours) * 15;
  const points: [number, number][] = [];
  for (let lng = -180; lng <= 180; lng += 2) {
    const lngRad = (lng - subsolarLng) * Math.PI / 180;
    const lat = Math.atan(-Math.cos(lngRad) / Math.tan(decRad)) * 180 / Math.PI;
    points.push([lng, lat]);
  }
  const darkSide = declination >= 0 ? -90 : 90;
  points.push([180, darkSide]);
  points.push([-180, darkSide]);
  points.push(points[0]);
  return points;
}

const EMPTY_FC = { type: 'FeatureCollection' as const, features: [] };

const CARGO_AIRPORTS_FC: GeoJSON.FeatureCollection = {
  type: 'FeatureCollection',
  features: [
    { type: 'Feature', geometry: { type: 'Point', coordinates: [55.3644, 25.2532] }, properties: { code: 'DXB', name: "Dubai Int'l Cargo Hub", city: 'Dubai', country: 'United Arab Emirates' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [2.5479, 49.0097] }, properties: { code: 'CDG', name: 'Paris Charles de Gaulle Cargo', city: 'Paris / Le Havre', country: 'France' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [103.9915, 1.3644] }, properties: { code: 'SIN', name: 'Singapore Changi Airfreight Hub', city: 'Singapore', country: 'Singapore' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [9.9882, 53.6304] }, properties: { code: 'HAM', name: 'Hamburg International Airport', city: 'Hamburg', country: 'Germany' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-118.4085, 33.9416] }, properties: { code: 'LAX', name: "Los Angeles Int'l Air Cargo", city: 'Los Angeles', country: 'United States' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [139.7798, 35.5494] }, properties: { code: 'HND', name: 'Tokyo Haneda Airfreight Hub', city: 'Tokyo / Yokohama', country: 'Japan' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-73.7781, 40.6413] }, properties: { code: 'JFK', name: 'John F. Kennedy Airfreight Center', city: 'New York', country: 'United States' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [4.7683, 52.3105] }, properties: { code: 'AMS', name: 'Amsterdam Schiphol Cargo', city: 'Amsterdam / Rotterdam', country: 'Netherlands' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [121.8083, 31.1443] }, properties: { code: 'PVG', name: 'Shanghai Pudong Cargo Hub', city: 'Shanghai', country: 'China' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [72.8656, 19.0896] }, properties: { code: 'BOM', name: 'Mumbai Air Cargo Terminal', city: 'Mumbai', country: 'India' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [-87.9073, 41.9742] }, properties: { code: 'ORD', name: "Chicago O'Hare Cargo Center", city: 'Chicago', country: 'United States' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [151.1753, -33.9399] }, properties: { code: 'SYD', name: 'Sydney Kingsford Smith Cargo', city: 'Sydney', country: 'Australia' } },
    { type: 'Feature', geometry: { type: 'Point', coordinates: [106.6559, -6.1256] }, properties: { code: 'CGK', name: 'Jakarta Soekarno-Hatta Cargo', city: 'Jakarta', country: 'Indonesia' } },
  ],
};

function extractTruckPoints(_routesFC: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  // Static midpoints retired in favor of live moving SSE positions (Step 4)
  return { type: 'FeatureCollection', features: [] };
}

/**
 * Generates an aerial parabolic flight arc between two coordinates.
 * Deflects poleward (northward in the Northern Hemisphere) proportional to distance,
 * mimicking high-altitude aviation flight paths rather than a flat ground straight line.
 */
export function generateParabolicFlightPath(
  coords: number[][],
  numPoints = 48,
  maxBowDeg = 8.5
): number[][] {
  if (!coords || coords.length < 2) return coords || [];
  const start = coords[0];
  const end = coords[coords.length - 1];
  let [lng1, lat1] = start;
  let [lng2, lat2] = end;

  // Handle antimeridian crossing
  let dLng = lng2 - lng1;
  if (dLng > 180) dLng -= 360;
  else if (dLng < -180) dLng += 360;

  const dLat = lat2 - lat1;
  const distDeg = Math.hypot(dLng, dLat);
  if (distDeg < 0.25) return coords;

  const midLng = lng1 + dLng * 0.5;
  const midLat = lat1 + dLat * 0.5;

  // Normal vector perpendicular to chord
  let normX = -dLat;
  let normY = dLng;
  const normLen = Math.hypot(normX, normY);
  if (normLen > 0) {
    normX /= normLen;
    normY /= normLen;
  }

  // Curve poleward (towards high latitudes: northward if positive, southward if negative)
  const poleward = midLat >= 0 ? 1 : -1;
  if (normY * poleward < 0) {
    normX = -normX;
    normY = -normY;
  }

  // Altitude bow height
  const bow = Math.min(maxBowDeg, Math.max(1.8, distDeg * 0.22));
  const ctrlLng = midLng + normX * bow * 0.45;
  const ctrlLat = Math.min(84, Math.max(-84, midLat + normY * bow));

  const arc: number[][] = [];
  for (let i = 0; i <= numPoints; i++) {
    const t = i / numPoints;
    const invT = 1 - t;
    // Quadratic Bezier
    let lng = invT * invT * lng1 + 2 * invT * t * ctrlLng + t * t * (lng1 + dLng);
    const lat = invT * invT * lat1 + 2 * invT * t * ctrlLat + t * t * lat2;
    if (lng > 180) lng -= 360;
    else if (lng < -180) lng += 360;
    arc.push([Number(lng.toFixed(5)), Number(lat.toFixed(5))]);
  }
  return arc;
}

/** Preprocesses GeoJSON FeatureCollection to turn air routes into parabolic flight paths. */
export function preprocessRoutesFC(routesFC: GeoJSON.FeatureCollection): GeoJSON.FeatureCollection {
  if (!routesFC || !Array.isArray(routesFC.features)) return routesFC;
  const features = routesFC.features.map((feat: any) => {
    const mode = String(feat?.properties?.mode || '').toUpperCase();
    if (mode === 'AIR') {
      const geom = feat?.geometry;
      if (geom?.type === 'LineString' && Array.isArray(geom.coordinates)) {
        return {
          ...feat,
          geometry: {
            ...geom,
            coordinates: generateParabolicFlightPath(geom.coordinates),
          },
        };
      }
    }
    return feat;
  });
  return {
    ...routesFC,
    features,
  };
}

/** Document kind printed on a waybill header, derived from transport mode. */
function kindLabel(mode: string): string {
  switch (String(mode).toUpperCase()) {
    case 'ROAD': return 'Road Freight \u00b7 Truck';
    case 'AIR':  return 'Air Cargo \u00b7 Flight';
    case 'RAIL': return 'Rail Freight \u00b7 Train';
    default:     return 'Maritime \u00b7 Vessel';
  }
}

function getAssetMarkerSvg(
  assetType: 'VESSEL' | 'TRUCK' | 'FLIGHT' | 'TRAIN',
  heading: number,
  _speed?: number | null,
  state: MarkerState = 'nominal',
): string {
  // Chartroom: flat cobalt body, hairline ink ring, no glow. Mode is carried
  // by the silhouette, SLA state by the ring treatment.
  return freightMarkerHtml(assetType, heading, state);
}

/**
 * Calculates initial compass bearing from (lng1, lat1) to (lng2, lat2) in degrees [0, 360).
 * 0 = North, 90 = East, 180 = South, 270 = West.
 */
function calculateBearing(lng1: number, lat1: number, lng2: number, lat2: number): number {
  const dLng = (lng2 - lng1) * (Math.PI / 180);
  const lat1Rad = lat1 * (Math.PI / 180);
  const lat2Rad = lat2 * (Math.PI / 180);
  const y = Math.sin(dLng) * Math.cos(lat2Rad);
  const x = Math.cos(lat1Rad) * Math.sin(lat2Rad) - Math.sin(lat1Rad) * Math.cos(lat2Rad) * Math.cos(dLng);
  const brng = (Math.atan2(y, x) * 180) / Math.PI;
  return (brng + 360) % 360;
}

/**
 * Computes shortest angular path so CSS rotation doesn't spin 340 degrees across the 0/360 boundary.
 */
function shortestAngle(current: number, target: number): number {
  let diff = (target - current) % 360;
  if (diff > 180) diff -= 360;
  if (diff < -180) diff += 360;
  return current + diff;
}

/**
 * Finds the segment on a route line closest to (currentLng, currentLat) and computes
 * the bearing pointing forward along the line towards the destination.
 */
function getRouteLineBearing(feature: any, currentLng: number, currentLat: number): number | null {
  if (!feature?.geometry?.coordinates) return null;
  const geomType = feature.geometry.type;
  let coords: number[][] | null = null;
  if (geomType === 'LineString') {
    coords = feature.geometry.coordinates;
  } else if (geomType === 'MultiLineString') {
    const parts: number[][][] = feature.geometry.coordinates;
    let closestPart = parts[0];
    let minPartDist = Infinity;
    for (const part of parts) {
      for (const pt of part) {
        const d = (pt[0] - currentLng) ** 2 + (pt[1] - currentLat) ** 2;
        if (d < minPartDist) {
          minPartDist = d;
          closestPart = part;
        }
      }
    }
    coords = closestPart;
  }

  if (!coords || coords.length < 2) return null;

  let bestDist = Infinity;
  let bestIdx = 0;
  for (let i = 0; i < coords.length - 1; i++) {
    const [x1, y1] = coords[i];
    const [x2, y2] = coords[i + 1];
    const dx = x2 - x1;
    const dy = y2 - y1;
    const lenSq = dx * dx + dy * dy;
    let t = lenSq > 0 ? ((currentLng - x1) * dx + (currentLat - y1) * dy) / lenSq : 0;
    t = Math.max(0, Math.min(1, t));
    const projX = x1 + t * dx;
    const projY = y1 + t * dy;
    const distSq = (currentLng - projX) ** 2 + (currentLat - projY) ** 2;
    if (distSq < bestDist) {
      bestDist = distSq;
      bestIdx = i;
    }
  }

  const [segX1, segY1] = coords[bestIdx];
  const [segX2, segY2] = coords[bestIdx + 1];
  return calculateBearing(segX1, segY1, segX2, segY2);
}

/**
 * Projects a point onto the nearest segment of a collection of LineString/MultiLineString features.
 * Snaps (targetLng, targetLat) directly onto the route line and returns the forward line bearing.
 */
function projectPointToLineFeatures(
  features: any[],
  targetLng: number,
  targetLat: number,
  preferredFeature?: any
): { snappedCoords: [number, number]; bearing: number; feature: any } | null {
  const targetFeatures = preferredFeature ? [preferredFeature] : features;
  if (!targetFeatures || !targetFeatures.length) return null;

  let bestDist = Infinity;
  let bestPt: [number, number] = [targetLng, targetLat];
  let bestBearing = 0;
  let bestFeat: any = null;

  for (const feat of targetFeatures) {
    if (!feat?.geometry?.coordinates) continue;
    const geomType = feat.geometry.type;
    let parts: number[][][] = [];
    if (geomType === 'LineString') {
      parts = [feat.geometry.coordinates];
    } else if (geomType === 'MultiLineString') {
      parts = feat.geometry.coordinates;
    }

    for (const coords of parts) {
      if (!coords || coords.length < 2) continue;
      for (let i = 0; i < coords.length - 1; i++) {
        const [x1, y1] = coords[i];
        const [x2, y2] = coords[i + 1];
        const dx = x2 - x1;
        const dy = y2 - y1;
        const lenSq = dx * dx + dy * dy;
        let t = lenSq > 0 ? ((targetLng - x1) * dx + (targetLat - y1) * dy) / lenSq : 0;
        t = Math.max(0, Math.min(1, t));
        const qx = x1 + t * dx;
        const qy = y1 + t * dy;
        const dSq = (targetLng - qx) ** 2 + (targetLat - qy) ** 2;
        if (dSq < bestDist) {
          bestDist = dSq;
          bestPt = [qx, qy];
          bestBearing = calculateBearing(x1, y1, x2, y2);
          bestFeat = feat;
        }
      }
    }
  }

  return bestFeat ? { snappedCoords: bestPt, bearing: bestBearing, feature: bestFeat } : null;
}

interface LiveMarkerRecord {
  marker: maplibregl.Marker;
  el: HTMLElement;
  innerEl: HTMLElement;
  badgeEl?: HTMLElement;
  animId?: number;
  currentCoords: [number, number]; // [lng, lat]
  targetCoords: [number, number];  // [lng, lat]
  currentHeading: number;
  assetType: 'VESSEL' | 'TRUCK' | 'FLIGHT' | 'TRAIN';
  assetId: string;
  latestPos?: PositionReport;
}

function GlobeMap({ data, activeLayers, onEntityClick, onMouseCoords, onRightClick, onViewStateChange, flyToLocation, projection = 'globe', mapStyle = 'dark', demoMode = false, theme = 'core', drawnPolygons = [], arcgisLayers = [], onMapCenter, route = null, userLocation = null, followUser = false, onFollowInterrupt, navigating = false, aircraftAirports = {} }: GlobeMapProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const [mapReady, setMapReady] = useState(false);
  /**
   * What the map's own layers draw with, mirrored out of the `--map-*` custom
   * properties. Held in state rather than read at each use so a change re-runs
   * the recolour effects; held in a ref as well for the click handlers, which
   * are registered once on load and would otherwise close over the first value.
   */
  const palette: MapPalette = MAP_DEFAULTS;
  const paletteRef = useRef(palette);
  const prevStyleRef = useRef(mapStyle);
  const initialStyleRef = useRef(mapStyle);
  const prevDrawnPolygonsRef = useRef<string[]>([]);
  const prevArcgisLayersRef = useRef<string[]>([]);


  // ── NexaFreight Route & Live Marker Lookups (Step 4) ──
  const legToShipmentRef = useRef<Map<string, { shipmentId: string; mode: string }>>(new Map());
  const vesselToShipmentRef = useRef<Map<string, string>>(new Map());
  const legToRouteFeatureRef = useRef<Map<string, any>>(new Map());
  const vesselToRouteFeatureRef = useRef<Map<string, any>>(new Map());
  const routesFeaturesRef = useRef<any[]>([]);
  const seaRoutesRef = useRef<any[]>([]);
  const [routesLoadedVer, setRoutesLoadedVer] = useState(0);
  const liveMarkersRef = useRef<Map<string, LiveMarkerRecord>>(new Map());

  const pStyle = `background:var(--paper,#F6F7F4);border:1px solid var(--border-hairline,#D4D5D0);border-radius:2px;padding:11px 12px;color:var(--ink,#16181D);font-family:'IBM Plex Mono','JetBrains Mono',ui-monospace,monospace;`;
  const htmlEsc = (s: any): string => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');

  const showPopup = useCallback((coords: [number, number], html: string) => {
    if (!mapRef.current) return;
    popupRef.current?.remove();
    popupRef.current = new maplibregl.Popup({ closeButton: true, maxWidth: '420px', offset: 14 })
      .setLngLat(coords)
      .setHTML(html)
      .addTo(mapRef.current);
  }, []);

  const openShipmentInspector = useCallback(async (
    shipmentId: string,
    coords: [number, number],
    opts?: {
      mode?: string;
      legId?: string;
      sequence?: any;
      status?: string;
      routeQuality?: string;
      provenance?: string;
      telemetry?: { speed?: string; heading?: string; provenance?: string; assetId?: string; assetType?: string };
    }
  ) => {
    if (!mapRef.current) return;
    const mode = opts?.mode || 'SEA';
    const modeColor = mode === 'SEA' ? '#2547C8' : mode === 'AIR' ? '#B54708' : mode === 'ROAD' ? '#027A48' : '#4B515D';
    const refNumber = `NF-${String(shipmentId || '').slice(0, 8).toUpperCase()}`;
    const prov = opts?.provenance || opts?.telemetry?.provenance;

    onEntityClick?.({
      type: 'shipment',
      id: shipmentId,
      shipmentId,
      ref: refNumber,
      coords: { lat: coords[1], lng: coords[0] },
    });

    // 1. Immediate loading popup — paper frame so the card does not jump
    showPopup(coords, waybillLoading(kindLabel(mode), refNumber));

    try {
      const detail = await getShipmentDetail(shipmentId);
      const slaStr = detail.strictest_sla_deadline
        ? new Date(detail.strictest_sla_deadline).toLocaleString('en-US', {
            month: 'short',
            day: 'numeric',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit',
            hour12: false,
          })
        : 'No SLA';

      const ordersCount = detail.orders?.length ?? 0;
      const legsCount = detail.legs?.length ?? 0;
      const onTimeOrders = detail.orders?.filter(o => o.sla_status === 'ON_TIME').length ?? 0;
      const lateOrders = detail.orders?.filter(o => o.sla_status === 'LATE').length ?? 0;
      const statusCol = detail.status === 'DELIVERED' ? '#027A48' : detail.status === 'DELAYED' ? '#B42318' : '#B54708';

      const rows: WaybillRow[] = [
        { label: 'status', value: String(detail.status ?? '—') },
        { label: 'lane', value: `${detail.origin ?? '—'} \u2192 ${detail.destination ?? '—'}` },
        { label: 'sla deadline', value: slaStr, emphasis: detail.status === 'DELAYED' },
        { label: 'cargo class', value: String(detail.cargo_class || 'STANDARD') },
        { label: 'containers', value: `${detail.container_count ?? 1}` },
        { label: 'route legs', value: `${legsCount}` },
        { label: 'orders', value: `${ordersCount} \u00b7 ${onTimeOrders} on-time \u00b7 ${lateOrders} late` },
      ];

      if (opts?.telemetry) {
        rows.push({
          label: 'telemetry',
          value: `${opts.telemetry.speed || '\u2014'} \u00b7 ${opts.telemetry.heading || '\u2014'}`,
        });
      }

      showPopup(coords, waybillCard({
        kind: kindLabel(mode),
        reference: refNumber,
        provenance: prov || (detail as any).provenance,
        rows,
        footer: opts?.telemetry?.provenance
          ? `Position ${String(opts.telemetry.provenance)}. Route is a planner recommendation.`
          : 'Route is a planner recommendation, not an observed track.',
        minWidth: 292,
      }));

      onEntityClick?.({
        type: 'shipment',
        id: shipmentId,
        ref: refNumber,
        detail,
        coords: { lat: coords[1], lng: coords[0] },
      });
    } catch (fetchErr) {
      console.warn('[NexaFreight] Failed to load shipment detail:', fetchErr);
      const routeQuality = opts?.routeQuality || 'APPROXIMATE';
      const legSeq = opts?.sequence ?? opts?.legId ?? '1';
      showPopup(coords, waybillCard({
        kind: kindLabel(mode),
        reference: refNumber,
        provenance: opts?.provenance || prov,
        rows: [
          { label: 'status', value: String(opts?.status || 'PLANNED') },
          { label: 'segment', value: `leg #${legSeq}` },
          { label: 'route quality', value: routeQuality, emphasis: routeQuality !== 'EXACT' },
          { label: 'uuid', value: String(shipmentId) },
        ],
        footer: 'Detail record unavailable \u2014 showing map-side attributes only.',
      }));
    }
  }, [showPopup, onEntityClick]);

  const handleMarkerClick = useCallback(async (
    pos: PositionReport,
    coords: [number, number],
    normType: 'VESSEL' | 'TRUCK' | 'FLIGHT' | 'TRAIN'
  ) => {
    const assetId = String(pos.asset_id ?? '');
    const mode = normType === 'VESSEL' ? 'SEA' : normType === 'TRUCK' ? 'ROAD' : normType === 'TRAIN' ? 'RAIL' : 'AIR';
    const modeColor = mode === 'SEA' ? '#2547C8' : mode === 'AIR' ? '#B54708' : mode === 'RAIL' ? '#4B515D' : '#027A48';

    // 1. Cross-reference shipment ID
    let shipmentId: string | null = (pos as any).shipment_id || null;
    let legId: string | null = null;

    if (!shipmentId) {
      if (normType === 'VESSEL') {
        shipmentId = vesselToShipmentRef.current.get(assetId) || null;
      } else {
        const match = legToShipmentRef.current.get(assetId);
        if (match) {
          shipmentId = match.shipmentId;
          legId = assetId;
        }
      }
    }

    // 2. Fallback: Search routes features directly if not in lookup map
    if (!shipmentId && Array.isArray(routesFeaturesRef.current)) {
      for (const f of routesFeaturesRef.current) {
        const p = f.properties;
        if (normType === 'VESSEL' && p?.vessel_mmsi && String(p.vessel_mmsi) === assetId) {
          shipmentId = String(p.shipment_id);
          legId = String(p.leg_id || '');
          break;
        } else if (p?.leg_id && String(p.leg_id) === assetId) {
          shipmentId = String(p.shipment_id);
          legId = String(p.leg_id);
          break;
        }
      }
    }

    const speedStr = pos.speed_knots != null ? `${Number(pos.speed_knots).toFixed(1)} kts` : '—';
    const headingStr = pos.heading_deg != null && !isNaN(Number(pos.heading_deg)) ? `${Math.round(Number(pos.heading_deg))}°` : '—';
    const provStr = pos.provenance || 'REAL';

    if (!shipmentId) {
      // Unlinked asset: report the telemetry we actually have, nothing more.
      showPopup(coords, waybillCard({
        kind: kindLabel(mode),
        reference: assetId,
        provenance: provStr,
        rows: [
          { label: 'speed', value: speedStr },
          { label: 'heading', value: headingStr },
          { label: 'asset type', value: normType },
        ],
        footer: 'No shipment linked to this asset.',
      }));
      return;
    }

    await openShipmentInspector(shipmentId, coords, {
      mode,
      legId: legId || '—',
      telemetry: { speed: speedStr, heading: headingStr, provenance: provStr, assetId, assetType: normType },
    });
  }, [openShipmentInspector, showPopup]);

  // Create aircraft icon on canvas (for WebGL symbol layer)
  const createIcon = useCallback((map: maplibregl.Map, id: string, color: string, size: number) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const cx = size / 2, cy = size / 2;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, cy - size * 0.4);
    ctx.lineTo(cx - size * 0.12, cy + size * 0.1);
    ctx.lineTo(cx - size * 0.4, cy + size * 0.2);
    ctx.lineTo(cx - size * 0.4, cy + size * 0.3);
    ctx.lineTo(cx - size * 0.12, cy + size * 0.15);
    ctx.lineTo(cx, cy + size * 0.35);
    ctx.lineTo(cx + size * 0.12, cy + size * 0.15);
    ctx.lineTo(cx + size * 0.4, cy + size * 0.3);
    ctx.lineTo(cx + size * 0.4, cy + size * 0.2);
    ctx.lineTo(cx + size * 0.12, cy + size * 0.1);
    ctx.closePath();
    ctx.fill();
    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  const createDot = useCallback((map: maplibregl.Map, id: string, color: string, size: number) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(size/2, size/2, size/2 - 1, 0, Math.PI * 2);
    ctx.fill();
    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  const createTruckIcon = useCallback((map: maplibregl.Map, id: string, color: string = '#027A48', size: number = 28) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const cx = size / 2, cy = size / 2;

    // Dark badge background with emerald border
    ctx.fillStyle = '#16181D';
    ctx.beginPath();
    ctx.roundRect(1, 1, size - 2, size - 2, 4);
    ctx.fill();
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = color;
    ctx.stroke();

    // 53ft intermodal container box
    ctx.fillStyle = color;
    ctx.fillRect(cx - 9, cy - 4, 12, 8);

    // Corrugated container panel ribs
    ctx.strokeStyle = '#F6F7F4';
    ctx.lineWidth = 0.6;
    for (let x = cx - 7; x <= cx + 1; x += 2) {
      ctx.beginPath();
      ctx.moveTo(x, cy - 3.5); ctx.lineTo(x, cy + 3.5);
      ctx.stroke();
    }

    // Semi-tractor cab
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx + 4, cy - 4);
    ctx.lineTo(cx + 7, cy - 4);
    ctx.lineTo(cx + 9.5, cy - 1);
    ctx.lineTo(cx + 9.5, cy + 4);
    ctx.lineTo(cx + 4, cy + 4);
    ctx.closePath();
    ctx.fill();

    // Windshield
    ctx.fillStyle = '#F6F7F4';
    ctx.fillRect(cx + 6, cy - 3, 2.5, 2.5);

    // Wheels
    ctx.fillStyle = '#0F172A';
    ctx.strokeStyle = '#D4D5D0';
    ctx.lineWidth = 0.6;
    const wheels = [cx - 7, cx - 3, cx + 7];
    wheels.forEach(wx => {
      ctx.beginPath();
      ctx.arc(wx, cy + 5, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    });

    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  const createWarehouseIcon = useCallback((map: maplibregl.Map, id: string, color: string = '#2547C8', size: number = 28) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const cx = size / 2, cy = size / 2;

    // Outer tile: Chartroom paper/dark badge with hairline border
    ctx.fillStyle = '#16181D';
    ctx.beginPath();
    ctx.roundRect(1, 1, size - 2, size - 2, 4);
    ctx.fill();
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = '#D4D5D0';
    ctx.stroke();

    // Symmetrical warehouse roofline with industrial gables
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx - 9, cy - 2);
    ctx.lineTo(cx, cy - 8);
    ctx.lineTo(cx + 9, cy - 2);
    ctx.lineTo(cx + 9, cy + 9);
    ctx.lineTo(cx - 9, cy + 9);
    ctx.closePath();
    ctx.fill();

    // 3 roll-up loading dock bay doors
    ctx.fillStyle = '#F6F7F4';
    ctx.fillRect(cx - 7, cy + 2, 3.5, 7);
    ctx.fillRect(cx - 1.75, cy + 2, 3.5, 7);
    ctx.fillRect(cx + 3.5, cy + 2, 3.5, 7);

    // Roll-up door slat horizontal ribs
    ctx.strokeStyle = '#16181D';
    ctx.lineWidth = 0.6;
    for (let y = cy + 4; y <= cy + 8; y += 2) {
      ctx.beginPath();
      ctx.moveTo(cx - 7, y); ctx.lineTo(cx - 3.5, y);
      ctx.moveTo(cx - 1.75, y); ctx.lineTo(cx + 1.75, y);
      ctx.moveTo(cx + 3.5, y); ctx.lineTo(cx + 7, y);
      ctx.stroke();
    }

    // Overhead crane / gantry beam
    ctx.fillStyle = '#F6F7F4';
    ctx.fillRect(cx - 8, cy - 3, 16, 1.2);

    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  const createICDIcon = useCallback((map: maplibregl.Map, id: string, color: string = '#475569', size: number = 28) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const cx = size / 2, cy = size / 2;

    // Dark badge background with steel rail border
    ctx.fillStyle = '#16181D';
    ctx.beginPath();
    ctx.roundRect(1, 1, size - 2, size - 2, 4);
    ctx.fill();
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = '#94A3B8';
    ctx.stroke();

    // Intermodal rail container crane / gantry frame
    ctx.strokeStyle = '#64748B';
    ctx.lineWidth = 1.2;
    ctx.strokeRect(cx - 8, cy - 8, 16, 11);

    // Gantry top rail
    ctx.fillStyle = '#94A3B8';
    ctx.fillRect(cx - 9, cy - 9, 18, 2);

    // Suspended intermodal shipping container
    ctx.fillStyle = '#2547C8';
    ctx.fillRect(cx - 5.5, cy - 5, 11, 6.5);
    ctx.strokeStyle = '#F6F7F4';
    ctx.lineWidth = 0.5;
    ctx.strokeRect(cx - 5.5, cy - 5, 11, 6.5);

    // Railway tracks and cross-ties at the base
    ctx.strokeStyle = '#D4D5D0';
    ctx.lineWidth = 1;
    // Cross-ties
    for (let x = cx - 8; x <= cx + 8; x += 3.5) {
      ctx.beginPath();
      ctx.moveTo(x, cy + 5.5);
      ctx.lineTo(x, cy + 9.5);
      ctx.stroke();
    }
    // Rails
    ctx.strokeStyle = '#CBD5E1';
    ctx.lineWidth = 0.8;
    ctx.beginPath();
    ctx.moveTo(cx - 9, cy + 6.5);
    ctx.lineTo(cx + 9, cy + 6.5);
    ctx.moveTo(cx - 9, cy + 8.5);
    ctx.lineTo(cx + 9, cy + 8.5);
    ctx.stroke();

    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  const createAirportIcon = useCallback((map: maplibregl.Map, id: string, color: string = '#D97706', size: number = 28) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const cx = size / 2, cy = size / 2;

    // Dark badge background with aviation amber border
    ctx.fillStyle = '#16181D';
    ctx.beginPath();
    ctx.roundRect(1, 1, size - 2, size - 2, 4);
    ctx.fill();
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = '#F59E0B';
    ctx.stroke();

    // Airport runway intersection cross lines
    ctx.strokeStyle = 'rgba(246, 247, 244, 0.35)';
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(cx - 8, cy - 8); ctx.lineTo(cx + 8, cy + 8);
    ctx.moveTo(cx + 8, cy - 8); ctx.lineTo(cx - 8, cy + 8);
    ctx.stroke();

    // Swept-wing cargo jet silhouette
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx, cy - 8);
    ctx.lineTo(cx + 1.5, cy - 4);
    ctx.lineTo(cx + 9, cy + 1);
    ctx.lineTo(cx + 9, cy + 3);
    ctx.lineTo(cx + 2, cy);
    ctx.lineTo(cx + 1.8, cy + 5);
    ctx.lineTo(cx + 5, cy + 7);
    ctx.lineTo(cx + 5, cy + 8.5);
    ctx.lineTo(cx, cy + 7.5);
    ctx.lineTo(cx - 5, cy + 8.5);
    ctx.lineTo(cx - 5, cy + 7);
    ctx.lineTo(cx - 1.8, cy + 5);
    ctx.lineTo(cx - 2, cy);
    ctx.lineTo(cx - 9, cy + 3);
    ctx.lineTo(cx - 9, cy + 1);
    ctx.lineTo(cx - 1.5, cy - 4);
    ctx.closePath();
    ctx.fill();

    // Jet cockpit window
    ctx.fillStyle = '#F6F7F4';
    ctx.fillRect(cx - 0.75, cy - 6, 1.5, 1.5);

    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  const createPortIcon = useCallback((map: maplibregl.Map, id: string, color: string = '#2547C8', size: number = 28) => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = size; canvas.height = size;
    const ctx = canvas.getContext('2d')!;
    const cx = size / 2, cy = size / 2;

    // Dark badge background with maritime cobalt border
    ctx.fillStyle = '#16181D';
    ctx.beginPath();
    ctx.roundRect(1, 1, size - 2, size - 2, 4);
    ctx.fill();
    ctx.lineWidth = 1.2;
    ctx.strokeStyle = color;
    ctx.stroke();

    // Precision Anchor Glyph
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.8;
    ctx.lineCap = 'round';

    // Ring at top
    ctx.beginPath();
    ctx.arc(cx, cy - 6, 2.2, 0, Math.PI * 2);
    ctx.stroke();

    // Crossbar / Stock
    ctx.beginPath();
    ctx.moveTo(cx - 5.5, cy - 3);
    ctx.lineTo(cx + 5.5, cy - 3);
    ctx.stroke();

    // Shank
    ctx.beginPath();
    ctx.moveTo(cx, cy - 4);
    ctx.lineTo(cx, cy + 6.5);
    ctx.stroke();

    // Flukes (curved bottom arms)
    ctx.beginPath();
    ctx.arc(cx, cy + 1.5, 6, 0.2 * Math.PI, 0.8 * Math.PI, false);
    ctx.stroke();

    // Fluke arrow points
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(cx - 5.8, cy + 3.8); ctx.lineTo(cx - 4.5, cy + 6.5); ctx.lineTo(cx - 3.5, cy + 4.5);
    ctx.closePath();
    ctx.fill();

    ctx.beginPath();
    ctx.moveTo(cx + 5.8, cy + 3.8); ctx.lineTo(cx + 4.5, cy + 6.5); ctx.lineTo(cx + 3.5, cy + 4.5);
    ctx.closePath();
    ctx.fill();

    map.addImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
  }, []);

  useEffect(() => {
    if (!mapRef.current) return;
    const map = mapRef.current;

    // ── DEMO MODE SPINNING ──
    let spinReq: number | undefined = undefined;
    let isSpinning = false;
    
    const startSpinning = () => {
      if (!map) return;
      isSpinning = true;
      let lastTime = performance.now();
      
      const frame = (time: number) => {
        if (!isSpinning) return;
        
        // Only spin if the user is not actively dragging or zooming the map
        if (!map.isMoving() && !map.isZooming()) {
          const dt = time - lastTime;
          const center = map.getCenter();
          // Adjust spin speed: 0.5 degrees per second
          center.lng += (0.5 * dt) / 1000;
          map.setCenter(center);
        }
        
        lastTime = time;
        spinReq = requestAnimationFrame(frame);
      };
      
      spinReq = requestAnimationFrame(frame);
    };

    if (demoMode) {
      startSpinning();
    } else {
      isSpinning = false;
      if (spinReq) cancelAnimationFrame(spinReq);
    }

    return () => {
      isSpinning = false;
      if (spinReq) cancelAnimationFrame(spinReq);
      if (typeof window !== 'undefined' && (window as any)._globeSpinTimer) {
        clearInterval((window as any)._globeSpinTimer);
      }
    };
  }, [mapReady, demoMode]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    
    // OpenFreeMap Positron (clean paper cartography, no API key, zero watermarks)
    const isPaper = initialStyleRef.current === 'paper';
    const openFreeMapStyle = isPaper
      ? 'https://tiles.openfreemap.org/styles/positron'
      : 'https://tiles.openfreemap.org/styles/dark';

    const container = containerRef.current;
    const baseOptions = {
      container,
      style: openFreeMapStyle,
      center: [20.0, 25.0] as [number, number],
      zoom: 2.8,
      minZoom: 1.5,
      maxZoom: 18,
      renderWorldCopies: false, // Restrict to exactly one world map length (no infinite horizontal wrap)
      attributionControl: false as const,
      maxPitch: 60,
      fadeDuration: 0, // Instant tile rendering for crisp 60fps interaction
      transformRequest: (url: string) => {
        return { url };
      },
    };

    // MapLibre asks for a high-performance WebGL2 context and throws outright if it
    // cannot get one. Some machines refuse that exact request while still granting a
    // plainer context — a blocklisted discrete GPU, a driver Chrome only trusts for
    // WebGL1 — so walk down to weaker requests before giving up.
    const attributeFallbacks: maplibregl.MapOptions['canvasContextAttributes'][] = [
      undefined,
      { powerPreference: 'low-power', failIfMajorPerformanceCaveat: false },
      { contextType: 'webgl2', powerPreference: 'low-power', failIfMajorPerformanceCaveat: false },
    ];

    let map: maplibregl.Map | undefined;
    for (const canvasContextAttributes of attributeFallbacks) {
      try {
        map = new maplibregl.Map(
          canvasContextAttributes ? { ...baseOptions, canvasContextAttributes } : baseOptions
        );
        break;
      } catch (e: any) {
        // A failed constructor leaves its canvas behind; the next attempt needs a clean container.
        container.innerHTML = '';
        if (canvasContextAttributes === attributeFallbacks[attributeFallbacks.length - 1]) throw e;
        console.warn('[NexaFreight] WebGL context rejected, retrying with weaker attributes:', e instanceof Error ? e.message : e);
      }
    }
    if (!map) return;

    map.on('error', (e) => {
      console.warn('[NexaFreight Map Error]:', e.error?.message || e);
    });

    map.on('load', () => {
      mapRef.current = map;
      map.resize();
      map.setRenderWorldCopies(false);
      try {
        map.setMaxBounds([[-180, -85], [180, 85]]);
      } catch (err) {
        console.warn('[NexaFreight] Could not set maxBounds:', err);
      }
      map.setMinZoom(1.5);
      
      // Theme colors
      const isGhost = theme === 'ghost';
      const phantomPurple = '#B388FF';
      const phantomDark = '#1A0040';
      /* The first paint reads the same `--map-*` properties the recolour
         effects below push in later. Deriving them from `theme` here as well
         is what let the two drift: the effect's ghost palette was four
         distinct violets, this block's was one, and whichever ran last won. */
      const bootStyle = getComputedStyle(document.body);
      const boot = MAP_DEFAULTS;
      const cameraColor = boot.cctv;
      const flightCom = boot.flightCivil;
      const flightPriv = boot.flightPrivate;
      const flightGov = boot.flightGov;
      const flightMil = boot.flightMilitary;

      // Create icons — NexaFreight Unified Palette
      createIcon(map, 'plane-cyan', flightCom, 24);   
      createIcon(map, 'plane-green', flightPriv, 24);   
      createIcon(map, 'plane-pink', flightGov, 24);    
      createIcon(map, 'plane-red', flightMil, 24);     
      createIcon(map, 'plane-grey', boot.flightUnknown, 24);
      createDot(map, 'dot-gold', isGhost ? phantomPurple : '#D4AF37', 8);
      createDot(map, 'dot-red', isGhost ? phantomPurple : '#D32F2F', 10);
      createDot(map, 'dot-orange', isGhost ? phantomPurple : '#E65100', 10);
      createDot(map, 'dot-green', isGhost ? phantomPurple : '#26A69A', 10);
      createDot(map, 'dot-fire', isGhost ? phantomPurple : '#E65100', 10);
      createDot(map, 'dot-cctv', cameraColor, 10);
      createTruckIcon(map, 'truck-green', '#027A48', 28);
      createAirportIcon(map, 'airport-orange', '#D97706', 28);
      createWarehouseIcon(map, 'warehouse-blue', '#2547C8', 28);
      createICDIcon(map, 'icd-rail', '#475569', 28);
      createPortIcon(map, 'port-anchor', '#2547C8', 28);

      const sources = ['ports', 'airports', 'routes', 'trucks', 'flights', 'jets', 'private-fl', 'satellites', 'earthquakes', 'day-night', 'cctv', 'fires', 'weather', 'infrastructure', 'maritime', 'maritime-choke', 'maritime-ships', 'warehouses', 'disruptions', 'live-news', 'balloons', 'radiation', 'sdk-entities', 'sdk-links', 'network-mesh'];
      sources.forEach(s => map.addSource(s, { type: 'geojson', data: EMPTY_FC }));

      // Immediately populate pre-defined cargo airport hubs
      const airInitSrc = map.getSource('airports') as maplibregl.GeoJSONSource | undefined;
      if (airInitSrc) {
        airInitSrc.setData(CARGO_AIRPORTS_FC as never);
      }

      // ── FLIGHT ROUTE VISUALIZATION SOURCES & LAYERS ──

      // Warning icon generator (parameterized — eliminates 3x copy-paste)
      const createWarningIcon = (id: string, color: string) => {
        const s = 20;
        const c = document.createElement('canvas');
        c.width = s; c.height = s;
        const ctx = c.getContext('2d')!;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(s/2, 1);
        ctx.lineTo(s - 1, s - 1);
        ctx.lineTo(1, s - 1);
        ctx.closePath();
        ctx.fill();
        ctx.fillStyle = '#000';
        ctx.font = 'bold 11px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText('!', s/2, s - 4);
        map.addImage(id, { width: s, height: s, data: new Uint8Array(ctx.getImageData(0, 0, s, s).data) });
      };
      createWarningIcon('warn-icon', '#D32F2F');
      createWarningIcon('warn-orange', '#E65100');
      createWarningIcon('warn-yellow', '#F9A825');

      // Day/Night
      map.addLayer({ id: 'day-night-fill', type: 'fill', source: 'day-night', paint: { 'fill-color': isGhost ? '#0D0030' : '#000022', 'fill-opacity': 0.35 }});

      // ── NexaFreight Route Layers (Step 5 — Full Multimodal Maritime, Aviation, Road & Rail) ──
      // 1. Sea routes: deep maritime cobalt with navigational dashed track
      map.addLayer({
        id: 'routes-sea-glow',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'SEA'],
        paint: {
          'line-color': '#2547C8',
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 3.5, 5, 5.5, 10, 8.0],
          'line-opacity': 0.22,
          'line-blur': 2,
        },
      });

      map.addLayer({
        id: 'routes-sea',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'SEA'],
        paint: {
          'line-color': '#2547C8',
          'line-dasharray': [3, 2],
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 1.8, 5, 2.8, 10, 4.5],
          'line-opacity': 0.95,
        },
      });

      map.addLayer({
        id: 'routes-sea-arrows',
        type: 'symbol',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'SEA'],
        layout: {
          'symbol-placement': 'line',
          'symbol-spacing': 150,
          'text-field': '▶',
          'text-size': ['interpolate', ['linear'], ['zoom'], 1, 8, 5, 12, 10, 16],
          'text-keep-upright': false,
        },
        paint: {
          'text-color': '#2547C8',
        },
      });

      // 2. Air routes: High-altitude golden amber parabolic flight corridors with glowing contrails
      map.addLayer({
        id: 'routes-air-glow',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'AIR'],
        paint: {
          'line-color': '#F59E0B',
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 5.0, 5, 8.0, 10, 12.0],
          'line-opacity': 0.28,
          'line-blur': 3,
        },
      });

      map.addLayer({
        id: 'routes-air',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'AIR'],
        paint: {
          'line-color': '#D97706',
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 2.2, 5, 3.4, 10, 5.0],
          'line-opacity': 0.95,
        },
      });

      map.addLayer({
        id: 'routes-air-dash',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'AIR'],
        paint: {
          'line-color': '#FEF08A',
          'line-dasharray': [4, 6],
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 1.4, 5, 2.0, 10, 3.0],
          'line-opacity': 0.9,
        },
      });

      map.addLayer({
        id: 'routes-air-arrows',
        type: 'symbol',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'AIR'],
        layout: {
          'symbol-placement': 'line',
          'symbol-spacing': 180,
          'text-field': '✈',
          'text-size': ['interpolate', ['linear'], ['zoom'], 1, 9, 5, 13, 10, 16],
          'text-keep-upright': false,
        },
        paint: {
          'text-color': '#FEF08A',
          'text-halo-color': '#B45309',
          'text-halo-width': 1,
        },
      });

      // 3. Road routes: solid highway emerald (#027A48)
      map.addLayer({
        id: 'routes-road-glow',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'ROAD'],
        paint: {
          'line-color': '#027A48',
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 4.0, 5, 6.5, 10, 9.0],
          'line-opacity': 0.35,
          'line-blur': 2,
        },
      });

      map.addLayer({
        id: 'routes-road',
        type: 'line',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'ROAD'],
        paint: {
          'line-color': '#027A48',
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 2.5, 5, 4.0, 10, 5.5],
          'line-opacity': 0.95,
        },
      });

      map.addLayer({
        id: 'routes-road-arrows',
        type: 'symbol',
        source: 'routes',
        filter: ['==', ['get', 'mode'], 'ROAD'],
        layout: {
          'symbol-placement': 'line',
          'symbol-spacing': 100,
          'text-field': '▶',
          'text-size': ['interpolate', ['linear'], ['zoom'], 1, 8, 5, 10, 10, 14],
          'text-keep-upright': false,
        },
        paint: {
          'text-color': '#0B0D19',
          'text-halo-color': '#027A48',
          'text-halo-width': 1,
        },
      });

      // 4. Rail routes: Dual-layer authentic Railway Track Cartography (Dark Bed + Silver Cross-Ties)
      map.addLayer({
        id: 'routes-rail-bed',
        type: 'line',
        source: 'routes',
        filter: ['in', ['get', 'mode'], ['literal', ['RAIL', 'TRAIN']]],
        paint: {
          'line-color': '#0F172A',
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 3.2, 5, 4.8, 10, 7.2],
          'line-opacity': 0.95,
        },
      });

      map.addLayer({
        id: 'routes-rail',
        type: 'line',
        source: 'routes',
        filter: ['in', ['get', 'mode'], ['literal', ['RAIL', 'TRAIN']]],
        paint: {
          'line-color': '#F8FAFC',
          'line-dasharray': [1.2, 1.8],
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 2.2, 5, 3.6, 10, 5.4],
          'line-opacity': 0.95,
        },
      });

      map.addLayer({
        id: 'routes-rail-core',
        type: 'line',
        source: 'routes',
        filter: ['in', ['get', 'mode'], ['literal', ['RAIL', 'TRAIN']]],
        paint: {
          'line-color': '#64748B',
          'line-width': ['interpolate', ['linear'], ['zoom'], 1, 1.0, 5, 1.6, 10, 2.4],
          'line-opacity': 0.85,
        },
      });

      // ── Road Trucks Markers Layer ──
      map.addLayer({
        id: 'routes-trucks-glow',
        type: 'circle',
        source: 'trucks',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 4, 5, 7, 10, 10],
          'circle-color': '#027A48',
          'circle-opacity': 0.3,
          'circle-blur': 1,
        },
      });

      map.addLayer({
        id: 'routes-trucks-layer',
        type: 'symbol',
        source: 'trucks',
        layout: {
          'icon-image': 'truck-green',
          'icon-size': 0.85,
          'icon-allow-overlap': true,
          'text-field': ['get', 'truck_id'],
          'text-size': 10,
          'text-font': ['JetBrains Mono Bold', 'Open Sans Bold'],
          'text-offset': [0, 1.4],
          'text-anchor': 'top',
          'text-allow-overlap': false,
        },
        paint: {
          'text-color': '#027A48',
          'text-halo-color': 'rgba(246,247,244,0.95)',
          'text-halo-width': 1.5,
          'text-opacity': 0.95,
        },
      });

      // ── NexaFreight Ports Layer (Step 4 — Navigational Anchor Badge + Congestion Halo) ──
      map.addLayer({
        id: 'ports-glow',
        type: 'circle',
        source: 'ports',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 7, 5, 12, 10, 16],
          'circle-color': [
            'interpolate',
            ['linear'],
            ['coalesce', ['get', 'congestion_index'], 1.0],
            0.0, '#027A48',   // low congestion: law green
            0.8, '#027A48',   // below baseline: law green
            1.0, '#B54708',   // baseline normal: law amber
            1.4, '#B54708',   // elevated congestion: law amber
            2.0, '#B42318'    // severe congestion: exception red
          ],
          'circle-opacity': 0.32,
          'circle-blur': 0.8,
        },
      });

      map.addLayer({
        id: 'ports-layer',
        type: 'symbol',
        source: 'ports',
        layout: {
          'icon-image': 'port-anchor',
          'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.75, 5, 0.9, 10, 1.15],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'text-field': ['get', 'un_locode'],
          'text-size': 10,
          'text-font': ['JetBrains Mono Bold', 'Open Sans Bold'],
          'text-offset': [0, 1.4],
          'text-anchor': 'top',
          'text-allow-overlap': false,
        },
        paint: {
          'text-color': '#16181D',
          'text-halo-color': 'rgba(246,247,244,0.95)',
          'text-halo-width': 1.5,
          'text-opacity': 0.95,
        },
      });

      map.addLayer({
        id: 'ports-label',
        type: 'symbol',
        source: 'ports',
        minzoom: 5,
        layout: {
          'text-field': ['get', 'name'],
          'text-size': 11,
          'text-font': ['Open Sans Bold', 'JetBrains Mono Bold'],
          'text-offset': [0, 2.5],
          'text-anchor': 'top',
          'text-allow-overlap': false,
        },
        paint: {
          'text-color': '#16181D',
          'text-halo-color': 'rgba(246,247,244,0.95)',
          'text-halo-width': 1.6,
        },
      });

      // ── International Cargo Airports Layer ──
      map.addLayer({
        id: 'airports-glow',
        type: 'circle',
        source: 'airports',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 5, 5, 8, 10, 12],
          'circle-color': '#D97706',
          'circle-opacity': 0.25,
          'circle-blur': 1,
        },
      });

      map.addLayer({
        id: 'airports-layer',
        type: 'symbol',
        source: 'airports',
        layout: {
          'icon-image': 'airport-orange',
          'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.75, 5, 0.9, 10, 1.15],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'text-field': ['get', 'code'],
          'text-size': 10,
          'text-font': ['JetBrains Mono Bold', 'Open Sans Bold'],
          'text-offset': [0, 1.4],
          'text-allow-overlap': false,
        },
        paint: {
          'text-color': '#16181D',
          'text-halo-color': 'rgba(246,247,244,0.95)',
          'text-halo-width': 1.5,
          'text-opacity': 0.95,
        },
      });

      ['routes-sea', 'routes-air', 'routes-road', 'routes-rail', 'routes-rail-bed', 'routes-trucks-layer', 'warehouses-layer', 'ports-layer', 'airports-layer'].forEach(layer => {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
      });

      // ── NexaFreight Inland Warehouses & Intermodal Depots Layer ──
      map.addLayer({
        id: 'warehouses-layer',
        type: 'symbol',
        source: 'warehouses',
        layout: {
          'icon-image': [
            'case',
            ['==', ['get', 'facility_type'], 'INLAND_CONTAINER_DEPOT'],
            'icd-rail',
            ['==', ['get', 'facility_type'], 'AIR_FREIGHT_STAGING'],
            'airport-orange',
            'warehouse-blue'
          ],
          'icon-size': ['interpolate', ['linear'], ['zoom'], 1, 0.8, 5, 0.95, 10, 1.2],
          'icon-allow-overlap': true,
          'icon-ignore-placement': true,
          'text-field': ['get', 'name'],
          'text-size': 10,
          'text-font': ['JetBrains Mono Bold', 'Open Sans Bold'],
          'text-offset': [0, 1.4],
          'text-anchor': 'top',
        },
        paint: {
          'text-color': '#2547C8',
          'text-halo-color': 'rgba(246,247,244,0.95)',
          'text-halo-width': 1.5,
          'icon-opacity': ['interpolate', ['linear'], ['zoom'], 1, 0.7, 5, 1],
        },
      });

      // ── Disruption Sonar Rings & Chokepoint Alerts (Concentric Red/Amber Radar) ──
      map.addLayer({
        id: 'disruptions-outer-pulse',
        type: 'circle',
        source: 'disruptions',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 16, 4, 30, 8, 54],
          'circle-color': ['match', ['get', 'severity'], 'CRITICAL', '#B42318', 'HIGH', '#B54708', '#B54708'],
          'circle-opacity': 0.16,
          'circle-stroke-width': 2,
          'circle-stroke-color': ['match', ['get', 'severity'], 'CRITICAL', '#B42318', 'HIGH', '#B54708', '#B54708'],
          'circle-stroke-opacity': 0.75,
        },
      });

      map.addLayer({
        id: 'disruptions-inner-ring',
        type: 'circle',
        source: 'disruptions',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 9, 4, 18, 8, 32],
          'circle-color': ['match', ['get', 'severity'], 'CRITICAL', 'rgba(180, 35, 24, 0.15)', 'HIGH', 'rgba(181, 71, 8, 0.15)', 'rgba(181, 71, 8, 0.15)'],
          'circle-stroke-width': 1.5,
          'circle-stroke-color': ['match', ['get', 'severity'], 'CRITICAL', '#B42318', 'HIGH', '#B54708', '#B54708'],
          'circle-stroke-opacity': 0.9,
        },
      });

      map.addLayer({
        id: 'disruptions-core',
        type: 'circle',
        source: 'disruptions',
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 1, 3.5, 4, 5.5, 8, 7.5],
          'circle-color': ['match', ['get', 'severity'], 'CRITICAL', '#B42318', 'HIGH', '#B54708', '#B54708'],
          'circle-stroke-width': 2,
          'circle-stroke-color': '#FFFFFF',
          'circle-opacity': 1,
        },
      });

      map.addLayer({
        id: 'disruptions-label',
        type: 'symbol',
        source: 'disruptions',
        layout: {
          'text-field': ['get', 'callout_tag'],
          'text-size': 10,
          'text-font': ['Open Sans Bold'],
          'text-offset': [1.2, 1.4],
          'text-anchor': 'top-left',
          'text-allow-overlap': true,
        },
        paint: {
          'text-color': '#FFFFFF',
          'text-halo-color': ['match', ['get', 'severity'], 'CRITICAL', '#DC2626', 'HIGH', '#EA580C', '#D97706'],
          'text-halo-width': 3,
        },
      });

      ['ports-layer', 'airports-layer', 'warehouses-layer', 'disruptions-outer-pulse', 'disruptions-core', 'disruptions-label'].forEach(layer => {
        map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
        map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
      });

      // GDELT



      // ══ NETWORK INTEL — Live Malware (abuse.ch) — crimson threat ══
      /* Sized by how many live malicious URLs the host serves. A box running
         forty payloads and one running a single sample were the same dot
         before, and they are not the same thing. */
      /* Arrival beacon — expands and fades over the minute after a detection
         is pushed, then the feature drops out of the source entirely. */

      // ── NETWORK INTEL MESH (SDK STYLE) ──
      map.addLayer({ id: 'network-mesh-atmo', type: 'line', source: 'network-mesh', paint: {

        'line-width': ['interpolate',['linear'],['zoom'], 1, 2, 5, 4, 10, 8],
        'line-opacity': 0.08,
        'line-blur': 4,
      }});
      map.addLayer({ id: 'network-mesh-glow', type: 'line', source: 'network-mesh', paint: {

        'line-width': ['interpolate',['linear'],['zoom'], 1, 1, 5, 2, 10, 4],
        'line-opacity': 0.2,
        'line-blur': 1.5,
      }});
      map.addLayer({ id: 'network-mesh-core', type: 'line', source: 'network-mesh', paint: {

        'line-width': ['interpolate',['linear'],['zoom'], 1, 0.2, 5, 0.5, 10, 1.5],
        'line-opacity': 0.4,
      }});

      // ══ LIVE CYBER ATTACKS — dark wire network (source → target) ══
      // Animated dashed flow line — fast marching ants in black

      
      /* ── Cloudflare Radar — internet outages (country-scoped) ── */

      /* ── Cloudflare Radar — layer-3 attack origin share ── */

      // Weather Events (NASA EONET) — deep violet
      map.addLayer({ id: 'weather-glow', type: 'circle', source: 'weather', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,12, 5,20, 10,30],
        'circle-color': '#7E57C2', 'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'weather-dots', type: 'circle', source: 'weather', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,5, 5,8, 10,14],
        'circle-color': ['match', ['get','icon'], 'cyclone','#7E57C2', 'volcano','#D32F2F', '#7E57C2'],
        'circle-opacity': 0.75,
        'circle-stroke-width': 1.5, 'circle-stroke-color': '#7E57C2', 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'weather-label', type: 'symbol', source: 'weather', layout: {
        'text-field': ['get','title'], 'text-size': 9, 'text-font': ['Open Sans Regular'],
        'text-offset': [0, 2], 'text-max-width': 14, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#7E57C2', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.8 }});

      // Nuclear Infrastructure — teal / amber risk
      map.addLayer({ id: 'infra-glow', type: 'circle', source: 'infrastructure', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,8, 5,14, 10,22],
        'circle-color': ['case', ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100', '#26A69A'],
        'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'infra-dots', type: 'circle', source: 'infrastructure', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,6, 10,10],
        'circle-color': ['case', 
          ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100',
          ['==', ['get','status'], 'Active Conflict Zone'], '#D32F2F', 
          ['==', ['get','status'], 'Destroyed / Decommissioning'], '#546E7A', 
          '#26A69A'
        ],
        'circle-opacity': 0.75,
        'circle-stroke-width': 1.5, 'circle-stroke-color': ['case', ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100', '#26A69A'], 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'infra-label', type: 'symbol', source: 'infrastructure', minzoom: 5, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Open Sans Regular'],
        'text-offset': [0, 2], 'text-max-width': 14, 'text-allow-overlap': false,
      }, paint: { 'text-color': ['case', ['in', 'SEISMIC RISK', ['get', 'status']], '#E65100', '#26A69A'], 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.7 }});

      // Maritime — ports & naval bases — ocean teal
      map.addLayer({ id: 'maritime-glow', type: 'circle', source: 'maritime', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,6, 5,12, 10,20],
        'circle-color': ['match', ['get','type'], 'naval','#D32F2F', 'energy','#E65100', '#26C6DA'],
        'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'maritime-dots', type: 'circle', source: 'maritime', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,3, 5,5, 10,9],
        'circle-color': ['match', ['get','type'], 'naval','#D32F2F', 'energy','#E65100', '#26C6DA'],
        'circle-opacity': 0.8,
        'circle-stroke-width': 1.5, 'circle-stroke-color': ['match', ['get','type'], 'naval','#D32F2F', 'energy','#E65100', '#26C6DA'], 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'maritime-label', type: 'symbol', source: 'maritime', minzoom: 4, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Open Sans Regular'],
        'text-offset': [0, 1.8], 'text-max-width': 12, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#26C6DA', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.7 }});

      // Maritime chokepoints — amber threat spectrum
      map.addLayer({ id: 'choke-glow', type: 'circle', source: 'maritime-choke', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,10, 5,18, 10,28],
        'circle-color': '#B54708', 'circle-opacity': 0.1, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'choke-dots', type: 'circle', source: 'maritime-choke', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,7, 10,12],
        'circle-color': ['match', ['get','risk'], 'CRITICAL','#B42318', 'HIGH','#B54708', 'ELEVATED','#B54708', '#027A48'],
        'circle-opacity': 0.85,
        'circle-stroke-width': 1.5, 'circle-stroke-color': '#B54708', 'circle-stroke-opacity': 0.4,
      }});
      map.addLayer({ id: 'choke-label', type: 'symbol', source: 'maritime-choke', minzoom: 3, layout: {
        'text-field': ['get','name'], 'text-size': 10, 'text-font': ['Open Sans Bold'],
        'text-offset': [0, 2], 'text-max-width': 14, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#E65100', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.9 }});

      // Live News — muted rose
      map.addLayer({ id: 'news-glow', type: 'circle', source: 'live-news', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,8, 5,14, 10,22],
        'circle-color': '#EC407A', 'circle-opacity': 0.08, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'news-dots', type: 'circle', source: 'live-news', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,6, 10,10],
        'circle-color': '#EC407A', 'circle-opacity': 0.8,
        'circle-stroke-width': 1.5, 'circle-stroke-color': '#EC407A', 'circle-stroke-opacity': 0.4,
      }});
      map.addLayer({ id: 'news-label', type: 'symbol', source: 'live-news', minzoom: 4, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Open Sans Regular'],
        'text-offset': [0, 1.8], 'text-max-width': 12, 'text-allow-overlap': false,
      }, paint: { 'text-color': '#EC407A', 'text-halo-color': '#000', 'text-halo-width': 1, 'text-opacity': 0.8 }});

      // ══ IP SWEEP — Neighborhood device visualization ══

      // ══ SCAN TARGETS — Geolocated individual scans ══

      // Flight layers (WebGL symbol — GPU rendered, handles 50K+ smooth)
      const flightLayers = [
        { id: 'fl-commercial', src: 'flights', icon: 'plane-cyan' },
        { id: 'fl-private', src: 'private-fl', icon: 'plane-green' },
        { id: 'fl-jets', src: 'jets', icon: 'plane-pink' },
      ];
      flightLayers.forEach(l => {
        map.addLayer({ id: l.id, type: 'symbol', source: l.src, layout: {
          'icon-image': l.icon, 'icon-size': ['interpolate',['linear'],['zoom'], 1,0.4, 5,0.7, 10,1],
          'icon-rotate': ['get','heading'], 'icon-rotation-alignment': 'map', 'icon-allow-overlap': true, 'icon-ignore-placement': true,
        }, paint: { 'icon-opacity': 0.85 }});
      });

      // Route layers are added later (after setMapReady) so they render on top of everything.

      // Balloons (moving entities)
      map.addLayer({ id: 'balloon-dots', type: 'circle', source: 'balloons', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,3, 5,5, 10,7],
        'circle-color': ['get', 'color'],
        'circle-opacity': 0.8,
        'circle-stroke-width': 1, 'circle-stroke-color': '#fff', 'circle-stroke-opacity': 0.5,
      }});
      map.addLayer({ id: 'balloon-label', type: 'symbol', source: 'balloons', minzoom: 4, layout: {
        'text-field': ['get','callsign'], 'text-size': 9, 'text-font': ['Open Sans Regular'],
        'text-offset': [0, 1.2], 'text-max-width': 12, 'text-allow-overlap': false,
      }, paint: { 'text-color': ['get', 'color'], 'text-halo-color': '#000', 'text-halo-width': 1 }});

      // Radiation — violet base, threat spectrum for danger/warning
      map.addLayer({ id: 'rad-glow', type: 'circle', source: 'radiation', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,10, 5,20, 10,40],
        'circle-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'],
        'circle-opacity': 0.12, 'circle-blur': 1,
      }});
      map.addLayer({ id: 'rad-dots', type: 'circle', source: 'radiation', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,4, 5,6, 10,8],
        'circle-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'],
        'circle-opacity': 0.85,
        'circle-stroke-width': 1.5, 'circle-stroke-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'], 'circle-stroke-opacity': 0.35,
      }});
      map.addLayer({ id: 'rad-label', type: 'symbol', source: 'radiation', minzoom: 5, layout: {
        'text-field': ['concat', ['to-string', ['get','reading']], ' nSv/h'], 'text-size': 9, 'text-font': ['Open Sans Bold'],
        'text-offset': [0, 1.5], 'text-allow-overlap': false,
      }, paint: { 'text-color': ['match', ['get','status'], 'DANGER','#D32F2F', 'WARNING','#E65100', '#7E57C2'], 'text-halo-color': '#000', 'text-halo-width': 1 }});

      // ══ NexaFreight SDK — Lattice Intelligence Mesh ══
      // Polybolos Style: Delicate, translucent, steel-blue splined mesh

      // ── SEA domain (Distinct Solid Lines) ──
      // Removed glow to match the clean, diagrammatic look of submarinecablemap.com
      map.addLayer({ id: 'sdk-sea', type: 'line', source: 'sdk-links', filter: ['==',['get','domain'],'SEA'], paint: {
        'line-color': ['coalesce', ['get', 'color'], '#1976D2'], // Single solid color from properties
        'line-width': ['interpolate',['linear'],['zoom'], 1, 0.8, 5, 1.5, 10, 2.5],
        'line-opacity': ['interpolate',['linear'],['zoom'], 1, 0.3, 5, 0.5, 10, 0.7],
      }});

      // ── AIR domain (Steel Gray / Cyan) ──
      map.addLayer({ id: 'sdk-air-atmo', type: 'line', source: 'sdk-links', filter: ['==',['get','domain'],'AIR'], paint: {
        'line-color': '#4DD0E1',
        'line-width': ['interpolate',['linear'],['zoom'], 1, 1.5, 5, 5, 10, 8],
        'line-opacity': 0.04,
        'line-blur': 3,
      }});
      map.addLayer({ id: 'sdk-air-glow', type: 'line', source: 'sdk-links', filter: ['==',['get','domain'],'AIR'], paint: {
        'line-color': '#80DEEA',
        'line-width': ['interpolate',['linear'],['zoom'], 1, 0.8, 5, 2, 10, 4],
        'line-opacity': ['interpolate',['linear'],['zoom'], 1, 0.08, 5, 0.12, 10, 0.18],
        'line-blur': 1,
      }});
      map.addLayer({ id: 'sdk-air', type: 'line', source: 'sdk-links', filter: ['==',['get','domain'],'AIR'], paint: {
        'line-color': '#B2EBF2',
        'line-width': ['interpolate',['linear'],['zoom'], 1, 0.15, 5, 0.6, 10, 1.2],
        'line-opacity': ['interpolate',['linear'],['zoom'], 1, 0.2, 5, 0.35, 10, 0.5],
      }});

      // ── INTEL domain (Deep Steel / Violet) ──
      map.addLayer({ id: 'sdk-intel-atmo', type: 'line', source: 'sdk-links', filter: ['==',['get','domain'],'INTEL'], paint: {
        'line-color': '#7986CB',
        'line-width': ['interpolate',['linear'],['zoom'], 1, 2.5, 5, 7, 10, 12],
        'line-opacity': 0.06,
        'line-blur': 5,
      }});
      map.addLayer({ id: 'sdk-intel-glow', type: 'line', source: 'sdk-links', filter: ['==',['get','domain'],'INTEL'], paint: {
        'line-color': '#9FA8DA',
        'line-width': ['interpolate',['linear'],['zoom'], 1, 1.2, 5, 3, 10, 6],
        'line-opacity': ['interpolate',['linear'],['zoom'], 1, 0.12, 5, 0.18, 10, 0.25],
        'line-blur': 2,
      }});
      map.addLayer({ id: 'sdk-intel', type: 'line', source: 'sdk-links', filter: ['==',['get','domain'],'INTEL'], paint: {
        'line-color': '#C5CAE9',
        'line-width': ['interpolate',['linear'],['zoom'], 1, 0.3, 5, 1, 10, 2],
        'line-opacity': ['interpolate',['linear'],['zoom'], 1, 0.3, 5, 0.45, 10, 0.7],
      }});

      // Maritime Ships (moving entities) — ocean teal family
      map.addLayer({ id: 'ship-dots', type: 'circle', source: 'maritime-ships', paint: {
        'circle-radius': ['interpolate',['linear'],['zoom'], 1,2, 5,4, 10,6],
        'circle-color': ['match', ['get','type'], 'military','#B42318', 'tanker','#B54708', 'cargo','#2547C8', '#4B515D'],
        'circle-opacity': 0.75,
      }});
      map.addLayer({ id: 'ship-label', type: 'symbol', source: 'maritime-ships', minzoom: 5, layout: {
        'text-field': ['get','name'], 'text-size': 9, 'text-font': ['Open Sans Regular'],
        'text-offset': [0, 1.2], 'text-allow-overlap': false,
      }, paint: { 'text-color': ['match', ['get','type'], 'military','#B42318', 'tanker','#B54708', 'cargo','#2547C8', '#4B515D'], 'text-halo-color': 'rgba(246,247,244,0.95)', 'text-halo-width': 1 }});

      // ── Fetch & Populate NexaFreight Ports (Step 4) ──
      const loadPorts = async () => {
        try {
          const portsResp = await getPorts();
          let features: GeoJSON.Feature[] = [];
          if (portsResp?.type === 'FeatureCollection' && Array.isArray(portsResp.features)) {
            features = portsResp.features.map((f: any) => {
              const coords = f.geometry?.coordinates || [0, 0];
              // Invariant: coordinates must be [lon, lat], NOT [lat, lon]
              const lon = Number(f.properties?.lon ?? f.properties?.longitude ?? coords[0]);
              const lat = Number(f.properties?.lat ?? f.properties?.latitude ?? coords[1]);
              return {
                type: 'Feature' as const,
                geometry: {
                  type: 'Point' as const,
                  coordinates: [lon, lat],
                },
                properties: {
                  ...f.properties,
                  port_id: String(f.properties?.port_id ?? f.properties?.id ?? ''),
                  name: f.properties?.name || 'Unknown Port',
                  un_locode: f.properties?.un_locode || f.properties?.locode || '',
                  congestion_index: f.properties?.congestion_index != null ? Number(f.properties.congestion_index) : 1.0,
                },
              };
            });
          } else if (Array.isArray(portsResp)) {
            features = (portsResp as any[]).map(p => ({
              type: 'Feature' as const,
              geometry: {
                type: 'Point' as const,
                coordinates: [Number(p.lon ?? p.longitude), Number(p.lat ?? p.latitude)],
              },
              properties: {
                ...p,
                port_id: String(p.port_id ?? p.id ?? ''),
                name: p.name || 'Unknown Port',
                un_locode: p.un_locode || p.locode || '',
                congestion_index: p.congestion_index != null ? Number(p.congestion_index) : 1.0,
              },
            }));
          }
          const portsFC = { type: 'FeatureCollection' as const, features };
          const src = map.getSource('ports') as maplibregl.GeoJSONSource | undefined;
          if (src) {
            src.setData(portsFC as never);
          }
        } catch (err) {
          console.warn('[NexaFreight] Failed to load ports on map load:', err);
        }
      };
      loadPorts();

      // ── Fetch & Populate NexaFreight Routes (Step 5) ──
      const loadWarehouses = () => {
      getWarehouses().then(resp => {
        const src = map.getSource('warehouses') as maplibregl.GeoJSONSource | undefined;
        if (src && resp?.type === 'FeatureCollection') {
          src.setData(resp as never);
        }
      }).catch(err => {
        console.warn('[NexaFreight] Failed to load warehouses:', err);
      });
    };
    loadWarehouses();

    const loadRoutes = async () => {
      try {
        const rawRoutes = await getAllRoutes();
          const routesResp = preprocessRoutesFC(rawRoutes);
          const src = map.getSource('routes') as maplibregl.GeoJSONSource | undefined;
          if (src && routesResp?.type === 'FeatureCollection') {
            src.setData(routesResp as never);
            const trkSrc = map.getSource('trucks') as maplibregl.GeoJSONSource | undefined;
            if (trkSrc) trkSrc.setData({ type: 'FeatureCollection', features: [] } as never);

            if (Array.isArray(routesResp.features)) {
              routesFeaturesRef.current = routesResp.features;
              const legMap = new Map<string, { shipmentId: string; mode: string }>();
              const vesselMap = new Map<string, string>();
              for (const f of routesResp.features) {
                const p = f.properties;
                if (p?.leg_id && p?.shipment_id) {
                  legMap.set(String(p.leg_id), { shipmentId: String(p.shipment_id), mode: p.mode || '' });
                }
                if (p?.vessel_mmsi && p?.shipment_id) {
                  vesselMap.set(String(p.vessel_mmsi), String(p.shipment_id));
                }
              }
              legToShipmentRef.current = legMap;
              vesselToShipmentRef.current = vesselMap;
            }
          }
        } catch (err) {
          console.warn('[NexaFreight] Failed to load routes on map load:', err);
        }
      };
      loadRoutes();

      // ── Fetch & Populate Disruption Sonar Rings (Red Sea, Suez, Panama, Malacca) ──
      const loadDisruptions = async () => {
        try {
          const alertsRes = await getAlerts({ status: 'OPEN' }).catch(() => null);
          const liveAlerts = alertsRes?.alerts || [];

          const incidents: GeoJSON.Feature[] = [
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [43.3, 12.6] },
              properties: {
                id: 'choke-red-sea',
                title: 'BAB-EL-MANDEB STRAIT',
                callout_tag: 'OPS ADVISORY\nRED SEA CHOKEPOINT',
                severity: 'CRITICAL',
                type: 'CHOKEPOINT_DELAY',
                description: 'Active maritime security advisory. Container vessels diverting via Cape of Good Hope (+10-14 days).',
                shipment_id: liveAlerts.find(a => (a.disruption_type as string) === 'CHOKEPOINT_DELAY' || (a.disruption_type as string) === 'VESSEL_DELAY')?.shipment_id || (liveAlerts[0]?.shipment_id ?? ''),
              },
            },
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [32.34, 30.58] },
              properties: {
                id: 'choke-suez',
                title: 'SUEZ CANAL TRANSIT QUEUE',
                callout_tag: 'SUEZ CANAL\nTRANSIT QUEUE',
                severity: 'HIGH',
                type: 'CONGESTION',
                description: 'Southbound convoy holding pattern due to weather and draft clearances.',
                shipment_id: '',
              },
            },
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [101.3, 2.2] },
              properties: {
                id: 'choke-malacca',
                title: 'STRAIT OF MALACCA',
                callout_tag: 'MALACCA STRAIT\nHIGH VESSEL DENSITY',
                severity: 'MEDIUM',
                type: 'CONGESTION',
                description: 'High maritime vessel density approaching Port Klang and Singapore berths.',
                shipment_id: '',
              },
            },
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [-79.9, 9.1] },
              properties: {
                id: 'choke-panama',
                title: 'PANAMA CANAL DRAFT RESTRICTION',
                callout_tag: 'PANAMA CANAL\nSLOT RESTRICTIONS',
                severity: 'HIGH',
                type: 'WEATHER_DELAY',
                description: 'Freshwater draft restrictions limiting daily transit slots.',
                shipment_id: '',
              },
            },
            {
              type: 'Feature',
              geometry: { type: 'Point', coordinates: [4.4, 51.9] },
              properties: {
                id: 'choke-rotterdam',
                title: 'PORT OF ROTTERDAM CRANE ACTION',
                callout_tag: 'ROTTERDAM TERMINAL\nBERTH DELAY +48H',
                severity: 'HIGH',
                type: 'PORT_STRIKE',
                description: 'Terminal operations slow-down impacting container dwell times.',
                shipment_id: liveAlerts.find(a => (a.disruption_type as string) === 'PORT_STRIKE' || (a.disruption_type as string) === 'PORT_CONGESTION')?.shipment_id || '',
              },
            },
          ];

          const disruptionsFC = { type: 'FeatureCollection' as const, features: incidents };
          const src = map.getSource('disruptions') as maplibregl.GeoJSONSource | undefined;
          if (src) {
            src.setData(disruptionsFC as never);
          }
        } catch (err) {
          console.warn('[NexaFreight] Failed to load disruptions on map load:', err);
        }
      };
      loadDisruptions();

      if (typeof window !== 'undefined') {
        (window as any).__nexaOpenShipment = (id: string) => {
          onEntityClick?.({ type: 'shipment', id });
        };
      }

      setMapReady(true);
      // Dev-only handle. The map is otherwise unreachable from the console,
      // which makes interaction bugs guesswork rather than diagnosis.
      if (process.env.NODE_ENV === 'development') (window as any).__globeMap = map;
    });

    // Events
    let lastMove = 0;
    map.on('mousemove', e => {
      const now = Date.now();
      if (now - lastMove > 100) {
        lastMove = now;
        onMouseCoords?.({ lat: e.lngLat.lat, lng: e.lngLat.lng });
      }
    });
    map.on('contextmenu', e => { e.preventDefault(); onRightClick?.({ lat: e.lngLat.lat, lng: e.lngLat.lng }); });
    map.on('moveend', () => { const c = map.getCenter(); onViewStateChange?.({ zoom: map.getZoom(), latitude: c.lat }); });

    // ── POPUP HELPER ──
    const popup = (coords: any, html: string) => {
      showPopup(coords, html);
    };
    const pStyle = `background:var(--paper,#F6F7F4);border:1px solid var(--border-hairline,#D4D5D0);border-radius:2px;padding:11px 12px;color:var(--ink,#16181D);font-family:'IBM Plex Mono','JetBrains Mono',ui-monospace,monospace;`;
    const linkStyle = `display:inline-block;margin-top:8px;padding:5px 12px;font-size:10px;letter-spacing:0.12em;text-decoration:none;border-radius:5px;font-family:'JetBrains Mono',monospace;`;

    // ── XSS PROTECTION HELPERS ──
    const htmlEsc = (s: any): string => String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
    const idSafe = (s: any): string => String(s ?? '').replace(/[^a-zA-Z0-9_\.\-]/g, '');
    const urlSafe = (s: any): string => { const u = String(s ?? ''); return /^https?:\/\//i.test(u) ? u : '#'; };

    const formatTime = (iso: string | null) => {
      if (!iso) return '—';
      try {
        const d = new Date(iso);
        return d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZoneName: 'short' });
      } catch { return '—'; }
    };

    // ── Flights (with FlightAware + ADS-B Exchange links + ROUTE VISUALIZATION) ──
    ['fl-commercial', 'fl-private', 'fl-jets'].forEach(layer => {
      map.on('click', layer, e => {
        if (!e.features?.length) return;
        const p = e.features[0].properties as any;
        const coords = (e.features[0].geometry as any).coordinates;
        const cs = (p.callsign||'').trim();

        // Show initial popup immediately (without route data)
        const routeLoadingId = `route-info-${Date.now()}`;
        popup(coords, `<div style="${pStyle}border:1px solid rgba(255,255,255,0.08);">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
            <span style="color:#16181D;font-size:15px;font-weight:700;letter-spacing:0.08em;">${htmlEsc(cs)}</span>
            <span style="color:#5C5A54;font-size:10px;">${htmlEsc(p.icao24||'')}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;font-size:11px;">
            <div><span style="color:#5C5A54;font-size:9px;">MODEL</span><br/><span style="color:#4B515D;">${htmlEsc(p.model||'—')}</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">ALT</span><br/><span style="color:#4B515D;">${p.alt?Math.round(p.alt)+'m':'—'}</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">SPEED</span><br/><span style="color:#4B515D;">${p.speed_knots||'—'}kt</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">HDG</span><br/><span style="color:#4B515D;">${Math.round(p.heading||0)}°</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">REG</span><br/><span style="color:#4B515D;">${htmlEsc(p.registration||'—')}</span></div>
            <div><span style="color:#5C5A54;font-size:9px;">POS</span><br/><span style="color:#4B515D;">${coords[1].toFixed(2)},${coords[0].toFixed(2)}</span></div>
          </div>
          <div id="ac-${idSafe(p.icao24||'')}" style="margin-top:8px;padding-top:8px;border-top:1px solid rgba(255,255,255,0.06);">
            <span style="color:#5C5A54;font-size:9px;letter-spacing:0.1em;">IDENTIFYING AIRFRAME…</span>
          </div>
          <button onclick="window.NexaFreightWatchFlight && window.NexaFreightWatchFlight({ icao24: '${idSafe(p.icao24||'')}', callsign: '${idSafe(cs)}' })" style="width:100%;margin-top:8px;padding:6px 12px;background:rgba(0,229,255,0.10);border:1px solid rgba(0,229,255,0.35);color:#7FE9FF;font-family:'JetBrains Mono',monospace;font-size:9px;font-weight:bold;letter-spacing:0.1em;border-radius:4px;cursor:pointer;">+ WATCH THIS AIRCRAFT</button>
          <div id="${routeLoadingId}" style="margin-top:8px;padding:6px;border-top:1px solid rgba(255,255,255,0.06);text-align:center;">
            <span style="color:#5C5A54;font-size:9px;letter-spacing:0.1em;">RESOLVING ROUTE…</span>
          </div>
          <div style="margin-top:8px;display:flex;gap:4px;flex-wrap:wrap;">
            <a href="https://www.flightaware.com/live/flight/${encodeURIComponent(cs)}" target="_blank" style="${linkStyle}color:#78909C;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.03);">FLIGHTAWARE</a>
            <a href="https://globe.adsbexchange.com/?icao=${encodeURIComponent(p.icao24||'')}" target="_blank" style="${linkStyle}color:#78909C;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.03);">ADS-B</a>
            <a href="https://www.radarbox.com/data/flights/${encodeURIComponent(cs)}" target="_blank" style="${linkStyle}color:#78909C;border:1px solid rgba(255,255,255,0.1);background:rgba(255,255,255,0.03);">RADARBOX</a>
          </div>
        </div>`);

        // The transponder only reports a type code (often nothing at all), so
        // resolve the real manufacturer/model and registration out of band.
        if (p.icao24) {
          fetch(`/api/aircraft?icao24=${encodeURIComponent(p.icao24)}`)
            .then(r => (r.ok ? r.json() : null))
            .then((d) => {
              const el = document.getElementById(`ac-${p.icao24}`);
              if (!el || !d || d.error) {
                if (el) el.innerHTML = '<span style="color:#5C5A54;font-size:9px;">AIRFRAME NOT IN REGISTRY</span>';
                return;
              }
              const bits = [d.registration, d.typeCode, d.operator].filter(Boolean)
                .map((x: string) => htmlEsc(String(x))).join(' · ');
              el.innerHTML =
                `<div style="color:#16181D;font-size:11px;line-height:1.35;">${htmlEsc(d.model || 'Unidentified type')}</div>` +
                (bits ? `<div style="color:#78909C;font-size:9px;margin-top:2px;">${bits}</div>` : '');
            })
            .catch(() => {});
        }

        // Resolve origin/destination for the readout only. The line this used
        // to draw was a straight hop between two airports, which is not the
        // path flown — watched aircraft draw their real reported track instead.
        const cleanCallsign = cs.replace(/\s+/g, '');
        const routeParams = new URLSearchParams({
          callsign: cleanCallsign,
          icao24: p.icao24 || '',
          lat: String(coords[1]),
          lng: String(coords[0]),
          speed: String(p.speed_knots || 0),
        });
        fetch(`/api/flight-route?${routeParams}`)
          .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
          .then(routeData => {
            const el = document.getElementById(routeLoadingId);
            if (!el) return;
            if (routeData.found && routeData.origin && routeData.destination) {
              const depTime = formatTime(routeData.departureTime);
              const arrTime = formatTime(routeData.arrivalTime);
              const pct = Math.round((routeData.progress || 0) * 100);
              const distKm = routeData.totalDistanceKm || 0;
              el.innerHTML = `
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
                  <div><span style="color:#5C5A54;font-size:8px;">FROM</span><br/><span style="color:#16181D;font-size:13px;font-weight:700;">${htmlEsc(routeData.origin.iata || routeData.origin.icao)}</span> <span style="color:#5C5A54;font-size:9px;">${htmlEsc(routeData.origin.city)}</span></div>
                  <span style="color:#5C5A54;font-size:11px;">&rarr;</span>
                  <div style="text-align:right;"><span style="color:#5C5A54;font-size:8px;">TO</span><br/><span style="color:#16181D;font-size:13px;font-weight:700;">${htmlEsc(routeData.destination.iata || routeData.destination.icao)}</span> <span style="color:#5C5A54;font-size:9px;">${htmlEsc(routeData.destination.city)}</span></div>
                </div>
                <div style="height:2px;background:rgba(255,255,255,0.06);border-radius:1px;margin:6px 0;"><div style="width:${pct}%;height:100%;background:rgba(255,255,255,0.35);border-radius:1px;"></div></div>
                <div style="display:flex;justify-content:space-between;font-size:10px;color:#78909C;">
                  <span>DEP ${depTime}</span>
                  <span>${pct}% &middot; ${distKm.toLocaleString()}km</span>
                  <span>ARR ${arrTime}</span>
                </div>
              `;
            } else {
              el.innerHTML = `<span style="color:#5C5A54;font-size:9px;">NO SCHEDULED ROUTE</span>`;
            }
          })
          .catch(() => {
            const el = document.getElementById(routeLoadingId);
            if (el) el.innerHTML = `<span style="color:#5C5A54;font-size:9px;">ROUTE UNAVAILABLE</span>`;
          });
      });
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
    });

    // (CCTV and Earthquakes click handlers removed)
    // ── Satellites (SatNOGS powered) ──
    // Layers with their own click handlers. The satellite pick defers to
    // these, and to nothing else — the basemap is not a click target.
    const CLICKABLE_LAYERS = new Set(['ports-layer', 'airports-layer', 'warehouses-layer', 'disruptions-outer-pulse', 'disruptions-core', 'disruptions-label', 'routes-sea', 'routes-air', 'routes-road', 'routes-rail', 'routes-trucks-layer', 'cctv-dots', 'eq-circles', 'fires-heat', 'weather-dots', 'infra-dots', 'choke-dots', 'news-dots', 'balloon-dots', 'rad-dots', 'ship-dots', 'sdk-sea', 'sdk-air', 'sdk-intel', 'flight-dots', 'jet-dots', 'private-dots']);

    // ── Disruption Sonar Pulse Radar Click ──
    ['disruptions-outer-pulse', 'disruptions-core', 'disruptions-label'].forEach(layer => {
      map.on('click', layer, e => {
        if (!e.features?.length) return;
        const p = e.features[0].properties as any;
        const coords = (e.features[0].geometry as any).coordinates;
        popup(coords, `
          <div style="${pStyle}border:1px solid #DC2626;min-width:270px;background:var(--paper,#F6F7F4);">
            <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;border-bottom:1px solid var(--border-hairline,#D4D5D0);padding-bottom:5px;">
              <span style="display:inline-flex;align-items:center;gap:6px;font-size:11px;font-weight:700;color:#DC2626;letter-spacing:0.1em;">
                <span style="display:inline-block;width:7px;height:7px;border-radius:50%;background:#EF4444;box-shadow:0 0 6px #EF4444;"></span>
                ${htmlEsc(p.title || p.id)}
              </span>
              <span style="font-size:9px;font-weight:700;padding:2px 6px;border-radius:2px;background:rgba(239,68,68,0.12);color:#DC2626;border:1px solid #EF4444;">
                ${htmlEsc(p.severity || 'CRITICAL')}
              </span>
            </div>
            <div style="font-size:11px;color:var(--ink,#16181D);line-height:1.4;margin-bottom:8px;font-family:var(--font-ui,sans-serif);">
              ${htmlEsc(p.description)}
            </div>
            <div style="display:flex;justify-content:space-between;align-items:center;font-size:9px;color:var(--text-secondary,#5A5D66);margin-top:6px;padding-top:4px;border-top:1px solid var(--border-hairline,#D4D5D0);">
              <span>TYPE: ${htmlEsc(p.type)}</span>
              <span>STATUS: ACTIVE ALERT</span>
            </div>
            ${p.shipment_id ? `
              <div style="margin-top:8px;">
                <button onclick="window.__nexaOpenShipment && window.__nexaOpenShipment('${idSafe(p.shipment_id)}')" style="${linkStyle}color:#16181D;background:#2547C8;cursor:pointer;border:none;width:100%;text-align:center;padding:6px 10px;font-weight:600;">
                  INSPECT SHIPMENT (${htmlEsc(p.shipment_id)})
                </button>
              </div>
            ` : ''}
          </div>
        `);
      });
    });

    // Satellites are picked on the GPU: the pick pass runs the same vertex
    // (Satellite and fires click handlers removed)

    // ── Malware Threats (Abuse.ch) ──


    
    // ── Cloudflare Radar: internet outage ──

    // ── Cloudflare Radar: attack origin share ──

    
    

    // ── NexaFreight SDK link click ──
    const SDK_SOURCE_URLS: Record<string, string> = {
      'AIS Maritime': 'https://www.marinetraffic.com',
      'AIS Stream': 'https://aisstream.io',
      'AIS → Lattice': 'https://aisstream.io',
      'ADS-B / OpenSky': 'https://opensky-network.org',
      'ADS-B → Lattice': 'https://opensky-network.org',
      'Naval Intelligence': 'https://www.odni.gov',
    };
    ['sdk-sea', 'sdk-sea-glow', 'sdk-air', 'sdk-air-glow', 'sdk-intel', 'sdk-intel-glow'].forEach(layer => {
      map.on('click', layer, e => {
        if (!e.features?.length) return;
        const p = e.features[0].properties as any;
        const coords = e.lngLat;
        const srcUrl = p.url || SDK_SOURCE_URLS[p.source] || 'https://nexafreight.com';
        const domainLabel = p.domain === 'SEA' ? '⚓ MARITIME' : p.domain === 'AIR' ? '✈ AIR CORRIDOR' : '🛡 NAVAL INTEL';
        const domainColor = p.domain === 'SEA' ? '#4FC3F7' : p.domain === 'AIR' ? '#B3E5FC' : '#81D4FA';
        const linkStyle = 'text-decoration:none;padding:3px 8px;border-radius:4px;font-size:9px;font-weight:700;letter-spacing:0.05em;';
        popup([coords.lng, coords.lat], `<div style="${pStyle}border:1px solid ${domainColor}40;">
          <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
            <div style="width:8px;height:8px;border-radius:50%;background:${domainColor};box-shadow:0 0 8px ${domainColor};"></div>
            <span style="color:${domainColor};font-size:11px;font-weight:700;letter-spacing:0.1em;">${domainLabel}</span>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:9px;margin-bottom:8px;">
            <div><span style="color:#5C5A54;">FROM</span><br/><span style="color:#16181D;">${htmlEsc(p.fromName || 'Origin')}</span></div>
            <div><span style="color:#5C5A54;">TO</span><br/><span style="color:#16181D;">${htmlEsc(p.toName || 'Destination')}</span></div>
            <div><span style="color:#5C5A54;">DOMAIN</span><br/><span style="color:${domainColor};">${p.domain}</span></div>
            <div><span style="color:#5C5A54;">SOURCE</span><br/><a href="${urlSafe(srcUrl)}" target="_blank" style="color:${domainColor};text-decoration:underline;cursor:pointer;">${htmlEsc(p.source || 'NexaFreight')}</a></div>
          </div>
          <a href="${urlSafe(srcUrl)}" target="_blank" style="${linkStyle}color:${domainColor};border:1px solid ${domainColor}40;background:${domainColor}18;display:inline-block;margin-top:4px;">OPEN SOURCE ↗</a>
        </div>`);
      });
    });

    // ⚡ Live Cyber Attack Arcs (click on flying heads) ⚡

    // ── Generic hover for clickables ──
    ['ports-layer', 'airports-layer', 'warehouses-layer', 'routes-sea', 'routes-air', 'routes-road', 'routes-rail', 'routes-trucks-layer', 'cctv-dots', 'eq-circles', 'fires-heat', 'weather-dots', 'infra-dots', 'choke-dots', 'news-dots', 'balloon-dots', 'rad-dots', 'ship-dots', 'sdk-sea', 'sdk-sea-glow', 'sdk-sea-atmo', 'sdk-air', 'sdk-air-glow', 'sdk-air-atmo', 'sdk-intel', 'sdk-intel-glow', 'sdk-intel-atmo'].forEach(layer => {
      map.on('mouseenter', layer, () => { map.getCanvas().style.cursor = 'pointer'; });
      map.on('mouseleave', layer, () => { map.getCanvas().style.cursor = ''; });
    });

    // ── Scan Targets click ──

    // ── IP Sweep device click ──

    // ── Balloons / Sondes ──
    map.on('click', 'balloon-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      popup(coords, `<div style="${pStyle}border:1px solid ${p.color}40;">
        <div style="color:${p.color};font-size:12px;font-weight:700;letter-spacing:0.1em;margin-bottom:4px;">🎈 ${p.callsign}</div>
        <div style="font-size:9px;color:#aaa;margin-bottom:8px;">${p.type.toUpperCase()} / STATUS: ${p.status.toUpperCase()}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;">
          <div><span style="color:#5C5A54;">ALTITUDE</span><br/><span style="color:#16181D;">${p.altitude} m</span></div>
          <div><span style="color:#5C5A54;">SPEED</span><br/><span style="color:#16181D;">${Math.round(p.speed)} km/h</span></div>
          <div><span style="color:#5C5A54;">VERT RATE</span><br/><span style="color:${p.verticalRate > 0 ? '#00E676' : '#FF3D3D'};">${p.verticalRate.toFixed(1)} m/s</span></div>
          <div><span style="color:#5C5A54;">TEMP</span><br/><span style="color:#16181D;">${p.temperature}°C</span></div>
        </div>
      </div>`);
    });

    // ── Radiation ──
    map.on('click', 'rad-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const color = p.status === 'DANGER' ? '#FF1744' : p.status === 'WARNING' ? '#FF9500' : '#AB47BC';
      popup(coords, `<div style="${pStyle}border:1px solid ${color}40;">
        <div style="color:${color};font-size:12px;font-weight:700;margin-bottom:4px;">☢️ ${p.name}</div>
        <div style="font-size:9px;color:#aaa;margin-bottom:8px;">${p.city}, ${p.country}</div>
        <div style="display:grid;grid-template-columns:1fr;gap:4px;font-size:11px;">
          <div><span style="color:#5C5A54;font-size:9px;">READING</span><br/><span style="color:${color};font-weight:bold;">${p.reading} nSv/h</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">STATUS</span><br/><span style="color:${color};">${p.status}</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">NETWORK</span><br/><span style="color:#16181D;">${p.network}</span></div>
        </div>
      </div>`);
    });

    // ── Maritime Ships ──
    map.on('click', 'ship-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const color = p.type === 'military' ? '#FF1744' : p.type === 'tanker' ? '#FF9500' : '#00E5FF';
      const icon = p.type === 'military' ? '⚔️' : p.type === 'tanker' ? '🛢️' : '🚢';
      
      popup(coords, `<div style="${pStyle}border:1px solid ${color}60;box-shadow:inset 0 0 12px ${color}15;">
        <div style="display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid ${color}40;padding-bottom:6px;margin-bottom:8px;">
          <div style="color:${color};font-size:12px;font-weight:700;letter-spacing:0.1em;">${icon} [ ${(p.type||'VESSEL').toUpperCase()} ]</div>
          <div style="color:#5C5A54;font-size:9px;">FLAG: ${p.flag||'UNK'}</div>
        </div>
        <div style="color:#16181D;font-size:11px;font-weight:bold;margin-bottom:10px;">${p.name || 'UNIDENTIFIED VESSEL'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:9px;margin-bottom:8px;background:rgba(0,0,0,0.3);padding:6px;border-radius:4px;">
          <div><span style="color:#5C5A54;">SPEED</span><br/><span style="color:${color};font-family:monospace;">${Number(p.speed).toFixed(1)} kn</span></div>
          <div><span style="color:#5C5A54;">HEADING</span><br/><span style="color:${color};font-family:monospace;">${Number(p.heading).toFixed(0)}°</span></div>
          <div><span style="color:#5C5A54;">LATITUDE</span><br/><span style="color:#16181D;font-family:monospace;">${coords[1].toFixed(4)}°</span></div>
          <div><span style="color:#5C5A54;">LONGITUDE</span><br/><span style="color:#16181D;font-family:monospace;">${coords[0].toFixed(4)}°</span></div>
        </div>
        <div><span style="color:#5C5A54;font-size:9px;">DESTINATION: </span><span style="color:#16181D;font-size:9px;">${p.destination || 'UNKNOWN'}</span></div>
        <a href="https://www.marinetraffic.com/en/ais/details/ships/mmsi:${p.mmsi}" target="_blank" style="${linkStyle}flex:1;text-align:center;color:${color};border:1px solid ${color}40;background:${color}15;display:inline-block;width:100%;box-sizing:border-box;margin-top:4px;">[ OPEN SOURCE ↗ ]</a>
      </div>`);
    });

    // ── Weather Events (NASA EONET + NOAA/NWS + GDACS) ──
    map.on('click', 'weather-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const iconEmoji = p.icon === 'cyclone' ? '🌀' : p.icon === 'volcano' ? '🌋' : p.icon === 'flood' ? '🌊' : p.icon === 'drought' ? '🏜️' : p.icon === 'ice' ? '🧊' : p.icon === 'weather' ? '⚠️' : '⚡';
      popup(coords, `<div style="${pStyle}border:1px solid rgba(224,64,251,0.3);">
        <div style="color:#E040FB;font-size:14px;font-weight:700;margin-bottom:6px;">${iconEmoji} ${p.type || 'Weather Event'}</div>
        <div style="font-size:10px;color:#16181D;margin-bottom:8px;line-height:1.4;">${p.title || 'Unknown event'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:9px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;">SEVERITY</span><br/><span style="color:${p.severity === 'high' ? '#FF1744' : '#FFD700'};">${(p.severity||'low').toUpperCase()}</span></div>
          <div><span style="color:#5C5A54;">COORDS</span><br/><span style="color:#16181D;">${coords[1].toFixed(3)}°, ${coords[0].toFixed(3)}°</span></div>
        </div>
        <div style="display:flex;gap:6px;">
          ${p.source ? `<a href="${p.source}" target="_blank" style="${linkStyle}color:#E040FB;border:1px solid rgba(224,64,251,0.4);background:rgba(224,64,251,0.1);">📡 SOURCE</a>` : ''}
        </div>
      </div>`);
    });

    // ── Nuclear Infrastructure ──
    map.on('click', 'infra-dots', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const statusColor = p.status.includes('SEISMIC RISK') ? '#FF9500' : p.status === 'Active Conflict Zone' ? '#FF1744' : p.status === 'Operational' ? '#76FF03' : '#757575';
      popup(coords, `<div style="${pStyle}border:1px solid rgba(118,255,3,0.3);">
        <div style="color:#76FF03;font-size:14px;font-weight:700;margin-bottom:4px;">☢️ ${p.name || 'Nuclear Facility'}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;font-size:9px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;">STATUS</span><br/><span style="color:${statusColor};">${p.status || '—'}</span></div>
          <div><span style="color:#5C5A54;">CITY</span><br/><span style="color:#16181D;">${p.city || '—'}, ${p.country || ''}</span></div>
          <div><span style="color:#5C5A54;">REACTORS</span><br/><span style="color:#76FF03;">${p.reactors || '—'}</span></div>
          <div><span style="color:#5C5A54;">CAPACITY</span><br/><span style="color:#16181D;">${p.capacityMW ? p.capacityMW.toLocaleString() + ' MW' : '—'}</span></div>
          <div><span style="color:#5C5A54;">OWNER</span><br/><span style="color:#16181D;">${p.owner || '—'}</span></div>
          <div><span style="color:#5C5A54;">COORDS</span><br/><span style="color:#16181D;">${coords[1].toFixed(3)}°, ${coords[0].toFixed(3)}°</span></div>
        </div>
        <a href="https://www.google.com/maps/@${coords[1]},${coords[0]},14z/data=!3m1!1e3" target="_blank" style="${linkStyle}color:#76FF03;border:1px solid rgba(118,255,3,0.4);background:rgba(118,255,3,0.1);">SATELLITE VIEW</a>
      </div>`);
    });

    // ── NexaFreight Ports Inspector (Step 4) ──
    map.on('click', 'ports-layer', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = (e.features[0].geometry as any).coordinates;
      const unLocode = p.un_locode || p.locode || p.location_id || '—';
      const cIndex = p.congestion_index != null ? Number(p.congestion_index) : 1.0;
      const congestionVal = cIndex.toFixed(2);
      const congestionCol = cIndex > 1.5 ? '#B42318' : cIndex > 1.2 ? '#B54708' : cIndex < 0.9 ? '#027A48' : '#B54708';
      const statusLabel = cIndex > 1.5 ? 'CRITICAL CONGESTION' : cIndex > 1.2 ? 'ELEVATED DELAYS' : cIndex < 0.9 ? 'OPTIMAL FLOW' : 'NORMAL ACTIVITY';

      popup(coords, `<div style="${pStyle}border:1px solid #2547C840;min-width:240px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <span style="color:#2547C8;font-size:11px;font-weight:700;letter-spacing:0.08em;">PORT INSPECTOR</span>
          <span style="background:rgba(0,188,212,0.15);color:#2547C8;padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;font-family:'JetBrains Mono',monospace;">${htmlEsc(unLocode)}</span>
        </div>
        <div style="color:#16181D;font-size:15px;font-weight:700;margin-bottom:8px;line-height:1.2;">${htmlEsc(p.name)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;font-size:9px;">UN/LOCODE</span><br/><span style="color:#16181D;font-weight:bold;">${htmlEsc(unLocode)}</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">PORT ID</span><br/><span style="color:#16181D;">#${htmlEsc(p.port_id || p.id || '—')}</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">CONGESTION</span><br/><span style="color:${congestionCol};font-weight:bold;">${congestionVal}x</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">PROVENANCE</span><br/><span style="color:#4B515D;">${htmlEsc(p.provenance || 'CALIBRATED')}</span></div>
        </div>
        <div style="padding:4px 8px;border-radius:4px;background:${congestionCol}15;border:1px solid ${congestionCol}30;font-size:9px;color:${congestionCol};font-weight:bold;margin-bottom:8px;text-align:center;">
          ${statusLabel}
        </div>
        <div style="font-size:9px;color:#5C5A54;border-top:1px solid rgba(255,255,255,0.08);padding-top:6px;display:flex;justify-content:space-between;">
          <span>LAT: ${coords[1]?.toFixed(4)}°</span>
          <span>LON: ${coords[0]?.toFixed(4)}°</span>
        </div>
      </div>`);

      // Find an active shipment associated with this port if available
      let associatedShipmentId: string | undefined;
      if (routesFeaturesRef.current && routesFeaturesRef.current.length > 0) {
        for (const rf of routesFeaturesRef.current) {
          const geom = rf.geometry;
          if (geom?.type === 'LineString' && Array.isArray(geom.coordinates) && geom.coordinates.length > 0) {
            const start = geom.coordinates[0];
            const end = geom.coordinates[geom.coordinates.length - 1];
            if (
              (Math.abs(start[0] - coords[0]) < 0.8 && Math.abs(start[1] - coords[1]) < 0.8) ||
              (Math.abs(end[0] - coords[0]) < 0.8 && Math.abs(end[1] - coords[1]) < 0.8)
            ) {
              associatedShipmentId = String(rf.properties?.shipment_id);
              break;
            }
          }
        }
        if (!associatedShipmentId && routesFeaturesRef.current[0]?.properties?.shipment_id) {
          associatedShipmentId = String(routesFeaturesRef.current[0].properties.shipment_id);
        }
      }

      onEntityClick?.({
        type: 'port',
        id: p.port_id || p.id,
        shipmentId: associatedShipmentId,
        un_locode: unLocode,
        name: p.name,
        congestion_index: cIndex,
        coords: { lat: coords[1], lng: coords[0] },
        properties: p,
      });
    });

    // ── NexaFreight Shipment Routes Inspector (Step 5) ──
    ['routes-sea', 'routes-air', 'routes-road', 'routes-rail', 'routes-rail-bed', 'routes-trucks-layer'].forEach(layer => {
      map.on('click', layer, async e => {
        if (!e.features?.length) return;
        const p = e.features[0].properties as any;
        const coords = [e.lngLat.lng, e.lngLat.lat] as [number, number];
        const shipmentId = p.shipment_id || p.id;
        const legId = p.leg_id || p.id || '—';
        const mode = p.mode || (layer.includes('truck') ? 'ROAD' : layer.includes('rail') ? 'RAIL' : 'SEA');
        onEntityClick?.({
          type: 'route',
          id: legId,
          shipmentId: String(shipmentId),
          mode,
          properties: p,
        });
        await openShipmentInspector(shipmentId, coords, {
          mode,
          legId,
          sequence: p.sequence,
          status: p.status,
          routeQuality: p.route_quality,
          provenance: p.provenance,
        });
      });
    });

    // ── NexaFreight Cargo Airports Inspector ──
    map.on('click', 'airports-layer', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = [e.lngLat.lng, e.lngLat.lat];
      popup(coords, `<div style="${pStyle}border:1px solid #f9731660;min-width:260px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <span style="color:#f97316;font-size:11px;font-weight:700;letter-spacing:0.08em;">AIR CARGO GATEWAY</span>
          <span style="background:#f9731620;color:#f97316;padding:2px 8px;border-radius:4px;font-size:10px;font-weight:bold;">${htmlEsc(p.code)}</span>
        </div>
        <div style="color:#16181D;font-size:15px;font-weight:bold;margin-bottom:4px;">${htmlEsc(p.name)}</div>
        <div style="color:#4B515D;font-size:10px;margin-bottom:8px;">${htmlEsc(p.city)}, ${htmlEsc(p.country)}</div>
        <div style="font-size:10px;color:#f97316;background:rgba(249,115,22,0.1);padding:4px 8px;border-radius:4px;border:1px solid rgba(249,115,22,0.2);">
          Active International Airfreight Hub • Connected via Overland Drayage
        </div>
      </div>`);
    });

    // ── NexaFreight Warehouses & Inland Terminals Inspector ──
    map.on('click', 'warehouses-layer', e => {
      if (!e.features?.length) return;
      const p = e.features[0].properties as any;
      const coords = [e.lngLat.lng, e.lngLat.lat];
      const isICD = p.facility_type === 'INLAND_CONTAINER_DEPOT' || (p.name && (p.name.includes('ICD') || p.name.includes('Rail')));
      const isAir = p.facility_type === 'AIR_FREIGHT_STAGING' || (p.name && p.name.includes('Airport'));
      const badgeColor = isICD ? '#2547C8' : isAir ? '#D97706' : '#027A48';
      const badgeBg = isICD ? 'rgba(37,71,200,0.1)' : isAir ? 'rgba(217,119,6,0.1)' : 'rgba(2,122,72,0.1)';
      const typeLabel = isICD ? 'INTERMODAL RAIL FREIGHT TERMINAL' : isAir ? 'AIR FREIGHT DRAYAGE STATION' : 'LOGISTICS HUB & DISTRIBUTION CENTER';
      const locode = p.locode || '—';

      popup(coords, `<div style="${pStyle}border:1px solid ${badgeColor}40;min-width:260px;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:8px;">
          <span style="color:${badgeColor};font-size:10px;font-weight:700;letter-spacing:0.08em;">${typeLabel}</span>
          <span style="background:${badgeBg};color:${badgeColor};padding:2px 8px;border-radius:4px;font-size:10px;font-weight:bold;font-family:'JetBrains Mono',monospace;">${htmlEsc(locode)}</span>
        </div>
        <div style="color:#16181D;font-size:15px;font-weight:bold;margin-bottom:6px;">${htmlEsc(p.name)}</div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;font-size:11px;margin-bottom:8px;">
          <div><span style="color:#5C5A54;font-size:9px;">FACILITY TYPE</span><br/><span style="color:#16181D;font-weight:600;">${htmlEsc(p.type_description || (isICD ? 'Intermodal Rail ICD' : isAir ? 'Airport Drayage' : 'Fulfillment Cross-Dock'))}</span></div>
          <div><span style="color:#5C5A54;font-size:9px;">STATUS</span><br/><span style="color:#027A48;font-weight:600;">● OPERATIONAL</span></div>
        </div>
        <div style="font-size:10px;color:${badgeColor};background:${badgeBg};padding:5px 8px;border-radius:4px;border:1px solid ${badgeColor}25;">
          ${isICD ? 'Direct Rail Spur Connected • Dedicated Freight Corridor (DFC)' : isAir ? 'Direct Airport Airside Access • Bonded Cargo Staging' : 'Multi-Bay Commercial Truck Dock • Rapid Cross-Docking'}
        </div>
      </div>`);

      onEntityClick?.({
        type: 'warehouse',
        id: p.warehouse_id || p.id,
        name: p.name,
        locode: p.locode,
        facility_type: p.facility_type,
        coords: { lat: coords[1], lng: coords[0] },
        properties: p,
      });
    });

    // ── Maritime Chokepoints ──
    map.on('click', 'choke-dots', e => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      const coords = (e.features![0].geometry as any).coordinates;
      const riskCol = p.risk === 'CRITICAL' ? '#FF1744' : p.risk === 'HIGH' ? '#FF9500' : p.risk === 'ELEVATED' ? '#FFD700' : '#00E676';
      popup(coords, `<div style="${pStyle}border:1px solid ${riskCol}40;">
        <div style="color:#FF9500;font-weight:bold;font-size:11px;margin-bottom:4px;">${p.name}</div>
        <div style="font-size:9px;color:#aaa;">Traffic: <span style="color:#fff;">${p.traffic}</span></div>
        <div style="font-size:9px;color:#aaa;">Risk: <span style="color:${riskCol};font-weight:bold;">${p.risk}</span></div>
      </div>`);
    });

    // ── Live News (opens feed viewer) ──
    map.on('click', 'news-dots', e => {
      const p = e.features?.[0]?.properties;
      if (!p) return;
      onEntityClick?.({
        type: 'live_news',
        name: p.name,
        city: p.city,
        country: p.country,
        url: p.url,
        category: p.category,
        embed_allowed: p.embed_allowed !== false && p.embed_allowed !== 'false',
      });
    });

    return () => { map.remove(); mapRef.current = null; };
  }, []);

  // Day/Night
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const update = () => {
      const src = map.getSource('day-night') as any;
      if (!src) return;
      if (!activeLayers.day_night) { src.setData(EMPTY_FC); return; }
      src.setData({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Polygon', coordinates: [computeSolarTerminator()] }, properties: {} }] });
    };
    update();
    const iv = setInterval(update, 300000); // 5 min (was 1 min — shadow barely moves)
    return () => clearInterval(iv);
  }, [mapReady, activeLayers.day_night]);

  // Helper to set GeoJSON
  const setGeo = useCallback((source: string, features: any[]) => {
    const src = mapRef.current?.getSource(source) as any;
    if (src) src.setData({ type: 'FeatureCollection', features });
  }, []);

  const setVis = useCallback((ids: string[], visible: boolean) => {
    const map = mapRef.current;
    if (!map) return;
    ids.forEach(id => { if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none'); });
  }, []);

  // Flight data → GeoJSON (GPU rendered)
  useEffect(() => {
    if (!mapReady) return;
    const toFeatures = (arr: any[], decimate: number = 1) => {
      let filtered = arr || [];
      if (decimate > 1) {
        filtered = filtered.filter((_, i) => i % decimate === 0);
      }
      return filtered.map((f: any) => ({
        type: 'Feature' as const, geometry: { type: 'Point' as const, coordinates: [f.lng, f.lat] },
        properties: { callsign: f.callsign, heading: f.heading || 0, alt: f.alt, model: f.model, speed_knots: f.speed_knots, registration: f.registration, icao24: f.icao24 },
      }));
    };
    setGeo('flights', activeLayers.flights ? toFeatures(data.commercial_flights, 10) : []);
    setGeo('private-fl', activeLayers.private ? toFeatures(data.private_flights, 2) : []);
    setGeo('jets', activeLayers.jets ? toFeatures(data.private_jets, 2) : []);
  }, [mapReady, data.commercial_flights, data.private_flights, data.private_jets, activeLayers.flights, activeLayers.private, activeLayers.jets]);


    // Update aircraft icon colors dynamically on theme switch
    useEffect(() => {
      if (!mapReady || !mapRef.current) return;
      const map = mapRef.current;

      const updateMapIcon = (id: string, color: string, size: number) => {
        if (!map.hasImage(id)) return;
        const canvas = document.createElement('canvas');
        canvas.width = size; canvas.height = size;
        const ctx = canvas.getContext('2d')!;
        const cx = size / 2, cy = size / 2;
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.moveTo(cx, cy - size * 0.4);
        ctx.lineTo(cx - size * 0.12, cy + size * 0.1);
        ctx.lineTo(cx - size * 0.4, cy + size * 0.2);
        ctx.lineTo(cx - size * 0.4, cy + size * 0.3);
        ctx.lineTo(cx - size * 0.12, cy + size * 0.15);
        ctx.lineTo(cx, cy + size * 0.35);
        ctx.lineTo(cx + size * 0.12, cy + size * 0.15);
        ctx.lineTo(cx + size * 0.4, cy + size * 0.3);
        ctx.lineTo(cx + size * 0.4, cy + size * 0.2);
        ctx.lineTo(cx + size * 0.12, cy + size * 0.1);
        ctx.closePath();
        ctx.fill();
        map.updateImage(id, { width: size, height: size, data: new Uint8Array(ctx.getImageData(0, 0, size, size).data) });
      };

      updateMapIcon('plane-cyan', palette.flightCivil, 24);
      updateMapIcon('plane-green', palette.flightPrivate, 24);
      updateMapIcon('plane-pink', palette.flightGov, 24);
      updateMapIcon('plane-grey', palette.flightUnknown, 24);
    }, [mapReady, palette]);

  // ── DECOUPLED LAYER RENDERERS (Performance Optimized) ──


  /* ── Cloudflare Radar: outages ── */

  /* ── Cloudflare Radar: attack origins ── */
  useEffect(() => {
    if (!mapReady) return;
    const al = activeLayers as any;
    setGeo('cf-attacks', al.cf_attacks && data.cf_attack_origins ? data.cf_attack_origins.map((a: any) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [a.lng, a.lat] },
      properties: { country: a.country, country_name: a.country_name, share: a.share },
    })) : []);
  }, [mapReady, data.cf_attack_origins, (activeLayers as any).cf_attacks, setGeo]);

  // Malware Threats

  // Network Mesh Generation (Nearest Neighbor Lattice)

  // ══ LIVE CYBER ATTACKS — Threat network with real-time flow animation ══





  useEffect(() => {
    if (!mapReady) return;
    setGeo('weather', activeLayers.weather && data.weather_events ? data.weather_events.map((w: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [w.lng, w.lat] }, properties: { title: w.title, type: w.type, icon: w.icon, severity: w.severity, source: w.source, id: w.id } })) : []);
  }, [mapReady, data.weather_events, activeLayers.weather, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('infrastructure', activeLayers.infrastructure && data.infrastructure ? data.infrastructure.map((i: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [i.lng, i.lat] }, properties: { name: i.name, city: i.city, country: i.country, status: i.status, reactors: i.reactors, capacityMW: i.capacityMW, owner: i.owner } })) : []);
  }, [mapReady, data.infrastructure, activeLayers.infrastructure, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('maritime', activeLayers.maritime && data.maritime_ports ? data.maritime_ports.map((p: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [p.lng, p.lat] }, properties: { name: p.name, country: p.country, type: p.type, volume: p.volume, fleet: p.fleet, rank: p.rank } })) : []);
    setGeo('maritime-choke', activeLayers.maritime && data.maritime_chokepoints ? data.maritime_chokepoints.map((c: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [c.lng, c.lat] }, properties: { name: c.name, traffic: c.traffic, risk: c.risk } })) : []);
    setGeo('maritime-ships', []);
  }, [mapReady, data.maritime_ports, data.maritime_chokepoints, data.maritime_ships, activeLayers.maritime, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('balloons', activeLayers.balloons && data.balloons ? data.balloons.map((b: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [b.lng, b.lat] }, properties: { callsign: b.callsign, type: b.type, status: b.status, altitude: b.altitude, speed: b.speed, verticalRate: b.verticalRate, temperature: b.temperature, color: b.color } })) : []);
  }, [mapReady, data.balloons, activeLayers.balloons, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('radiation', activeLayers.radiation && data.radiation ? data.radiation.map((r: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [r.lng, r.lat] }, properties: { name: r.name, city: r.city, country: r.country, reading: r.reading, status: r.status, network: r.network } })) : []);
  }, [mapReady, data.radiation, activeLayers.radiation, setGeo]);

  // ══ NexaFreight SDK — Lattice Sensor Mesh ══
  // Uses real submarine cable data for SEA domain, curated routes for AIR/INTEL
  useEffect(() => {
    if (!mapReady) return;
    setGeo('sdk-entities', []);

    const anySDK = activeLayers.sdk_sea || activeLayers.sdk_air || activeLayers.sdk_naval;
    if (!anySDK) {
      setGeo('sdk-links', []);
      return;
    }

    const links: any[] = [];

    // ── SEA DOMAIN: Real submarine cable data (1-for-1 Match) ──
    if (activeLayers.sdk_sea && data.submarine_cables) {
      const ignoredColors = new Set(['#9BB5CC', '#A0B8CD', '#8EABC2', '#9bb5cc', '#a0b8cd', '#8eabc2']);
      for (const cable of data.submarine_cables) {
        if (!cable.geometry) continue;
        
        // Remove the light blue background arcs
        if (cable.properties?.color && ignoredColors.has(cable.properties.color)) continue;
        
        links.push({
          type: 'Feature',
          geometry: cable.geometry, // Raw topographic paths exactly from Submarine Map
          properties: {
            domain: 'SEA',
            fromName: cable.properties?.name || 'Submarine Cable',
            toName: cable.properties?.landing_points || '',
            source: 'Global Subsea Cable Network',
            url: 'https://www.submarinecablemap.com/',
            ...cable.properties,
            color: '#1976D2', // Darker blue as requested, more transparent in layer paint
          },
        });
      }
    }

    setGeo('sdk-links', links);
  }, [mapReady, activeLayers.sdk_sea, activeLayers.sdk_air, activeLayers.sdk_naval, data.submarine_cables, setGeo]);

  useEffect(() => {
    if (!mapReady) return;
    setGeo('live-news', activeLayers.live_news && data.live_feeds ? data.live_feeds.map((f: any) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [f.lng, f.lat] }, properties: { name: f.name, city: f.city, country: f.country, url: f.url, category: f.category, embed_allowed: f.embed_allowed !== false } })) : []);
  }, [mapReady, data.live_feeds, activeLayers.live_news, setGeo]);




    // Visibility
  useEffect(() => {
    if (!mapReady) return;
    setVis(['day-night-fill'], activeLayers.day_night);
    setVis(['fl-commercial'], activeLayers.flights);
    setVis(['fl-private'], activeLayers.private);
    setVis(['fl-jets'], activeLayers.jets);
    setVis(['weather-glow','weather-dots','weather-label'], activeLayers.weather);
    setVis(['infra-glow','infra-dots','infra-label'], activeLayers.infrastructure);
    setVis(['maritime-glow','maritime-dots','maritime-label'], activeLayers.maritime);
    setVis(['choke-glow','choke-dots','choke-label'], activeLayers.maritime);
    setVis(['ship-dots','ship-label'], activeLayers.maritime);
    setVis(['news-glow','news-dots','news-label'], activeLayers.live_news);

    setVis(['balloon-dots','balloon-label'], activeLayers.balloons);
    setVis(['rad-glow','rad-dots','rad-label'], activeLayers.radiation);
    setVis(['sdk-sea','sdk-sea-glow','sdk-sea-atmo'], activeLayers.sdk_sea === true);
    setVis(['sdk-air','sdk-air-glow','sdk-air-atmo'], activeLayers.sdk_air === true);
    setVis(['sdk-intel','sdk-intel-glow','sdk-intel-atmo'], activeLayers.sdk_naval === true);
    setVis(['ports-glow', 'ports-layer', 'ports-label', 'airports-glow', 'airports-layer', 'warehouses-layer'], (activeLayers as any).ports !== false);
    setVis(['routes-sea-glow', 'routes-sea', 'routes-sea-arrows', 'routes-air-glow', 'routes-air', 'routes-air-dash', 'routes-air-arrows', 'routes-road-glow', 'routes-road', 'routes-road-arrows', 'routes-rail-bed', 'routes-rail', 'routes-rail-core', 'routes-trucks-glow', 'routes-trucks-layer'], (activeLayers as any).routes !== false);
    setVis(['disruptions-outer-pulse', 'disruptions-inner-ring', 'disruptions-core', 'disruptions-label'], (activeLayers as any).disruptions !== false);
    // Sweep layers always visible when data is present (controlled by useEffect)
    setVis([], true);
  }, [mapReady, activeLayers, setVis]);

  // ── NexaFreight Ports & Routes Reactive Loader ──
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    let cancelled = false;

    const loadPorts = () => {
      getPorts().then(portsResp => {
        if (cancelled) return;
        let features: GeoJSON.Feature[] = [];
        if (portsResp?.type === 'FeatureCollection' && Array.isArray(portsResp.features)) {
          features = portsResp.features.map((f: any) => {
            const coords = f.geometry?.coordinates || [0, 0];
            // Ensure coordinates are [lon, lat] — NOT [lat, lon]
            const lon = Number(f.properties?.lon ?? f.properties?.longitude ?? coords[0]);
            const lat = Number(f.properties?.lat ?? f.properties?.latitude ?? coords[1]);
            return {
              type: 'Feature' as const,
              geometry: {
                type: 'Point' as const,
                coordinates: [lon, lat],
              },
              properties: {
                ...f.properties,
                port_id: String(f.properties?.port_id ?? f.properties?.id ?? ''),
                name: f.properties?.name || 'Unknown Port',
                un_locode: f.properties?.un_locode || f.properties?.locode || '',
                congestion_index: f.properties?.congestion_index != null ? Number(f.properties.congestion_index) : 1.0,
              },
            };
          });
        } else if (Array.isArray(portsResp)) {
          features = (portsResp as any[]).map(p => ({
            type: 'Feature' as const,
            geometry: {
              type: 'Point' as const,
              coordinates: [Number(p.lon ?? p.longitude), Number(p.lat ?? p.latitude)],
            },
            properties: {
              ...p,
              port_id: String(p.port_id ?? p.id ?? ''),
              name: p.name || 'Unknown Port',
              un_locode: p.un_locode || p.locode || '',
              congestion_index: p.congestion_index != null ? Number(p.congestion_index) : 1.0,
            },
          }));
        }

        const src = map.getSource('ports') as maplibregl.GeoJSONSource | undefined;
        if (src) {
          src.setData({ type: 'FeatureCollection', features } as never);
        }
      }).catch(err => {
        console.warn('[NexaFreight] Failed to load ports:', err);
      });
    };

    const loadWarehouses = () => {
      getWarehouses().then(resp => {
        if (cancelled) return;
        const src = map.getSource('warehouses') as maplibregl.GeoJSONSource | undefined;
        if (src && resp?.type === 'FeatureCollection') {
          src.setData(resp as never);
        }
      }).catch(err => {
        console.warn('[NexaFreight] Failed to load warehouses:', err);
      });
    };

    const loadRoutes = () => {
      getAllRoutes().then(rawRoutes => {
        if (cancelled) return;
        const routesResp = preprocessRoutesFC(rawRoutes);
        const src = map.getSource('routes') as maplibregl.GeoJSONSource | undefined;
        if (src && routesResp?.type === 'FeatureCollection') {
          src.setData(routesResp as never);
          const trkSrc = map.getSource('trucks') as maplibregl.GeoJSONSource | undefined;
          if (trkSrc) trkSrc.setData({ type: 'FeatureCollection', features: [] } as never);

          if (Array.isArray(routesResp.features)) {
            routesFeaturesRef.current = routesResp.features;
            seaRoutesRef.current = routesResp.features.filter((f: any) => f?.properties?.mode === 'SEA');
            const legMap = new Map<string, { shipmentId: string; mode: string }>();
            const vesselMap = new Map<string, string>();
            const legFeatMap = new Map<string, any>();
            const vesselFeatMap = new Map<string, any>();
            for (const f of routesResp.features) {
              const p = f.properties;
              if (p?.leg_id && p?.shipment_id) {
                legMap.set(String(p.leg_id), { shipmentId: String(p.shipment_id), mode: p.mode || '' });
                legFeatMap.set(String(p.leg_id), f);
              }
              if (p?.vessel_mmsi && p?.shipment_id) {
                vesselMap.set(String(p.vessel_mmsi), String(p.shipment_id));
                vesselFeatMap.set(String(p.vessel_mmsi), f);
              }
            }
            legToShipmentRef.current = legMap;
            vesselToShipmentRef.current = vesselMap;
            legToRouteFeatureRef.current = legFeatMap;
            vesselToRouteFeatureRef.current = vesselFeatMap;
            setRoutesLoadedVer(v => v + 1);
          }
        }
      }).catch(err => {
        console.warn('[NexaFreight] Failed to load routes:', err);
      });
    };

    const loadDisruptions = () => {
      getAlerts({ status: 'OPEN' }).then(alertsRes => {
        if (cancelled) return;
        const liveAlerts = alertsRes?.alerts || [];
        const incidents: GeoJSON.Feature[] = [
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [43.3, 12.6] },
            properties: {
              id: 'choke-red-sea',
              title: 'BAB-EL-MANDEB STRAIT',
              callout_tag: 'OPS ADVISORY\nRED SEA CHOKEPOINT',
              severity: 'CRITICAL',
              type: 'CHOKEPOINT_DELAY',
              description: 'Active maritime security advisory. Container vessels diverting via Cape of Good Hope (+10-14 days).',
              shipment_id: liveAlerts.find(a => (a.disruption_type as string) === 'CHOKEPOINT_DELAY' || (a.disruption_type as string) === 'VESSEL_DELAY')?.shipment_id || (liveAlerts[0]?.shipment_id ?? ''),
            },
          },
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [32.34, 30.58] },
            properties: {
              id: 'choke-suez',
              title: 'SUEZ CANAL TRANSIT QUEUE',
              callout_tag: 'SUEZ CANAL\nTRANSIT QUEUE',
              severity: 'HIGH',
              type: 'CONGESTION',
              description: 'Southbound convoy holding pattern due to weather and draft clearances.',
              shipment_id: '',
            },
          },
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [101.3, 2.2] },
            properties: {
              id: 'choke-malacca',
              title: 'STRAIT OF MALACCA',
              callout_tag: 'MALACCA STRAIT\nHIGH VESSEL DENSITY',
              severity: 'MEDIUM',
              type: 'CONGESTION',
              description: 'High maritime vessel density approaching Port Klang and Singapore berths.',
              shipment_id: '',
            },
          },
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [-79.9, 9.1] },
            properties: {
              id: 'choke-panama',
              title: 'PANAMA CANAL DRAFT RESTRICTION',
              callout_tag: 'PANAMA CANAL\nSLOT RESTRICTIONS',
              severity: 'HIGH',
              type: 'WEATHER_DELAY',
              description: 'Freshwater draft restrictions limiting daily transit slots.',
              shipment_id: '',
            },
          },
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [4.4, 51.9] },
            properties: {
              id: 'choke-rotterdam',
              title: 'PORT OF ROTTERDAM CRANE ACTION',
              callout_tag: 'ROTTERDAM TERMINAL\nBERTH DELAY +48H',
              severity: 'HIGH',
              type: 'PORT_STRIKE',
              description: 'Terminal operations slow-down impacting container dwell times.',
              shipment_id: liveAlerts.find(a => (a.disruption_type as string) === 'PORT_STRIKE' || (a.disruption_type as string) === 'PORT_CONGESTION')?.shipment_id || '',
            },
          },
        ];
        const src = map.getSource('disruptions') as maplibregl.GeoJSONSource | undefined;
        if (src) src.setData({ type: 'FeatureCollection', features: incidents } as never);
      }).catch(err => {
        console.warn('[NexaFreight] Failed to load disruptions in reactive loader:', err);
      });
    };

    // Initial load
    loadPorts();
    loadWarehouses();
    loadRoutes();
    loadDisruptions();

    // Re-fetch automatically if the operator authenticates or re-authenticates
    const handleAuthRefresh = () => {
      loadPorts();
      loadRoutes();
      loadDisruptions();
    };
    window.addEventListener('nexafreight:auth_success', handleAuthRefresh);

    return () => {
      cancelled = true;
      window.removeEventListener('nexafreight:auth_success', handleAuthRefresh);
    };
  }, [mapReady]);

  // ── Live Moving Telemetry Markers (Step 4 — Repoint to useSSEPositions) ──
  const { positionsList } = useSSEPositions();

  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const activeAssetIds = new Set<string>();

    for (const pos of positionsList) {
      const rawAssetId = String(pos.asset_id ?? '');
      if (!rawAssetId) continue;
      activeAssetIds.add(rawAssetId);

      const targetLng = Number(pos.lon ?? pos.longitude);
      const targetLat = Number(pos.lat ?? pos.latitude);
      if (isNaN(targetLng) || isNaN(targetLat) || (targetLng === 0 && targetLat === 0)) continue;

      const rawType = String(pos.asset_type || '').toUpperCase();
      const normType: 'VESSEL' | 'TRUCK' | 'FLIGHT' | 'TRAIN' =
        rawType === 'VESSEL' || rawType === 'SEA'
          ? 'VESSEL'
          : rawType === 'TRUCK' || rawType === 'ROAD'
          ? 'TRUCK'
          : rawType === 'TRAIN' || rawType === 'RAIL'
          ? 'TRAIN'
          : 'FLIGHT';

      const heading = pos.heading_deg != null && !isNaN(Number(pos.heading_deg)) && Number(pos.heading_deg) !== 511
        ? Number(pos.heading_deg)
        : 0;

      // Check layer visibility based on operator toggles (flights and trucks visible with routes)
      const isVisible =
        (activeLayers as any).routes !== false &&
        (normType === 'VESSEL' ? (activeLayers as any).maritime !== false : true);

      // Align marker with the route line pointing forward towards destination (Swiggy / Zomato style)
      let effectiveLng = targetLng;
      let effectiveLat = targetLat;
      let alignedHeading = heading;

      const assignedFeat = legToRouteFeatureRef.current.get(rawAssetId) || vesselToRouteFeatureRef.current.get(rawAssetId);
      const modeRoutes = (routesFeaturesRef.current || []).filter((f: any) => {
        const m = f?.properties?.mode;
        if (normType === 'VESSEL') return m === 'SEA';
        if (normType === 'TRUCK') return m === 'ROAD';
        if (normType === 'TRAIN') return m === 'RAIL';
        if (normType === 'FLIGHT') return m === 'AIR';
        return true;
      });

      const candidateRoutes = assignedFeat ? [assignedFeat] : (modeRoutes.length > 0 ? modeRoutes : routesFeaturesRef.current || []);
      const proj = projectPointToLineFeatures(candidateRoutes, targetLng, targetLat, assignedFeat);
      if (proj) {
        effectiveLng = proj.snappedCoords[0];
        effectiveLat = proj.snappedCoords[1];
        alignedHeading = proj.bearing;
      } else if (heading != null && !isNaN(Number(heading)) && Number(heading) > 0) {
        alignedHeading = Number(heading);
      }

      const existing = liveMarkersRef.current.get(rawAssetId);

      if (existing) {
        existing.latestPos = pos;
        existing.el.style.display = isVisible ? 'block' : 'none';
        if (existing.badgeEl && pos.provenance) {
          existing.badgeEl.innerHTML = getProvenanceBadgeHtml(pos.provenance, 'xs');
        }

        const [startLng, startLat] = existing.currentCoords;
        const dist = Math.hypot(effectiveLng - startLng, effectiveLat - startLat);

        // If not aligned to a specific route feature and actively moving, derive direction from movement
        if (!proj && dist > 0.0001) {
          alignedHeading = calculateBearing(startLng, startLat, effectiveLng, effectiveLat);
        }

        // Smooth rotation transition over 4 seconds taking the shortest angular path
        const targetHeading = shortestAngle(existing.currentHeading, alignedHeading);
        existing.innerEl.style.transition = 'transform 4s linear';
        existing.innerEl.style.transform = `rotate(${targetHeading}deg)`;
        existing.currentHeading = targetHeading;

        // Smooth coordinates glide over 4 seconds (interpolates between ~5s updates)
        if (dist > 0.00001) {
          if (existing.animId) cancelAnimationFrame(existing.animId);
          existing.targetCoords = [effectiveLng, effectiveLat];
          const startTime = performance.now();
          const duration = 4000;

          const glide = (now: number) => {
            const elapsed = now - startTime;
            const progress = Math.min(1, elapsed / duration);
            const curLng = startLng + (effectiveLng - startLng) * progress;
            const curLat = startLat + (effectiveLat - startLat) * progress;
            existing.currentCoords = [curLng, curLat];
            existing.marker.setLngLat([curLng, curLat]);
            if (progress < 1) {
              existing.animId = requestAnimationFrame(glide);
            }
          };
          existing.animId = requestAnimationFrame(glide);
        }

        existing.el.title = `${normType}: ${rawAssetId}${pos.speed_knots ? ` (${Number(pos.speed_knots).toFixed(1)} kts)` : ''}`;
      } else {
        // Create new DOM marker with strict absolute positioning to eliminate layout flow offsets on zoom
        const el = document.createElement('div');
        el.className = `nexa-live-marker nexa-marker-${normType.toLowerCase()}`;
        el.style.width = '32px';
        el.style.height = '32px';
        el.style.cursor = 'pointer';
        el.style.position = 'absolute';
        el.style.top = '0';
        el.style.left = '0';
        el.style.margin = '0';
        el.style.padding = '0';
        el.style.willChange = 'transform';
        el.style.pointerEvents = 'auto';
        el.style.display = isVisible ? 'block' : 'none';
        el.title = `${normType}: ${rawAssetId}${pos.speed_knots ? ` (${Number(pos.speed_knots).toFixed(1)} kts)` : ''}`;

        const innerEl = document.createElement('div');
        innerEl.className = 'nexa-marker-icon-wrapper';
        innerEl.style.width = '100%';
        innerEl.style.height = '100%';
        innerEl.style.display = 'flex';
        innerEl.style.alignItems = 'center';
        innerEl.style.justifyContent = 'center';
        innerEl.style.transform = `rotate(${alignedHeading}deg)`;
        innerEl.style.transition = 'transform 4s linear';
        innerEl.style.filter = 'drop-shadow(0 2px 5px rgba(0,0,0,0.22))';
        innerEl.innerHTML = getAssetMarkerSvg(normType, 0, pos.speed_knots);
        el.appendChild(innerEl);

        // Step 5: Attach provenance badge overlay near the icon
        const badgeEl = document.createElement('div');
        badgeEl.className = 'nexa-marker-provenance-overlay';
        badgeEl.style.position = 'absolute';
        badgeEl.style.bottom = '-6px';
        badgeEl.style.left = '50%';
        badgeEl.style.transform = 'translateX(-50%)';
        badgeEl.style.pointerEvents = 'none';
        badgeEl.style.zIndex = '5';
        badgeEl.style.whiteSpace = 'nowrap';
        badgeEl.innerHTML = getProvenanceBadgeHtml(pos.provenance, 'xs');
        el.appendChild(badgeEl);

        const marker = new maplibregl.Marker({
          element: el,
          anchor: 'center',
        })
          .setLngLat([effectiveLng, effectiveLat])
          .addTo(map);

        const record: LiveMarkerRecord = {
          marker,
          el,
          innerEl,
          badgeEl,
          currentCoords: [effectiveLng, effectiveLat],
          targetCoords: [effectiveLng, effectiveLat],
          currentHeading: alignedHeading,
          assetType: normType,
          assetId: rawAssetId,
          latestPos: pos,
        };

        // Wire marker click to open shipment inspector
        el.addEventListener('click', (e: any) => {
          e.stopPropagation();
          const currentCoord = liveMarkersRef.current.get(rawAssetId)?.currentCoords || [effectiveLng, effectiveLat];
          const latest = liveMarkersRef.current.get(rawAssetId)?.latestPos || pos;
          handleMarkerClick(latest, currentCoord, normType);
        });

        liveMarkersRef.current.set(rawAssetId, record);
      }
    }

    // Prune stale markers that are no longer in telemetry stream
    for (const [id, record] of liveMarkersRef.current.entries()) {
      if (!activeAssetIds.has(id)) {
        if (record.animId) cancelAnimationFrame(record.animId);
        record.marker.remove();
        liveMarkersRef.current.delete(id);
      }
    }
  }, [mapReady, positionsList, activeLayers, handleMarkerClick, routesLoadedVer]);

  // Clean up all markers on map unmount
  useEffect(() => {
    return () => {
      for (const record of liveMarkersRef.current.values()) {
        if (record.animId) cancelAnimationFrame(record.animId);
        record.marker.remove();
      }
      liveMarkersRef.current.clear();
    };
  }, []);

  // IP Sweep visualization

  // Scan Targets visualization

  // Fly-to
  useEffect(() => {
    if (!mapReady || !mapRef.current || !flyToLocation) return;
    mapRef.current.flyTo({ center: [flyToLocation.lng, flyToLocation.lat], zoom: flyToLocation.zoom || 8, duration: 2000 });
  }, [mapReady, flyToLocation]);

  // Dynamic projection switching (lightweight — no terrain DEM)
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    try {
      (map as any).setProjection({ type: projection });
      if (projection === 'globe') {
        map.easeTo({ pitch: 20, duration: 1200 });
        try {
          (map as any).setSky({
            'sky-color': '#04040A',
            'sky-horizon-blend': 0.5,
            'horizon-color': '#0a0a1a',
            'horizon-fog-blend': 0.3,
            'fog-color': '#04040A',
            'fog-ground-blend': 0.9,
          });
        } catch (e: any) { console.warn('[NexaFreight] Suppressed error:', e instanceof Error ? e.message : e); }
      } else {
        map.easeTo({ pitch: 0, duration: 800 });
      }
    } catch (e: any) {
      console.warn('Projection switch failed:', e);
    }
  }, [mapReady, projection]);

  // 3D Terrain & Buildings layer
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const enabled = activeLayers.terrain_3d;

    try {
      if (enabled) {
        // ── 3D BUILDINGS SOURCE (OpenFreeMap CDN — no API key, globally cached) ──
        if (!map.getSource('NexaFreight-buildings')) {
          map.addSource('NexaFreight-buildings', {
            type: 'vector',
            url: 'https://tiles.openfreemap.org/planet',
          });
        }

        // ── 3D BUILDING EXTRUSION LAYER ──
        if (!map.getLayer('NexaFreight-3d-buildings')) {
          map.addLayer({
            id: 'NexaFreight-3d-buildings',
            source: 'NexaFreight-buildings',
            'source-layer': 'building',
            type: 'fill-extrusion',
            minzoom: 14.5,
            paint: {
              'fill-extrusion-color': [
                'interpolate', ['linear'], ['get', 'render_height'],
                0, '#1a1a2e',
                20, '#16213e',
                50, '#0f3460',
                120, '#533483',
                300, '#e94560',
              ],
              'fill-extrusion-height': [
                'interpolate', ['linear'], ['zoom'],
                14.5, 0,
                15.5, ['get', 'render_height']
              ],
              'fill-extrusion-base': [
                'interpolate', ['linear'], ['zoom'],
                14.5, 0,
                15.5, ['get', 'render_min_height']
              ],
              'fill-extrusion-opacity': [
                'interpolate', ['linear'], ['zoom'],
                14.5, 0,
                15, 0.7,
              ],
            },
          });
        }

        // Pitch the camera to reveal the 3D skyline
        if (map.getPitch() < 40) {
          map.easeTo({ pitch: 50, duration: 1200 });
        }

      } else {
        // ── DISABLE 3D ──
        if (map.getLayer('NexaFreight-3d-buildings')) map.removeLayer('NexaFreight-3d-buildings');
      }
    } catch (e: any) {
      console.warn('[NexaFreight] 3D terrain toggle error:', e);
    }
  }, [mapReady, activeLayers.terrain_3d]);

  // Satellite / Dark style switching
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    if (mapStyle === prevStyleRef.current) return;
    prevStyleRef.current = mapStyle;
    const map = mapRef.current;

    try {
      if (mapStyle === 'satellite') {
        // Add satellite raster tiles
        if (!map.getSource('satellite-tiles')) {
          map.addSource('satellite-tiles', {
            type: 'raster',
            tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
            tileSize: 256,
            maxzoom: 18,
          });
          map.addLayer({ id: 'satellite-layer', type: 'raster', source: 'satellite-tiles', paint: { 'raster-opacity': 0.85 } }, 'day-night-fill');
        } else {
          map.setLayoutProperty('satellite-layer', 'visibility', 'visible');
        }
      } else {
        if (map.getLayer('satellite-layer')) {
          map.setLayoutProperty('satellite-layer', 'visibility', 'none');
        }
      }
    } catch (e: any) {
      console.warn('Style switch failed:', e);
    }
  }, [mapReady, mapStyle]);

  // ── DRAWN POLYGONS ──
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const currentPolygons = drawnPolygons || [];
    const currentIds = currentPolygons.map(p => p.id);
    
    prevDrawnPolygonsRef.current.forEach(id => {
      if (!currentIds.includes(id)) {
        if (map.getLayer(`drawn-polygon-label-${id}`)) map.removeLayer(`drawn-polygon-label-${id}`);
        if (map.getLayer(`drawn-polygon-line-${id}`)) map.removeLayer(`drawn-polygon-line-${id}`);
        if (map.getLayer(`drawn-polygon-fill-${id}`)) map.removeLayer(`drawn-polygon-fill-${id}`);
        if (map.getSource(`drawn-polygon-${id}-label`)) map.removeSource(`drawn-polygon-${id}-label`);
        if (map.getSource(`drawn-polygon-${id}`)) map.removeSource(`drawn-polygon-${id}`);
      }
    });
    prevDrawnPolygonsRef.current = currentIds;

    currentPolygons.forEach(poly => {
      const sourceId = `drawn-polygon-${poly.id}`;
      const fillLayerId = `drawn-polygon-fill-${poly.id}`;
      const lineLayerId = `drawn-polygon-line-${poly.id}`;
      const labelLayerId = `drawn-polygon-label-${poly.id}`;

      // Build a centroid point feature for the label. A Polygon nests its ring
      // one level deeper than a LineString, so the label of a path would sit at
      // 0,0 if both were read the same way.
      const geom: any = poly.geojson.geometry;
      const ring: number[][] = geom?.type === 'LineString' ? (geom.coordinates || []) : (geom?.coordinates?.[0] || []);
      const centroid = ring.length > 0 ? [
        ring.reduce((s: number, c: number[]) => s + c[0], 0) / ring.length,
        ring.reduce((s: number, c: number[]) => s + c[1], 0) / ring.length,
      ] : [0, 0];
      const labelFC = { type: 'FeatureCollection' as const, features: [{ type: 'Feature' as const, properties: { name: poly.name }, geometry: { type: 'Point' as const, coordinates: centroid } }] };

      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, { type: 'geojson', data: poly.geojson });
      } else {
        (map.getSource(sourceId) as maplibregl.GeoJSONSource).setData(poly.geojson);
      }
      if (!map.getSource(`${sourceId}-label`)) {
        map.addSource(`${sourceId}-label`, { type: 'geojson', data: labelFC as any });
      } else {
        (map.getSource(`${sourceId}-label`) as maplibregl.GeoJSONSource).setData(labelFC as any);
      }

      if (!map.getLayer(fillLayerId)) {
        map.addLayer({ id: fillLayerId, type: 'fill', source: sourceId, filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': poly.color, 'fill-opacity': 0.12 } });
      }
      if (!map.getLayer(lineLayerId)) {
        map.addLayer({ id: lineLayerId, type: 'line', source: sourceId, paint: { 'line-color': poly.color, 'line-width': 2.5, 'line-dasharray': [6, 3] } });
      }
      if (!map.getLayer(labelLayerId)) {
        map.addLayer({ id: labelLayerId, type: 'symbol', source: `${sourceId}-label`, layout: { 'text-field': ['get', 'name'], 'text-size': 11, 'text-allow-overlap': true, 'text-ignore-placement': true }, paint: { 'text-color': poly.color, 'text-halo-color': 'rgba(246,247,244,0.95)', 'text-halo-width': 2 } });
      }
    });
  }, [mapReady, drawnPolygons]);

  // ── DIRECTIONS ROUTE ──
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;

    const SRC = 'directions-route';
    const SRC_ALT = 'directions-alternates';
    const SRC_ACTIVE = 'directions-active-step';
    const SRC_ENDS = 'directions-endpoints';
    const IDS = [
      'directions-alt-line', 'directions-line-casing', 'directions-line',
      'directions-active-line', 'directions-endpoint-halo', 'directions-endpoint',
    ];

    const teardown = () => {
      IDS.forEach(id => { if (map.getLayer(id)) map.removeLayer(id); });
      [SRC, SRC_ALT, SRC_ACTIVE, SRC_ENDS].forEach(id => { if (map.getSource(id)) map.removeSource(id); });
    };

    if (!route?.geometry?.coordinates?.length) { teardown(); return; }

    const fc = (features: GeoJSON.Feature[]) => ({ type: 'FeatureCollection' as const, features });
    const line = (coords: [number, number][]): GeoJSON.Feature => ({
      type: 'Feature', properties: {},
      geometry: { type: 'LineString', coordinates: coords },
    });
    const setData = (id: string, data: unknown) => {
      if (!map.getSource(id)) map.addSource(id, { type: 'geojson', data: data as never });
      else (map.getSource(id) as maplibregl.GeoJSONSource).setData(data as never);
    };

    setData(SRC, fc([line(route.geometry.coordinates)]));
    setData(SRC_ALT, fc((route.alternates || []).map(a => line(a.coordinates))));
    setData(SRC_ACTIVE, fc(route.activeSegment?.length ? [line(route.activeSegment)] : []));
    setData(SRC_ENDS, fc([
      { type: 'Feature', properties: { kind: 'origin' }, geometry: { type: 'Point', coordinates: [route.from.lng, route.from.lat] } },
      { type: 'Feature', properties: { kind: 'destination' }, geometry: { type: 'Point', coordinates: [route.to.lng, route.to.lat] } },
    ]));

    // Alternatives sit underneath, muted, so the chosen line stays unambiguous.
    if (!map.getLayer('directions-alt-line')) {
      map.addLayer({
        id: 'directions-alt-line', type: 'line', source: SRC_ALT,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#5C6470',
          'line-width': ['interpolate', ['linear'], ['zoom'], 5, 2.5, 14, 5],
          'line-opacity': 0.55,
        },
      });
    }
    if (!map.getLayer('directions-line-casing')) {
      map.addLayer({
        id: 'directions-line-casing', type: 'line', source: SRC,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: { 'line-color': '#001014', 'line-width': ['interpolate', ['linear'], ['zoom'], 5, 5, 14, 11], 'line-opacity': 0.9 },
      });
    }
    if (!map.getLayer('directions-line')) {
      map.addLayer({
        id: 'directions-line', type: 'line', source: SRC,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#00E5FF',
          'line-width': ['interpolate', ['linear'], ['zoom'], 5, 2.5, 14, 6],
          'line-opacity': 0.95,
        },
      });
    }
    if (!map.getLayer('directions-active-line')) {
      map.addLayer({
        id: 'directions-active-line', type: 'line', source: SRC_ACTIVE,
        layout: { 'line-cap': 'round', 'line-join': 'round' },
        paint: {
          'line-color': '#D4AF37',
          'line-width': ['interpolate', ['linear'], ['zoom'], 5, 4, 14, 9],
          'line-opacity': 0.95,
        },
      });
    }
    if (!map.getLayer('directions-endpoint-halo')) {
      map.addLayer({
        id: 'directions-endpoint-halo', type: 'circle', source: SRC_ENDS,
        paint: {
          'circle-radius': 9,
          'circle-color': ['match', ['get', 'kind'], 'origin', '#00FF88', '#FF3B30'],
          'circle-opacity': 0.18,
        },
      });
    }
    if (!map.getLayer('directions-endpoint')) {
      map.addLayer({
        id: 'directions-endpoint', type: 'circle', source: SRC_ENDS,
        paint: {
          'circle-radius': 5,
          'circle-color': ['match', ['get', 'kind'], 'origin', '#00FF88', '#FF3B30'],
          'circle-stroke-width': 1.5,
          'circle-stroke-color': '#001014',
        },
      });
    }
  }, [mapReady, route]);

  // ── ROUTE FRAMING ──
  // Kept apart from drawing so picking a step or an alternative redraws without
  // yanking the camera back out to the whole route.
  const routeFrameKey = route
    ? `${route.from.lat},${route.from.lng},${route.to.lat},${route.to.lng},${route.geometry.coordinates.length}`
    : null;
  useEffect(() => {
    if (!mapReady || !mapRef.current || !route?.geometry?.coordinates?.length) return;
    const coords = route.geometry.coordinates;
    let [west, south, east, north] = [coords[0][0], coords[0][1], coords[0][0], coords[0][1]];
    for (const [lng, lat] of coords) {
      if (lng < west) west = lng;
      if (lng > east) east = lng;
      if (lat < south) south = lat;
      if (lat > north) north = lat;
    }
    mapRef.current.fitBounds([[west, south], [east, north]], { padding: 90, duration: 900, maxZoom: 15 });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapReady, routeFrameKey]);

  // ── LIVE USER LOCATION ──
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;

    const SRC = 'user-location';
    const SRC_ACC = 'user-location-accuracy';
    const IDS = ['user-accuracy-fill', 'user-accuracy-line', 'user-dot-pulse', 'user-dot', 'user-dot-core'];

    if (!userLocation) {
      IDS.forEach(id => { if (map.getLayer(id)) map.removeLayer(id); });
      [SRC, SRC_ACC].forEach(id => { if (map.getSource(id)) map.removeSource(id); });
      return;
    }

    const { lat, lng, accuracy } = userLocation;

    // Accuracy is a real-world radius, so it must be a polygon in degrees
    // rather than a fixed pixel circle — it has to shrink as you zoom out.
    const ring: [number, number][] = [];
    const r = Math.min(Math.max(accuracy ?? 0, 0), 5000);
    if (r > 0) {
      const dLat = r / 111320;
      const dLng = r / (111320 * Math.cos((lat * Math.PI) / 180) || 1);
      for (let i = 0; i <= 64; i++) {
        const t = (i / 64) * 2 * Math.PI;
        ring.push([lng + dLng * Math.cos(t), lat + dLat * Math.sin(t)]);
      }
    }

    const point = {
      type: 'FeatureCollection',
      features: [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [lng, lat] } }],
    };
    const accFc = {
      type: 'FeatureCollection',
      features: ring.length
        ? [{ type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [ring] } }]
        : [],
    };

    if (!map.getSource(SRC)) map.addSource(SRC, { type: 'geojson', data: point as never });
    else (map.getSource(SRC) as maplibregl.GeoJSONSource).setData(point as never);
    if (!map.getSource(SRC_ACC)) map.addSource(SRC_ACC, { type: 'geojson', data: accFc as never });
    else (map.getSource(SRC_ACC) as maplibregl.GeoJSONSource).setData(accFc as never);

    if (!map.getLayer('user-accuracy-fill')) {
      map.addLayer({ id: 'user-accuracy-fill', type: 'fill', source: SRC_ACC, paint: { 'fill-color': '#4285F4', 'fill-opacity': 0.12 } });
    }
    if (!map.getLayer('user-accuracy-line')) {
      map.addLayer({ id: 'user-accuracy-line', type: 'line', source: SRC_ACC, paint: { 'line-color': '#4285F4', 'line-width': 1, 'line-opacity': 0.35 } });
    }
    if (!map.getLayer('user-dot-pulse')) {
      map.addLayer({ id: 'user-dot-pulse', type: 'circle', source: SRC, paint: { 'circle-radius': 8, 'circle-color': '#4285F4', 'circle-opacity': 0.35 } });
    }
    if (!map.getLayer('user-dot')) {
      map.addLayer({ id: 'user-dot', type: 'circle', source: SRC, paint: { 'circle-radius': 7, 'circle-color': '#FFFFFF' } });
    }
    if (!map.getLayer('user-dot-core')) {
      map.addLayer({ id: 'user-dot-core', type: 'circle', source: SRC, paint: { 'circle-radius': 5, 'circle-color': '#4285F4' } });
    }
  }, [mapReady, userLocation]);

  // Pulse the halo. rAF-driven, so it stops when the tab is backgrounded.
  useEffect(() => {
    if (!mapReady || !mapRef.current || !userLocation) return;
    const map = mapRef.current;
    let raf = 0;
    const started = performance.now();
    const tick = (now: number) => {
      if (map.getLayer('user-dot-pulse')) {
        const t = ((now - started) % 2000) / 2000;
        map.setPaintProperty('user-dot-pulse', 'circle-radius', 8 + t * 22);
        map.setPaintProperty('user-dot-pulse', 'circle-opacity', 0.35 * (1 - t));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [mapReady, userLocation]);

  // ── FOLLOW MODE ──
  useEffect(() => {
    if (!mapReady || !mapRef.current || !followUser) return;
    const map = mapRef.current;
    // originalEvent is only set when a real input device drove the change, so
    // the easeTo below cannot trip this and cancel its own follow.
    const onGesture = (e: any) => { if (e?.originalEvent) onFollowInterrupt?.(); };
    map.on('dragstart', onGesture);
    map.on('zoomstart', onGesture);
    map.on('rotatestart', onGesture);
    map.on('pitchstart', onGesture);
    return () => {
      map.off('dragstart', onGesture);
      map.off('zoomstart', onGesture);
      map.off('rotatestart', onGesture);
      map.off('pitchstart', onGesture);
    };
  }, [mapReady, followUser, onFollowInterrupt]);

  // Recentering runs on every position fix, so without the handover above the
  // map fights the operator: zoom out to look ahead and the next GPS tick drags
  // the camera back to 16.5. Follow itself is unchanged and resumes on recenter.
  useEffect(() => {
    if (!mapReady || !mapRef.current || !followUser || !userLocation) return;
    // While navigating, sit close in and rotate the map so travel direction is
    // "up" — reading a turn off a north-locked map at speed does not work.
    mapRef.current.easeTo({
      center: [userLocation.lng, userLocation.lat],
      ...(navigating
        ? {
            zoom: Math.max(mapRef.current.getZoom(), 16.5),
            pitch: 50,
            ...(typeof userLocation.heading === 'number' && !Number.isNaN(userLocation.heading)
              ? { bearing: userLocation.heading }
              : {}),
          }
        : {}),
      duration: 700,
    });
  }, [mapReady, followUser, userLocation, navigating]);

  // Restore a plain north-up view when guidance ends.
  useEffect(() => {
    if (!mapReady || !mapRef.current || navigating) return;
    mapRef.current.easeTo({ pitch: 0, bearing: 0, duration: 600 });
  }, [mapReady, navigating]);

  // ── AIRPORTS FOR WATCHED AIRCRAFT ──
  // The endpoints that survived corroboration against the aircraft's reported
  // track — where the leg began and where it is booked to end.
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const SRC = 'watched-airports';
    const IDS = ['watched-airport-glow', 'watched-airport-dot', 'watched-airport-label'];

    // The same airport can serve several watched aircraft — draw it once.
    const seen = new Set<string>();
    const features = Object.values(aircraftAirports).flat()
      .filter((a) => {
        if (!a || seen.has(a.icao)) return false;
        seen.add(a.icao);
        return true;
      })
      .map((a) => ({
        type: 'Feature' as const,
        properties: { label: a.iata || a.icao, city: a.city || '' },
        geometry: { type: 'Point' as const, coordinates: [a.lng, a.lat] },
      }));

    if (features.length === 0) {
      IDS.forEach((id) => { if (map.getLayer(id)) map.removeLayer(id); });
      if (map.getSource(SRC)) map.removeSource(SRC);
      return;
    }

    const fc = { type: 'FeatureCollection' as const, features };
    if (!map.getSource(SRC)) map.addSource(SRC, { type: 'geojson', data: fc as never });
    else (map.getSource(SRC) as maplibregl.GeoJSONSource).setData(fc as never);

    if (!map.getLayer('watched-airport-glow')) {
      map.addLayer({
        id: 'watched-airport-glow', type: 'circle', source: SRC,
        paint: { 'circle-radius': 13, 'circle-color': '#FFB300', 'circle-opacity': 0.16, 'circle-blur': 0.8 },
      });
    }
    if (!map.getLayer('watched-airport-dot')) {
      map.addLayer({
        id: 'watched-airport-dot', type: 'circle', source: SRC,
        paint: {
          'circle-radius': 5,
          'circle-color': '#FFFFFF',
          'circle-stroke-width': 2,
          'circle-stroke-color': '#FFB300',
        },
      });
    }
    if (!map.getLayer('watched-airport-label')) {
      map.addLayer({
        id: 'watched-airport-label', type: 'symbol', source: SRC,
        layout: {
          'text-field': ['get', 'label'],
          'text-size': 11,
          'text-font': ['Open Sans Bold'],
          'text-offset': [0, 1.6],
          'text-allow-overlap': true,
        },
        paint: { 'text-color': '#FFB300', 'text-halo-color': '#0C0E1A', 'text-halo-width': 1.5 },
      });
    }
  }, [mapReady, aircraftAirports]);

  // ── ARCGIS LAYERS ──
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;
    const currentLayers = arcgisLayers || [];
    const currentIds = currentLayers.map(l => l.id);

    prevArcgisLayersRef.current.forEach(id => {
      if (!currentIds.includes(id)) {
        const sourceId = `arcgis-${id}`;
        if (map.getLayer(`${sourceId}-fill`)) map.removeLayer(`${sourceId}-fill`);
        if (map.getLayer(`${sourceId}-line`)) map.removeLayer(`${sourceId}-line`);
        if (map.getLayer(`${sourceId}-circle`)) map.removeLayer(`${sourceId}-circle`);
        if (map.getSource(sourceId)) map.removeSource(sourceId);
      }
    });
    prevArcgisLayersRef.current = currentIds;

    currentLayers.forEach(layer => {
      const sourceId = `arcgis-${layer.id}`;
      const c = layer.color || '#D4AF37';
      const o = layer.opacity ?? 0.8;
      if (!map.getSource(sourceId)) {
        map.addSource(sourceId, { type: 'geojson', data: layer.geojson });
        // A fill layer with no geometry filter is applied to LineStrings too,
        // and maplibre fills an open path by closing it — which is what draws
        // the triangular wedges across a pipeline or railway dataset. Fill is
        // only ever meaningful for polygons.
        map.addLayer({ id: `${sourceId}-fill`, type: 'fill', source: sourceId, filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': c, 'fill-opacity': o * 0.15, 'fill-outline-color': c } });
        map.addLayer({ id: `${sourceId}-line`, type: 'line', source: sourceId, filter: ['match', ['geometry-type'], ['LineString', 'Polygon'], true, false], paint: { 'line-color': c, 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 0.6, 10, 1.4, 14, 2, 18, 3], 'line-opacity': o } });
        // A fixed radius does not survive a dense dataset: ~1.2k points at
        // city zoom merge into one blob. Scaling with zoom keeps them as
        // discrete stations when you are far out, and readable up close.
        map.addLayer({ id: `${sourceId}-circle`, type: 'circle', source: sourceId, filter: ['==', ['geometry-type'], 'Point'], paint: { 'circle-color': c, 'circle-radius': ['interpolate', ['linear'], ['zoom'], 4, 1.5, 8, 2.5, 11, 4, 14, 6, 18, 9], 'circle-stroke-width': ['interpolate', ['linear'], ['zoom'], 8, 0.4, 14, 1.2], 'circle-stroke-color': '#000', 'circle-opacity': ['interpolate', ['linear'], ['zoom'], 6, 0.55, 12, 0.85] } });
      } else {
        (map.getSource(sourceId) as maplibregl.GeoJSONSource).setData(layer.geojson);
        // Update paint properties for color/opacity changes
        if (map.getLayer(`${sourceId}-fill`)) {
          map.setPaintProperty(`${sourceId}-fill`, 'fill-color', c);
          map.setPaintProperty(`${sourceId}-fill`, 'fill-opacity', o * 0.15);
          map.setPaintProperty(`${sourceId}-fill`, 'fill-outline-color', c);
        }
        if (map.getLayer(`${sourceId}-line`)) {
          map.setPaintProperty(`${sourceId}-line`, 'line-color', c);
          map.setPaintProperty(`${sourceId}-line`, 'line-opacity', o);
        }
        if (map.getLayer(`${sourceId}-circle`)) {
          map.setPaintProperty(`${sourceId}-circle`, 'circle-color', c);
          map.setPaintProperty(`${sourceId}-circle`, 'circle-opacity', o);
        }
      }
    });
  }, [mapReady, arcgisLayers]);

  // ── MAP CENTER REPORTING ──
  useEffect(() => {
    if (!mapReady || !mapRef.current) return;
    const map = mapRef.current;

    const reportCenter = () => {
      const c = map.getCenter();
      const b = map.getBounds();
      onMapCenter?.({
        lat: c.lat,
        lng: c.lng,
        bounds: b ? { west: b.getWest(), south: b.getSouth(), east: b.getEast(), north: b.getNorth() } : undefined,
      });
    };

    // Fire immediately so panels get initial coordinates
    reportCenter();

    map.on('moveend', reportCenter);
    return () => { map.off('moveend', reportCenter); };
  }, [mapReady, onMapCenter]);



  return (
    <div className="globe-frame">
      <div ref={containerRef} className="absolute inset-0 w-full h-full" />
    </div>
  );
}

export default memo(GlobeMap);
