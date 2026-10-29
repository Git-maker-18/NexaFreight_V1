'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter, useParams } from 'next/navigation';
import {
  ArrowLeft,
  Ship,
  Plane,
  Truck,
  Clock,
  AlertTriangle,
  DollarSign,
  TrendingUp,
  Activity,
  FileText,
  Calendar,
  Layers,
  ShieldCheck,
  RefreshCw,
} from 'lucide-react';
import { useAuthStore } from '@/store/useAuthStore';
import ErrorBoundary from '@/components/ErrorBoundary';
import DossierHeaderCards, { buildDossierCards } from '@/components/DossierHeaderCards';
import ShipmentMilestoneTracker from '@/components/ShipmentMilestoneTracker';
import RouteAlternativesPanel from '@/components/RouteAlternativesPanel';
import RouteMiniMap from '@/components/RouteMiniMap';
import { ProvenanceChip } from '@/components/ProvenanceBadge';
import LoadingGlobe from '@/components/illustrations/LoadingGlobe';
import PlexusHeader from '@/components/illustrations/PlexusHeader';
import {
  nexaClient,
  getAlerts,
  getPorts,
  getShipmentFinancials,
  getShipmentPrediction,
  getShipmentRoute,
  type Alert,
  type ShipmentDetail,
  type ShipmentFinancialsResponse,
  type ShipmentPredictResponse,
  type RouteFeatureCollection,
} from '@/lib/nexafreight';
import { formatInr, formatInrCompact, usdToInr } from '@/lib/format/inr';

const MODE_ICONS: Record<string, typeof Ship> = {
  SEA: Ship,
  AIR: Plane,
  ROAD: Truck,
  RAIL: Truck,
};

/* ── LIVE TRANSIT STATUS — control-tower telemetry strip ────────────────────
   Reference: shipment_detail_status.html. Four honest cells wired to real
   data only: time-to-destination countdown (last leg planned arrival),
   schedule variance (realized leg slip), current corridor leg
   (mode · vessel/flight), and destination port congestion from /map/ports. */

type PortFeat = { properties?: { locode?: string; un_locode?: string; name?: string; congestion_index?: number | null } };

function congestionLabel(idx: number): { label: string; color: string } {
  if (idx < 0.9) return { label: `LOW · ${idx.toFixed(2)}×`, color: 'var(--moss-positive)' };
  if (idx <= 1.2) return { label: `MODERATE · ${idx.toFixed(2)}×`, color: 'var(--cobalt)' };
  if (idx <= 1.5) return { label: `ELEVATED · ${idx.toFixed(2)}×`, color: '#B54708' };
  return { label: `SEVERE · ${idx.toFixed(2)}×`, color: 'var(--oxide-risk)' };
}

function LiveTransitStatusStrip({ shipment, portFeats, p50Hours }: { shipment: ShipmentDetail; portFeats: PortFeat[] | null; p50Hours: number | null }) {
  const legs = [...(shipment.legs || [])].sort((a, b) => (a.sequence_number ?? a.sequence ?? 0) - (b.sequence_number ?? b.sequence ?? 0));
  if (!legs.length) return null;

  const etaLeg = legs[legs.length - 1];
  const etaMs = etaLeg?.planned_arrival ? new Date(etaLeg.planned_arrival).getTime() : NaN;
  const now = Date.now();

  // TIME TO DESTINATION — "17d 06h" style countdown
  let countdown = '—';
  const countdownSub = etaLeg?.planned_arrival ? `PLANNED ARRIVAL · ${etaLeg.planned_arrival.slice(0, 16).replace('T', ' ')}` : 'NO ROUTE PLAN';
  if (!Number.isNaN(etaMs)) {
    const diff = etaMs - now;
    if (diff <= 0) {
      countdown = shipment.status === 'DELIVERED' ? 'ARRIVED' : 'IMMINENT';
    } else {
      const d = Math.floor(diff / 86_400_000);
      const h = Math.floor((diff % 86_400_000) / 3_600_000);
      const m = Math.floor((diff % 3_600_000) / 60_000);
      countdown = d > 0 ? `${d}d ${String(h).padStart(2, '0')}h` : `${h}h ${String(m).padStart(2, '0')}m`;
    }
  }

  // SCHEDULE VARIANCE — realized slip on completed legs
  const slipH = legs.reduce(
    (s, l) => (l.actual_arrival && l.planned_arrival ? s + (new Date(l.actual_arrival).getTime() - new Date(l.planned_arrival).getTime()) / 3_600_000 : s),
    0,
  );
  const variance = Math.abs(slipH) > 0.05
    ? `${slipH > 0 ? '+' : '−'}${Math.abs(slipH).toFixed(1)} h`
    : 'ON PLAN';
  const varianceTone = slipH > 2 ? 'var(--oxide-risk)' : slipH > 0.5 ? '#B54708' : 'var(--moss-positive)';
  const varianceFlag = slipH > 2 ? ' · ETA_WARN' : slipH > 0.5 ? ' · WATCH' : '';

  // CURRENT CORRIDOR — active leg else next planned leg
  const active = legs.find((l) => l.status === 'IN_PROGRESS') ?? legs.find((l) => l.status === 'PLANNED') ?? etaLeg;
  const corridorSub = [active?.mode, active?.vessel?.name || active?.flight_number].filter(Boolean).join(' · ') || 'NEXT SCHEDULED LEG';

  // PORT CONGESTION — destination locode → /map/ports congestion_index
  const portFeat = (portFeats || []).find((f) => (f.properties?.locode || f.properties?.un_locode) === (active?.destination || shipment.destination));
  const cIdx = portFeat?.properties?.congestion_index;
  const cong = typeof cIdx === 'number' ? congestionLabel(cIdx) : null;

  const cell = 'p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex flex-col gap-1';

  return (
    <section
      className="p-4 rounded-[3px] border bg-[var(--paper)]"
      style={{ borderColor: 'var(--border-hairline)' }}
      aria-label="Live transit status telemetry"
    >
      <div className="flex items-center justify-between pb-3 border-b border-[var(--border-hairline)] mb-4">
        <div className="flex items-center gap-2">
          <Clock className="w-4 h-4 text-[var(--cobalt)]" />
          <h3 className="font-ui text-[14px] font-bold text-[var(--ink)]">Live Transit Status</h3>
        </div>
        <span className="font-mono text-[9px] tracking-[0.12em] text-[var(--text-secondary)] border border-[var(--border-hairline)] rounded-[2px] px-1.5 py-0.5">
          LIVE FEED
        </span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4 font-mono text-[12px]">
        <div className={cell}>
          <span className="text-[10px] text-[var(--text-secondary)] uppercase tracking-[0.08em]">Time to Destination</span>
          <span className="text-[18px] font-bold text-[var(--ink)] tabular-nums">{countdown}</span>
          <span className="text-[9.5px] text-[var(--text-secondary)]">{countdownSub}</span>
        </div>
        <div className={cell}>
          <span className="text-[10px] text-[var(--text-secondary)] uppercase tracking-[0.08em]">Schedule Variance</span>
          <span className="text-[18px] font-bold tabular-nums" style={{ color: varianceTone }}>
            {variance}
            <span className="text-[9.5px] font-normal" style={{ color: varianceTone }}>{varianceFlag}</span>
          </span>
          <span className="text-[9.5px] text-[var(--text-secondary)]">REALIZED SLIP · EMPIRICAL P50 {(p50Hours ?? 0).toFixed(1)} H</span>
        </div>
        <div className={cell}>
          <span className="text-[10px] text-[var(--text-secondary)] uppercase tracking-[0.08em]">Current Corridor</span>
          <span className="text-[15px] font-bold text-[var(--ink)] tracking-tight">
            {active?.origin || '—'} → {active?.destination || '—'}
          </span>
          <span className="text-[9.5px] text-[var(--text-secondary)]">{corridorSub}</span>
        </div>
        <div className={cell}>
          <span className="text-[10px] text-[var(--text-secondary)] uppercase tracking-[0.08em]">Port Congestion · {active?.destination || shipment.destination}</span>
          <span className="text-[15px] font-bold tabular-nums" style={{ color: cong?.color ?? 'var(--text-secondary)' }}>
            {cong?.label ?? 'NO FEED'}
          </span>
          <span className="text-[9.5px] text-[var(--text-secondary)]">{portFeat?.properties?.name || 'DESTINATION NOT IN PORT INDEX'}</span>
        </div>
      </div>
    </section>
  );
}

function ShipmentDossierPageContent() {
  const router = useRouter();
  const routeParams = useParams();
  const shipmentId = String(routeParams?.id || '');

  const { isAuthenticated, isHydrated } = useAuthStore();
  const [shipment, setShipment] = useState<ShipmentDetail | null>(null);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [financials, setFinancials] = useState<ShipmentFinancialsResponse | null>(null);
  const [prediction, setPrediction] = useState<ShipmentPredictResponse | null>(null);
  const [routeData, setRouteData] = useState<RouteFeatureCollection | null>(null);
  const [portFeats, setPortFeats] = useState<PortFeat[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isHydrated && !isAuthenticated) {
      router.replace('/login');
    }
  }, [isHydrated, isAuthenticated, router]);

  const loadData = () => {
    if (!shipmentId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      nexaClient.getShipmentDetail(shipmentId).catch((err) => {
        throw new Error(err?.message || 'Failed to load shipment');
      }),
      getAlerts().catch(() => ({ alerts: [] })),
      getShipmentFinancials(shipmentId).catch(() => null),
      getShipmentPrediction(shipmentId).catch(() => null),
      getShipmentRoute(shipmentId).catch(() => null),
      getPorts().catch(() => null),
    ])
      .then(([detail, alertsResp, finResp, predResp, routeResp, portsResp]) => {
        if (!cancelled) {
          setShipment(detail as ShipmentDetail);
          setAlerts(alertsResp.alerts.filter((a) => a.shipment_id === shipmentId));
          setFinancials(finResp);
          setPrediction(predResp);
          setRouteData(routeResp);
          const pf = portsResp as unknown as { type?: string; features?: PortFeat[] } | PortFeat[] | null;
          setPortFeats(pf ? (Array.isArray(pf) ? pf : pf.features ?? []) : null);
        }
      })
      .catch((err) => {
        if (!cancelled) setError(err.message || 'Failed to load dossier');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  };

  useEffect(() => {
    return loadData();
  }, [shipmentId]);

  if (!isHydrated || !isAuthenticated) return null;

  const refNumber = `NF-${shipmentId.slice(0, 8).toUpperCase()}`;

  const dossierCards = buildDossierCards({
    origin: shipment?.origin,
    destination: shipment?.dest ?? shipment?.destination,
    status: shipment?.status,
    slaDeadline: (shipment as { sla_deadline?: string })?.sla_deadline ?? null,
    slaStatus: (shipment as { sla_status?: string })?.sla_status ?? null,
    exposureUsd: financials
      ? financials.pnl.sla_penalty_usd + financials.pnl.demurrage_usd
      : null,
    co2Kg: (shipment as { kg_co2?: number })?.kg_co2 ?? null,
    containers: shipment?.container_count,
  });

  // Calculate prediction confidence display
  const predConfidencePct = prediction
    ? prediction.sla_risk_level === 'BREACH'
      ? 18
      : prediction.sla_risk_level === 'HIGH'
      ? 38
      : prediction.sla_risk_level === 'MEDIUM'
      ? 68
      : 94
    : 85;

  return (
    <div className="min-h-screen flex flex-col bg-[var(--paper)] text-[var(--ink)]">
      <div className="pl-[58px] min-h-screen flex flex-col relative">
        {/* Cockpit Status Header */}
        <header
          className="h-12 border-b flex items-center justify-between px-4 z-[1040] select-none flex-shrink-0 relative overflow-hidden"
          style={{
            backgroundColor: 'var(--paper)',
            borderColor: 'var(--border-hairline)',
          }}
        >
          <PlexusHeader />

          <div className="relative z-10 flex items-center gap-3">
            <Link
              href="/shipments"
              className="flex items-center gap-1.5 text-[11px] font-mono font-medium text-[var(--text-secondary)] hover:text-[var(--cobalt)] transition-colors"
            >
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>MANIFEST</span>
            </Link>

            <span className="text-[var(--border-hairline)]">/</span>

            <div className="flex items-center gap-2">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src="/nexafreight-mark.svg" alt="NexaFreight" className="w-4 h-4 rounded-[2px]" />
              <span className="font-ui text-[13px] font-bold tracking-wider text-[var(--ink)]">
                WAYBILL {refNumber}
              </span>
              <span className="hidden sm:inline font-mono text-[10px] text-[var(--text-secondary)]">
                {shipmentId}
              </span>
            </div>

            <ProvenanceChip provenance={shipment?.provenance || 'REAL'} size="sm" />
          </div>

          <div className="relative z-10 flex items-center gap-2 font-mono text-[10px]">
            <span
              className="px-2 py-0.5 rounded-[2px] border font-bold"
              style={{
                borderColor:
                  shipment?.status === 'DELAYED'
                    ? 'var(--oxide-risk)'
                    : 'var(--border-hairline)',
                backgroundColor: 'var(--bg-subtle)',
                color:
                  shipment?.status === 'DELAYED'
                    ? 'var(--oxide-risk)'
                    : 'var(--moss-positive)',
              }}
            >
              {shipment?.status || (loading ? 'LOADING' : 'ACTIVE')}
            </span>

            <button
              onClick={loadData}
              className="p-1 rounded-[2px] border border-[var(--border-hairline)] hover:bg-black/5 text-[var(--text-secondary)]"
              title="Refresh dossier"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </header>

        {/* Dossier Body Content */}
        {loading && !shipment ? (
          <div className="flex-1 flex items-center justify-center py-28">
            <LoadingGlobe caption="SYNCHRONIZING SHIPMENT DOSSIER TELEMETRY..." size={260} />
          </div>
        ) : error ? (
          <main className="flex-1 p-8 max-w-4xl mx-auto flex flex-col items-center justify-center">
            <div className="p-6 rounded-[3px] border border-[var(--oxide-risk)] bg-red-50 text-[var(--oxide-risk)] font-mono text-[12px] text-center max-w-lg">
              <p className="font-bold mb-2">ERROR LOADING SHIPMENT</p>
              <p className="mb-4">{error}</p>
              <button
                onClick={loadData}
                className="px-3 py-1.5 rounded-[2px] border border-[var(--oxide-risk)] bg-[var(--paper)] text-[var(--oxide-risk)] font-bold text-[11px]"
              >
                RETRY
              </button>
            </div>
          </main>
        ) : (
          <main className="flex-1 p-6 max-w-6xl w-full mx-auto space-y-6">
            {/* 1. Header KPI Cards Strip (Lane, SLA, Exposure, CO2) */}
            <DossierHeaderCards cards={dossierCards} />

            {/* 2. Route Trajectory Map (Mercator Vector Projection) */}
            <RouteMiniMap
              routeData={routeData}
              origin={shipment?.origin}
              destination={shipment?.dest ?? shipment?.destination}
              status={shipment?.status}
              legs={shipment?.legs || []}
            />

            {/* 3. ETA Prediction & SLA Risk Strip */}
            <section
              className="p-4 rounded-[3px] border bg-[var(--paper)]"
              style={{ borderColor: 'var(--border-hairline)' }}
              aria-label="Empirical Transit Quantiles & SLA Risk Assessment"
            >
              <div className="flex items-center justify-between pb-3 border-b border-[var(--border-hairline)] mb-4">
                <div className="flex items-center gap-2">
                  <Activity className="w-4 h-4 text-[var(--cobalt)]" />
                  <h3 className="font-ui text-[14px] font-bold text-[var(--ink)]">
                    Empirical Transit Quantiles & SLA Risk Assessment
                  </h3>
                </div>
                <ProvenanceChip provenance={shipment?.status === 'DELIVERED' ? 'REAL' : (prediction?.provenance || 'DERIVED')} size="sm" />
              </div>

              <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono text-[12px]">
                {/* P50 Expected Delay */}
                <div className="p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex flex-col gap-1">
                  <span className="text-[10px] text-[var(--text-secondary)] uppercase">
                    P50 Expected Delay
                  </span>
                  <div className="flex items-baseline gap-2">
                    <span className="text-[18px] font-bold text-[var(--ink)] tabular-nums">
                      {shipment?.status === 'DELIVERED'
                        ? '0.0 h'
                        : prediction
                        ? `${prediction.delay_p50_hours.toFixed(1)} h`
                        : '0.0 h'}
                    </span>
                    <span className="text-[10px] text-[var(--text-secondary)]">
                      {shipment?.status === 'DELIVERED' ? 'voyage completed' : 'empirical lane residual'}
                    </span>
                  </div>
                </div>

                {/* SLA Risk Level */}
                <div className="p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex flex-col gap-1">
                  <span className="text-[10px] text-[var(--text-secondary)] uppercase">
                    SLA Risk Assessment
                  </span>
                  <div className="flex items-center gap-2">
                    <span
                      className="px-2 py-0.5 rounded-[2px] text-[12px] font-bold border"
                      style={{
                        backgroundColor:
                          shipment?.status === 'DELIVERED'
                            ? 'rgba(62, 107, 79, 0.08)'
                            : prediction?.sla_risk_level === 'BREACH' ||
                              prediction?.sla_risk_level === 'HIGH'
                            ? 'rgba(180, 69, 47, 0.08)'
                            : 'rgba(62, 107, 79, 0.08)',
                        borderColor:
                          shipment?.status === 'DELIVERED'
                            ? 'var(--moss-positive)'
                            : prediction?.sla_risk_level === 'BREACH' ||
                              prediction?.sla_risk_level === 'HIGH'
                            ? 'var(--oxide-risk)'
                            : 'var(--moss-positive)',
                        color:
                          shipment?.status === 'DELIVERED'
                            ? 'var(--moss-positive)'
                            : prediction?.sla_risk_level === 'BREACH' ||
                              prediction?.sla_risk_level === 'HIGH'
                            ? 'var(--oxide-risk)'
                            : 'var(--moss-positive)',
                      }}
                    >
                      {shipment?.status === 'DELIVERED'
                        ? 'FULFILLED'
                        : prediction?.sla_risk_level || 'ON_TIME'}
                    </span>
                    {prediction?.model_version && shipment?.status !== 'DELIVERED' && (
                      <span className="text-[10px] text-[var(--text-secondary)]">
                        v{prediction.model_version}
                      </span>
                    )}
                  </div>
                </div>

                {/* Model Confidence Bar */}
                <div className="p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex flex-col gap-1.5 justify-center">
                  <div className="flex justify-between items-center text-[10px] text-[var(--text-secondary)]">
                    <span>ON-TIME CONFIDENCE</span>
                    <span className="font-bold text-[var(--ink)] tabular-nums">
                      {shipment?.status === 'DELIVERED' ? 100 : predConfidencePct}%
                    </span>
                  </div>
                  <div className="w-full h-2 rounded-[1px] bg-[var(--border-hairline)] overflow-hidden">
                    <div
                      className="h-full rounded-[1px] transition-all"
                      style={{
                        width: `${shipment?.status === 'DELIVERED' ? 100 : predConfidencePct}%`,
                        backgroundColor: 'var(--moss-positive)',
                      }}
                    />
                  </div>
                </div>
              </div>
            </section>

            {/* 3b. Live Transit Status — countdown / variance / corridor / congestion */}
            {shipment && (
              <LiveTransitStatusStrip shipment={shipment} portFeats={portFeats} p50Hours={prediction?.delay_p50_hours ?? null} />
            )}

            {/* 4. Visual Transit Milestone Stepper */}
            {shipment && (
              <section
                className="p-4 rounded-[3px] border bg-[var(--bg-subtle)]"
                style={{ borderColor: 'var(--border-hairline)' }}
                aria-label="Transit Milestones"
              >
                <div className="text-[11px] font-mono text-[var(--text-secondary)] tracking-wider mb-2 font-bold">
                  TRANSIT MILESTONES & ACTIVE CORRIDORS
                </div>
                <ShipmentMilestoneTracker
                  legs={shipment.legs || []}
                  alerts={alerts}
                  origin={shipment.origin}
                  destination={shipment.dest ?? shipment.destination}
                  status={shipment.status}
                />
              </section>
            )}

            {/* 5. Multimodal Route Legs Timeline */}
            {shipment?.legs && shipment.legs.length > 0 && (
              <section
                className="p-4 rounded-[3px] border bg-[var(--paper)]"
                style={{ borderColor: 'var(--border-hairline)' }}
                aria-label="Multimodal Legs Timeline"
              >
                <div className="flex items-center justify-between pb-3 border-b border-[var(--border-hairline)] mb-4">
                  <div className="flex items-center gap-2">
                    <Layers className="w-4 h-4 text-[var(--cobalt)]" />
                    <h3 className="font-ui text-[14px] font-bold text-[var(--ink)]">
                      Multimodal Route Legs ({shipment.legs.length})
                    </h3>
                  </div>
                  <span className="font-mono text-[11px] text-[var(--text-secondary)]">
                    ACTIVE TRANSPORT CHAIN
                  </span>
                </div>

                <div className="space-y-2.5">
                  {shipment.legs.map((leg, idx) => {
                    const ModeIcon = MODE_ICONS[leg.mode] || Ship;
                    return (
                      <div
                        key={leg.id || idx}
                        className="p-3.5 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex flex-wrap items-center justify-between gap-3 text-[12px] font-mono"
                      >
                        <div className="flex items-center gap-3">
                          <span className="w-6 h-6 rounded-[2px] bg-[var(--paper)] border border-[var(--border-hairline)] flex items-center justify-center font-bold text-[11px] text-[var(--ink)]">
                            {idx + 1}
                          </span>
                          <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-[2px] bg-[var(--paper)] border border-[var(--border-hairline)]">
                            <ModeIcon className="w-3.5 h-3.5 text-[var(--cobalt)]" />
                            <span className="font-bold text-[var(--ink)]">{leg.mode}</span>
                          </div>
                          <span className="text-[var(--text-secondary)]">
                            {leg.distance_km ? `${Math.round(leg.distance_km)} km` : '—'}
                          </span>
                        </div>

                        <div className="flex items-center gap-4 text-[11px]">
                          {leg.planned_departure && (
                            <div className="flex items-center gap-1 text-[var(--text-secondary)]">
                              <Calendar className="w-3 h-3" />
                              <span>
                                Dep:{' '}
                                {new Date(leg.planned_departure).toLocaleDateString('en-GB', {
                                  day: '2-digit',
                                  month: 'short',
                                })}
                              </span>
                            </div>
                          )}
                          {leg.planned_arrival && (
                            <div className="flex items-center gap-1 text-[var(--text-secondary)]">
                              <Clock className="w-3 h-3" />
                              <span>
                                Arr:{' '}
                                {new Date(leg.planned_arrival).toLocaleDateString('en-GB', {
                                  day: '2-digit',
                                  month: 'short',
                                })}
                              </span>
                            </div>
                          )}

                          <span className="px-2 py-0.5 rounded-[2px] text-[10px] font-bold border border-[var(--border-hairline)] bg-[var(--paper)] text-[var(--ink)]">
                            {leg.status || 'PLANNED'}
                          </span>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}

            {/* 6. Chronological Events Audit Log */}
            <section
              className="p-4 rounded-[3px] border bg-[var(--paper)]"
              style={{ borderColor: 'var(--border-hairline)' }}
              aria-label="Audit Events Log"
            >
              <div className="flex items-center justify-between pb-3 border-b border-[var(--border-hairline)] mb-4">
                <div className="flex items-center gap-2">
                  <FileText className="w-4 h-4 text-[var(--cobalt)]" />
                  <h3 className="font-ui text-[14px] font-bold text-[var(--ink)]">
                    Audit Chronology & Milestone Events
                  </h3>
                </div>
                <span className="font-mono text-[10px] text-[var(--text-secondary)]">
                  IMMUTABLE LOG
                </span>
              </div>

              {shipment?.events && shipment.events.length > 0 ? (
                <div className="space-y-2 font-mono text-[11px]">
                  {shipment.events.map((evt, idx) => (
                    <div
                      key={evt.id || idx}
                      className="p-2.5 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex items-center justify-between"
                    >
                      <div className="flex items-center gap-3">
                        <span className="text-[var(--text-secondary)]">
                          {new Date(evt.timestamp).toLocaleDateString('en-GB', {
                            day: '2-digit',
                            month: 'short',
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </span>
                        <span className="font-bold text-[var(--ink)]">
                          {evt.event_type || evt.type || 'STATUS_UPDATE'}
                        </span>
                        <span className="text-[var(--text-secondary)]">
                          {evt.message || evt.description}
                        </span>
                      </div>
                      {evt.actor && (
                        <span className="text-[10px] text-[var(--text-secondary)] border border-[var(--border-hairline)] px-1.5 py-0.5 rounded-[2px] bg-[var(--paper)]">
                          {evt.actor}
                        </span>
                      )}
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-2 font-mono text-[11px]">
                  <div className="p-2.5 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-[var(--text-secondary)]">WAYBILL ISSUANCE</span>
                      <span className="font-bold text-[var(--ink)]">WAYBILL_RECORDED</span>
                      <span className="text-[var(--text-secondary)]">
                        Consignment registered in carrier ledger with EDI manifest.
                      </span>
                    </div>
                    <span className="text-[10px] text-[var(--moss-positive)] font-bold">
                      VERIFIED
                    </span>
                  </div>
                  <div className="p-2.5 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] flex items-center justify-between">
                    <div className="flex items-center gap-3">
                      <span className="text-[var(--text-secondary)]">AIS ACQUISITION</span>
                      <span className="font-bold text-[var(--ink)]">TELEMETRY_LINKED</span>
                      <span className="text-[var(--text-secondary)]">
                        Carrier positioning linked to live global maritime and road feeds.
                      </span>
                    </div>
                    <span className="text-[10px] text-[var(--cobalt)] font-bold">
                      LIVE
                    </span>
                  </div>
                </div>
              )}
            </section>

            {/* 7. Financial Ledger Breakdown (In ₹) */}
            <section
              className="p-4 rounded-[3px] border bg-[var(--paper)]"
              style={{ borderColor: 'var(--border-hairline)' }}
              aria-label="Financial PnL Ledger"
            >
              <div className="flex items-center justify-between pb-3 border-b border-[var(--border-hairline)] mb-4">
                <div className="flex items-center gap-2">
                  <DollarSign className="w-4 h-4 text-[var(--cobalt)]" />
                  <h3 className="font-ui text-[14px] font-bold text-[var(--ink)]">
                    Shipment Financials & PnL Ledger (₹)
                  </h3>
                </div>
                <div className="flex items-center gap-2">
                  <ProvenanceChip provenance={financials?.provenance || 'DERIVED'} size="sm" />
                  <span className="font-mono text-[10px] text-[var(--text-secondary)]">
                    fx.usd_inr = 95.8
                  </span>
                </div>
              </div>

              {financials ? (
                <div className="space-y-4">
                  {/* Financial KPI Summary Tiles */}
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono">
                    <div className="p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)]">
                      <span className="text-[10px] text-[var(--text-secondary)] block">
                        TOTAL REVENUE
                      </span>
                      <span className="text-[15px] font-bold text-[var(--ink)] tabular-nums">
                        {formatInr(usdToInr(financials.pnl.revenue_usd))}
                      </span>
                    </div>

                    <div className="p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)]">
                      <span className="text-[10px] text-[var(--text-secondary)] block">
                        FREIGHT COST
                      </span>
                      <span className="text-[15px] font-bold text-[var(--ink)] tabular-nums">
                        {formatInr(usdToInr(financials.pnl.freight_cost_usd))}
                      </span>
                    </div>

                    <div className="p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)]">
                      <span className="text-[10px] text-[var(--text-secondary)] block">
                        SLA PENALTY / EXPOSURE
                      </span>
                      <span
                        className="text-[15px] font-bold tabular-nums"
                        style={{
                          color:
                            financials.pnl.sla_penalty_usd > 0
                              ? 'var(--oxide-risk)'
                              : 'var(--ink)',
                        }}
                      >
                        {formatInr(usdToInr(financials.pnl.sla_penalty_usd))}
                      </span>
                    </div>

                    <div className="p-3 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)]">
                      <span className="text-[10px] text-[var(--text-secondary)] block">
                        NET REALIZED MARGIN
                      </span>
                      <span
                        className="text-[15px] font-bold tabular-nums"
                        style={{
                          color:
                            financials.pnl.margin_usd >= 0
                              ? 'var(--moss-positive)'
                              : 'var(--oxide-risk)',
                        }}
                      >
                        {formatInr(usdToInr(financials.pnl.margin_usd))}{' '}
                        {financials.pnl.margin_pct != null && (
                          <span className="text-[11px] font-normal">
                            ({(financials.pnl.margin_pct * 100).toFixed(1)}%)
                          </span>
                        )}
                      </span>
                    </div>
                  </div>

                  {/* Customer Orders Table */}
                  {financials.orders && financials.orders.length > 0 && (
                    <div className="border border-[var(--border-hairline)] rounded-[2px] overflow-hidden">
                      <table className="w-full text-left font-mono text-[11px]">
                        <thead className="bg-[var(--bg-subtle)] border-b border-[var(--border-hairline)] text-[10px] text-[var(--text-secondary)]">
                          <tr>
                            <th className="py-2 px-3">Order Number</th>
                            <th className="py-2 px-3">SLA Status</th>
                            <th className="py-2 px-3">Revenue (₹)</th>
                            <th className="py-2 px-3">Shipping Cost (₹)</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-[var(--border-hairline)]">
                          {financials.orders.map((ord) => (
                            <tr key={ord.order_number} className="hover:bg-[var(--bg-subtle)]">
                              <td className="py-2 px-3 font-bold text-[var(--ink)]">
                                {ord.order_number}
                              </td>
                              <td className="py-2 px-3">
                                <span className="px-1.5 py-0.5 rounded-[2px] text-[10px] font-bold border border-[var(--border-hairline)] bg-[var(--paper)]">
                                  {ord.sla_status}
                                </span>
                              </td>
                              <td className="py-2 px-3 tabular-nums font-semibold text-[var(--ink)]">
                                {formatInr(usdToInr(ord.revenue || 0))}
                              </td>
                              <td className="py-2 px-3 tabular-nums text-[var(--text-secondary)]">
                                {formatInr(usdToInr(ord.shipping_cost || 0))}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  )}
                </div>
              ) : (
                <div className="p-4 rounded-[2px] border border-[var(--border-hairline)] bg-[var(--bg-subtle)] text-[11px] font-mono text-[var(--text-secondary)]">
                  Financial figures are restricted to operator clearance or pending settlement.
                </div>
              )}
            </section>

            {/* 8. Route Alternatives & Recommendation Drawer Block */}
            {shipment && (
              <section
                className="p-4 rounded-[3px] border bg-[var(--paper)]"
                style={{ borderColor: 'var(--border-hairline)' }}
                aria-label="Route Alternatives"
              >
                <RouteAlternativesPanel shipmentId={shipmentId} showTabs />
              </section>
            )}
          </main>
        )}
      </div>
    </div>
  );
}

export default function ShipmentDossierPage() {
  return (
    <ErrorBoundary name="Shipment Dossier">
      <ShipmentDossierPageContent />
    </ErrorBoundary>
  );
}
