'use client';

import { useEffect, useState, useRef, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import dynamic from 'next/dynamic';
import {
  Layers,
  Search,
  Globe,
  AlertTriangle,
} from 'lucide-react';
import SearchBar from '@/components/SearchBar';
import ScaleBar from '@/components/ScaleBar';
import ErrorBoundary from '@/components/ErrorBoundary';
import KeyboardShortcuts from '@/components/KeyboardShortcuts';
import KpiBand from '@/components/KpiBand';
import OperatorInsightsStrip from '@/components/OperatorInsightsStrip';
import FeedHealthIndicator from '@/components/FeedHealthIndicator';
import ShipmentInspectorPanel from '@/components/ShipmentInspectorPanel';
import AlertCenter from '@/components/AlertCenter';
import RerouteOptions from '@/components/RerouteOptions';
import { ProvenanceChip } from '@/components/ProvenanceBadge';
import { getAlerts } from '@/lib/nexafreight';

const GlobeMap = dynamic(() => import('@/components/GlobeMap'), { ssr: false });
const LayerPanel = dynamic(() => import('@/components/LayerPanel'));

const ZuluClock = () => {
  const [time, setTime] = useState('');
  useEffect(() => {
    const iv = setInterval(() => {
      const now = new Date();
      setTime(
        `ZULU ${String(now.getUTCHours()).padStart(2, '0')}:${String(now.getUTCMinutes()).padStart(2, '0')}:${String(now.getUTCSeconds()).padStart(2, '0')}Z`,
      );
    }, 1000);
    return () => clearInterval(iv);
  }, []);
  return (
    <span className="font-bold tabular-nums" style={{ color: 'var(--text-secondary)' }}>
      {time || 'ZULU --:--:--Z'}
    </span>
  );
};

const UptimeClock = () => {
  const [uptime, setUptime] = useState('00:00:00');
  const startTime = useRef(0);
  if (startTime.current === 0) startTime.current = Date.now();
  useEffect(() => {
    const iv = setInterval(() => {
      const e = Math.floor((Date.now() - startTime.current) / 1000);
      setUptime(
        `${String(Math.floor(e / 3600)).padStart(2, '0')}:${String(Math.floor((e % 3600) / 60)).padStart(2, '0')}:${String(e % 60).padStart(2, '0')}`,
      );
    }, 1000);
    return () => clearInterval(iv);
  }, []);
  return (
    <span className="hidden lg:inline">
      UPTIME: <span className="font-bold tabular-nums" style={{ color: 'var(--ink)' }}>{uptime}</span>
    </span>
  );
};

const ActiveEntityCount = ({ data }: { data: Record<string, unknown[]> }) => {
  const count = !data
    ? 0
    : Object.values(data).reduce<number>(
        (sum, v) => sum + (Array.isArray(v) ? v.length : 0),
        0,
      );
  return (
    <span className="font-bold tabular-nums" style={{ color: 'var(--moss-positive)' }}>
      {count.toLocaleString()}
    </span>
  );
};

function OverviewCockpit() {
  const router = useRouter();
  const { isAuthenticated, isHydrated, user } = useAuthStore();

  // Auth gate
  useEffect(() => {
    if (isHydrated && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isHydrated, isAuthenticated, router]);

  // Map state
  const dataRef = useRef<Record<string, unknown[]>>({});
  const data = dataRef.current;

  const [mapView, setMapView] = useState({ zoom: 2.5, latitude: 20 });
  const [flyToLocation, setFlyToLocation] = useState<{
    lat: number;
    lng: number;
    zoom?: number;
    ts: number;
  } | null>(null);
  const [mapProjection, setMapProjection] = useState<'globe' | 'mercator'>('mercator');
  const [mapStyle] = useState<'dark' | 'satellite' | 'paper'>('paper');
  const [globeTheme] = useState<'core' | 'ghost'>('core');
  const [showSplash, setShowSplash] = useState(true);
  const mouseCoordsRef = useRef<{ lat: number; lng: number } | null>(null);
  const coordsDisplayRef = useRef<HTMLDivElement>(null);

  // Scrimmed Drawers & Panels
  const [showLayers, setShowLayers] = useState(false);
  const [showDesktopSearch, setShowDesktopSearch] = useState(false);
  const [showAlertsDrawer, setShowAlertsDrawer] = useState(false);
  const [activeAlertCount, setActiveAlertCount] = useState(0);

  /** Alert currently being re-routed in options drawer */
  const [activeOptionsAlertId, setActiveOptionsAlertId] = useState<string | null>(null);
  /** Shipment id open in the right-hand peek drawer */
  const [selectedShipmentId, setSelectedShipmentId] = useState<string | null>(null);
  /** Bumped when a decision executes so downstream components refetch */
  const [opsVersion, setOpsVersion] = useState(0);

  // Layer buckets
  const [activeLayers, setActiveLayers] = useState<Record<string, boolean>>({
    ports: true,
    active_ports_only: true,
    routes: true,
    maritime: true,
    disruptions: true,
    flights: false,
    weather: false,
    sdk_sea: false,
    cables: false,
  });

  // Query alert count for Disruption drawer badge
  useEffect(() => {
    let cancelled = false;
    const fetchAlertCount = async () => {
      try {
        const res = await getAlerts({ status: 'OPEN' });
        if (!cancelled && res?.alerts) {
          setActiveAlertCount(res.alerts.length);
        }
      } catch {}
    };
    fetchAlertCount();
    const interval = setInterval(fetchAlertCount, 30000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [opsVersion]);

  // Splash veil timeout
  useEffect(() => {
    const splashTimer = setTimeout(() => setShowSplash(false), 900);
    return () => clearTimeout(splashTimer);
  }, []);

  const openInspector = useCallback((shipmentId: string | null) => {
    if (!shipmentId) return;
    setSelectedShipmentId(shipmentId);
  }, []);

  const openOptions = useCallback((alertId: string) => {
    setActiveOptionsAlertId(alertId);
    setShowAlertsDrawer(true);
  }, []);

  const handleDecisionExecuted = useCallback(() => {
    setOpsVersion((v) => v + 1);
    setActiveOptionsAlertId(null);
  }, []);

  const handleEntityClick = useCallback(
    (entity: { type?: string; id?: string; shipmentId?: string } | null) => {
      if (!entity) return;
      if (entity.type === 'shipment' && (entity.shipmentId ?? entity.id)) {
        openInspector(entity.shipmentId ?? entity.id ?? null);
      }
    },
    [openInspector],
  );

  const handleMouseCoords = useCallback((coords: { lat: number; lng: number }) => {
    mouseCoordsRef.current = coords;
    if (coordsDisplayRef.current) {
      coordsDisplayRef.current.innerText = `${coords.lat.toFixed(4)}, ${coords.lng.toFixed(4)}`;
    }
  }, []);

  // Keyboard navigation & tool shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (['INPUT', 'TEXTAREA'].includes((e.target as Element)?.tagName)) return;
      if (e.key === 'l') setShowLayers((p) => !p);
      if (e.key === 's') setShowDesktopSearch((p) => !p);
      if (e.key === 'r') setFlyToLocation({ lat: 20, lng: 0, ts: Date.now() });
      if (e.key === 'Escape') {
        setSelectedShipmentId(null);
        setActiveOptionsAlertId(null);
        setShowAlertsDrawer(false);
        setShowLayers(false);
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  if (!isHydrated || !isAuthenticated) return null;

  return (
    <div
      className="fixed inset-0 overflow-hidden"
      style={{ backgroundColor: 'var(--paper)', color: 'var(--ink)' }}
    >
      {/* Main Workspace (Offset pl-[58px] for the global TacticalNavRail) */}
      <div className="pl-[58px] h-full flex flex-col relative overflow-hidden">
        {/* Cockpit Status Strip */}
        <header
          className="h-12 border-b flex items-center justify-between px-4 z-[1040] select-none flex-shrink-0"
          style={{
            backgroundColor: 'var(--paper)',
            borderColor: 'var(--border-hairline)',
          }}
        >
          {/* Left: Overview Title & System Health */}
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/nexafreight-mark.svg" alt="NexaFreight" className="w-5 h-5 rounded-[2px]" />
              <span className="font-ui text-[13px] font-bold tracking-wider text-[var(--ink)]">
                CONTROL TOWER
              </span>
              <span className="text-[var(--border-hairline)]">/</span>
              <span className="hidden sm:inline font-mono text-[10px] text-[var(--text-secondary)]">
                LIVE AIS FLEET & MARITIME TELEMETRY
              </span>
            </div>

            <span className="hidden md:inline-flex items-center gap-1.5 font-mono text-[10px] px-1.5 py-0.5 rounded-[2px] bg-[var(--bg-subtle)] border border-[var(--border-hairline)] text-[var(--moss-positive)]">
              <span className="w-1.5 h-1.5 rounded-full bg-[var(--moss-positive)] animate-pulse" />
              SAT-LINK: NOMINAL
            </span>
          </div>

          {/* Center: Real telemetry counters */}
          <div className="hidden xl:flex items-center gap-5 text-[10px] font-mono tracking-wider text-[var(--text-secondary)]">
            <ActiveEntityCount data={data} />
            <ZuluClock />
            <UptimeClock />
            <ProvenanceChip provenance="REAL" size="sm" />
          </div>

          {/* Right: Tools & Drawers */}
          <div className="flex items-center gap-2">
            <FeedHealthIndicator className="hidden md:flex" />

            {/* Disruptions Drawer Toggle */}
            <button
              onClick={() => setShowAlertsDrawer((p) => !p)}
              aria-pressed={showAlertsDrawer}
              className={`flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-mono rounded-[2px] border transition-colors ${
                showAlertsDrawer || activeAlertCount > 0
                  ? 'border-[var(--oxide-risk)] text-[var(--oxide-risk)] hover:bg-[var(--oxide-risk)]/10'
                  : 'border-[var(--border-hairline)] text-[var(--text-secondary)] hover:text-[var(--ink)]'
              }`}
              title="Toggle Alerts & Disruptions Drawer"
            >
              <AlertTriangle className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">ALERTS</span>
              {activeAlertCount > 0 && (
                <span className="px-1 min-w-[14px] h-[14px] flex items-center justify-center rounded-[2px] font-mono text-[9px] font-bold bg-[var(--oxide-risk)] text-white">
                  {activeAlertCount}
                </span>
              )}
            </button>

            {/* Map Layers Popover Toggle */}
            <button
              onClick={() => setShowLayers((p) => !p)}
              aria-pressed={showLayers}
              className={`flex items-center gap-1 px-2.5 py-1 text-[11px] font-mono rounded-[2px] border transition-colors ${
                showLayers
                  ? 'bg-[var(--cobalt)] text-white border-[var(--cobalt)]'
                  : 'border-[var(--border-hairline)] text-[var(--text-secondary)] hover:text-[var(--ink)]'
              }`}
              title="Toggle Map Layers (L)"
            >
              <Layers className="w-3.5 h-3.5" />
              <span className="hidden sm:inline">LAYERS</span>
            </button>

            {/* Globe / Mercator Projection Toggle */}
            <button
              onClick={() => setMapProjection((p) => (p === 'globe' ? 'mercator' : 'globe'))}
              className="p-1.5 text-[var(--text-secondary)] hover:text-[var(--ink)] border border-[var(--border-hairline)] rounded-[2px] transition-colors"
              title="Toggle Projection"
            >
              <Globe className="w-3.5 h-3.5" />
            </button>

            {/* Search Dialog Toggle */}
            <button
              onClick={() => setShowDesktopSearch((p) => !p)}
              className="p-1.5 text-[var(--text-secondary)] hover:text-[var(--ink)] border border-[var(--border-hairline)] rounded-[2px] transition-colors"
              title="Global Search (S)"
            >
              <Search className="w-3.5 h-3.5" />
            </button>
          </div>
        </header>

        {/* Workspace Canvas (Globe-Centric: KpiBand + Map Canvas, No Permanent Right Panels) */}
        <div className="flex-1 relative overflow-hidden flex flex-col">
          {/* Headline KPI Band */}
          <KpiBand window="month" />

          {/* GlobeMap Canvas */}
          <div className="flex-1 relative">
            <GlobeMap
              data={data}
              activeLayers={activeLayers}
              onEntityClick={handleEntityClick}
              onMouseCoords={handleMouseCoords}
              onViewStateChange={(vs) => setMapView({ zoom: vs.zoom, latitude: vs.latitude })}
              flyToLocation={flyToLocation}
              projection={mapProjection}
              mapStyle={mapStyle}
              demoMode={false}
              theme={globeTheme}
            />

            {/* Bottom-left: Coordinate Readout & Scale */}
            <div
              className="absolute bottom-6 left-4 z-[1030] flex flex-col gap-1 text-[10px] font-mono select-none"
              style={{ color: 'var(--text-secondary)' }}
            >
              <div
                ref={coordsDisplayRef}
                className="px-1.5 py-0.5 rounded-[2px] border font-mono"
                style={{
                  backgroundColor: 'rgba(246, 247, 244, 0.95)',
                  borderColor: 'var(--border-hairline)',
                  color: 'var(--ink)',
                }}
              >
                —, —
              </div>
              <ScaleBar zoom={mapView.zoom} latitude={mapView.latitude} />
            </div>

            {/* Bottom-right: OPERATOR PULSE — control-tower micro-insights */}
            <OperatorInsightsStrip />

            {/* Layer Panel Slide-Over Dock (When toggled on Map) */}
            {showLayers && (
              <div className="absolute top-3 left-3 z-[1050]">
                <LayerPanel
                  data={data}
                  activeLayers={activeLayers}
                  setActiveLayers={setActiveLayers}
                  onClose={() => setShowLayers(false)}
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ══════════ SCRIMMED DRAWERS & MODALS ═══════════════════════ */}

      {/* Global Search Dialog */}
      {showDesktopSearch && (
        <div className="absolute top-4 left-[74px] z-[1065]">
          <SearchBar
            onLocate={(lat, lng, zoom) => {
              setFlyToLocation({ lat, lng, zoom, ts: Date.now() });
              setShowDesktopSearch(false);
            }}
            alwaysExpanded
          />
        </div>
      )}

      {/* Scrimmed Disruptions & Rerouting Drawer */}
      {showAlertsDrawer && (
        <>
          <div
            className="fixed inset-0 bg-black/20 z-[1065] transition-opacity"
            onClick={() => {
              setShowAlertsDrawer(false);
              setActiveOptionsAlertId(null);
            }}
            aria-hidden="true"
          />
          <aside
            className="fixed right-0 top-0 bottom-0 w-full max-w-[380px] sm:w-[380px] z-[1070] overflow-y-auto p-4 border-l select-text"
            style={{
              backgroundColor: 'var(--paper)',
              borderColor: 'var(--border-hairline)',
              boxShadow: 'none',
            }}
            aria-label="Alerts & Disruptions Drawer"
          >
            <div className="flex justify-between items-center mb-4">
              <div className="flex items-center gap-2">
                <h2 className="text-[14px] font-bold tracking-wide font-ui text-[var(--ink)]">
                  DISRUPTIONS & RECOVERY
                </h2>
                {activeAlertCount > 0 && (
                  <span className="px-1.5 py-0.5 rounded-[2px] bg-[var(--oxide-risk)] text-white text-[10px] font-mono font-bold">
                    {activeAlertCount}
                  </span>
                )}
              </div>
              <button
                onClick={() => {
                  setShowAlertsDrawer(false);
                  setActiveOptionsAlertId(null);
                }}
                className="p-1 rounded-[2px] hover:bg-black/5 transition-colors font-mono text-[13px] text-[var(--text-secondary)]"
                aria-label="Close alerts drawer"
              >
                ✕
              </button>
            </div>

            {activeOptionsAlertId ? (
              <RerouteOptions
                alertId={activeOptionsAlertId}
                onApproved={handleDecisionExecuted}
                onClose={() => setActiveOptionsAlertId(null)}
              />
            ) : (
              <AlertCenter
                onOpenInspector={openInspector}
                onOpenOptions={openOptions}
                refreshKey={opsVersion}
                defaultOpen
              />
            )}
          </aside>
        </>
      )}

      {/* Scrimmed Shipment Peek Drawer (max 360px, auto-closes on navigation) */}
      <ShipmentInspectorPanel
        shipmentId={selectedShipmentId}
        onClose={() => setSelectedShipmentId(null)}
        refreshKey={opsVersion}
        viewerRole={user?.role}
      />

      {/* Keyboard Shortcuts Listener */}
      <KeyboardShortcuts />

      {/* First-Paint Splash Veil */}
      {showSplash && (
        <div
          className="absolute inset-0 z-[2000] flex items-center justify-center pointer-events-none transition-opacity duration-300"
          style={{ backgroundColor: 'var(--paper)' }}
        >
          <div className="text-center">
            <div
              className="font-mono font-bold tracking-[0.35em] text-xl"
              style={{ color: 'var(--ink)' }}
            >
              NEXAFREIGHT
            </div>
            <div
              className="font-mono text-[10px] tracking-[0.25em] mt-1.5"
              style={{ color: 'var(--text-secondary)' }}
            >
              AUTONOMOUS LOGISTICS CONTROL TOWER
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <ErrorBoundary name="NexaFreight Control Tower">
      <OverviewCockpit />
    </ErrorBoundary>
  );
}
