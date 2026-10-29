'use client';

import React, { useCallback, useEffect, useMemo, useState } from 'react';
import ProvenanceBadge from './ProvenanceBadge';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as RechartsTooltip,
  ResponsiveContainer,
  CartesianGrid,
  Legend,
} from 'recharts';
import {
  getAnalyticsEsg,
  getAnalyticsScorecard,
  getAnalyticsSla,
  getAnalyticsSummary,
  getDemandForecast,
  type AnalyticsEsgResponse,
  type AnalyticsFinancialResponse,
  type AnalyticsSlaResponse,
  type AnalyticsSummaryResponse,
  type DemandForecastSeriesPoint,
  type WindowSlice,
} from '@/lib/nexafreight';

export interface AnalyticsDashboardProps {
  openKey?: number;
  onClose?: () => void;
  onOpenInspector?: (shipmentId: string) => void;
}

const TABS = ['Scorecard', 'Fleet', 'SLA risk', 'ESG'] as const;
type Tab = (typeof TABS)[number];

/* ── Chartroom design tokens (mirroring CSS custom properties) ─────────── */
const T = {
  paper: '#F6F7F4',
  surface: '#FFFFFF',
  subtle: '#FAFBF9',
  ink: '#16181D',
  secondary: '#5A5D66',
  hairline: '#D4D5D0',
  cobalt: '#2547C8',
  cobaltLight: 'rgba(37,71,200,0.08)',
  oxide: '#B4452F',
  oxideLight: 'rgba(180,69,47,0.10)',
  moss: '#3E6B4F',
  mossLight: 'rgba(62,107,79,0.10)',
} as const;

/* ── Formatters ─────────────────────────────────────────────────────────── */
const fmtUsd = (n: number | null | undefined) =>
  n == null ? '—' : `$${n.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;

const fmtPct = (n: number | null | undefined) =>
  n == null ? '—' : `${(n * 100).toFixed(1)}%`;

/* ── Demand-forecast lanes (frozen StatsForecast AutoETS corpus) ───────────────  */
const SPARKLINE_LANES: Array<{ category: string; region: string; label: string }> = [
  { category: 'Computers', region: 'West Africa', label: 'Computers · W. Africa' },
  { category: 'Clothes', region: 'Western Europe', label: 'Clothes · W. Europe' },
  { category: 'Garden Tools', region: 'Central America', label: 'Garden Tools · C. America' },
];

/* ── Sparkline SVG ────────────────────────────────────────────────────────  */
function Sparkline({
  series,
  height = 44,
}: {
  series: DemandForecastSeriesPoint[];
  height?: number;
}) {
  if (series.length < 2) return null;
  const w = 200;
  const ys = series.map((p) => p.yhat);
  const min = Math.min(...ys);
  const max = Math.max(...ys);
  const span = max - min || 1;
  const pts = series
    .map(
      (p, i) =>
        `${(i / (series.length - 1)) * w},${height - ((p.yhat - min) / span) * (height - 8) - 4}`,
    )
    .join(' ');
  const split = series.findIndex((p) => p.is_forecast);
  return (
    <svg width={w} height={height} aria-hidden="true">
      {split > 1 && (
        <polyline
          points={pts.split(' ').slice(0, split + 1).join(' ')}
          fill="none"
          stroke={T.cobalt}
          strokeWidth="1.6"
        />
      )}
      {split >= 1 && (
        <polyline
          points={pts.split(' ').slice(split).join(' ')}
          fill="none"
          stroke={T.cobalt}
          strokeWidth="1.4"
          strokeDasharray="3 2"
          opacity={0.55}
        />
      )}
      {split <= 0 && (
        <polyline
          points={pts}
          fill="none"
          stroke={T.cobalt}
          strokeWidth="1.4"
          strokeDasharray="3 2"
          opacity={0.55}
        />
      )}
    </svg>
  );
}

/* ── Status pill ─────────────────────────────────────────────────────────── */
function StatusPill({ status }: { status: string }) {
  const isLate = status === 'LATE';
  const isRisk = status === 'AT_RISK';
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '1px 6px',
        borderRadius: 2,
        fontSize: 9,
        fontFamily: 'var(--font-mono, ui-monospace)',
        fontWeight: 600,
        letterSpacing: '0.08em',
        textTransform: 'uppercase' as const,
        backgroundColor: isLate ? T.oxideLight : isRisk ? 'rgba(180,69,47,0.06)' : T.mossLight,
        color: isLate ? T.oxide : isRisk ? '#8B3A24' : T.moss,
        border: `1px solid ${isLate ? T.oxide : isRisk ? '#C4714F' : T.moss}`,
      }}
    >
      {status}
    </span>
  );
}

/* ── Corner-tick registration marks ──────────────────────────────────────── */
const TICK_SIZE = 6;
function CornerTicks() {
  const s: React.CSSProperties = {
    position: 'absolute',
    width: TICK_SIZE,
    height: TICK_SIZE,
    borderColor: T.hairline,
    borderStyle: 'solid',
    borderWidth: 0,
  };
  return (
    <>
      <span style={{ ...s, top: 0, left: 0, borderTopWidth: 1, borderLeftWidth: 1 }} />
      <span style={{ ...s, top: 0, right: 0, borderTopWidth: 1, borderRightWidth: 1 }} />
      <span style={{ ...s, bottom: 0, left: 0, borderBottomWidth: 1, borderLeftWidth: 1 }} />
      <span style={{ ...s, bottom: 0, right: 0, borderBottomWidth: 1, borderRightWidth: 1 }} />
    </>
  );
}

/* ── Section heading ─────────────────────────────────────────────────────── */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        fontSize: 10,
        fontFamily: 'var(--font-mono, ui-monospace)',
        fontWeight: 600,
        letterSpacing: '0.10em',
        textTransform: 'uppercase',
        color: T.secondary,
        marginBottom: 6,
      }}
    >
      {children}
    </div>
  );
}

/* ── Card wrapper ────────────────────────────────────────────────────────── */
function Card({
  children,
  style,
}: {
  children: React.ReactNode;
  style?: React.CSSProperties;
}) {
  return (
    <div
      style={{
        position: 'relative',
        background: T.surface,
        border: `1px solid ${T.hairline}`,
        borderRadius: 3,
        padding: '8px 10px',
        ...style,
      }}
    >
      <CornerTicks />
      {children}
    </div>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   MAIN COMPONENT
══════════════════════════════════════════════════════════════════════════ */
export default function AnalyticsDashboard({
  openKey = 0,
  onClose,
  onOpenInspector,
}: AnalyticsDashboardProps) {
  const [tab, setTab] = useState<Tab>('Scorecard');
  const [scorecard, setScorecard] = useState<AnalyticsFinancialResponse | null>(null);
  const [summary, setSummary] = useState<AnalyticsSummaryResponse | null>(null);
  const [sla, setSla] = useState<AnalyticsSlaResponse | null>(null);
  const [esg, setEsg] = useState<AnalyticsEsgResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sparkError, setSparkError] = useState<string | null>(null);
  const [sparklines, setSparklines] = useState<Record<string, DemandForecastSeriesPoint[]>>({});

  const load = useCallback(async () => {
    setError(null);
    try {
      const [sc, su, sl, eg] = await Promise.all([
        getAnalyticsScorecard(),
        getAnalyticsSummary(),
        getAnalyticsSla(),
        getAnalyticsEsg(),
      ]);
      setScorecard(sc);
      setSummary(su);
      setSla(sl);
      setEsg(eg);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const loadSparklines = useCallback(async () => {
    setSparkError(null);
    for (const lane of SPARKLINE_LANES) {
      try {
        const res = await getDemandForecast(lane.category, lane.region, 90);
        if (res) {
          setSparklines((prev) => ({ ...prev, [lane.label]: res.series }));
        }
      } catch (err) {
        setSparkError(err instanceof Error ? err.message : String(err));
        return;
      }
    }
  }, []);

  useEffect(() => {
    void load();
    void loadSparklines();
  }, [load, loadSparklines, openKey]);

  const windows = useMemo(
    () => ([scorecard?.day, scorecard?.week, scorecard?.month].filter(Boolean) as WindowSlice[]),
    [scorecard],
  );

  /* ── Fleet totals for status distribution bar ───────────────────────── */
  const fleetTotal = summary
    ? (summary.in_transit ?? 0) + (summary.delivered ?? 0) + (summary.delayed ?? 0)
    : 0;

  /* ── Custom bar chart tooltip ──────────────────────────────────────────  */
  const CustomTooltip = ({
    active,
    payload,
    label,
  }: {
    active?: boolean;
    payload?: Array<{ name: string; value: number; color: string }>;
    label?: string;
  }) => {
    if (!active || !payload?.length) return null;
    return (
      <div
        style={{
          background: T.surface,
          border: `1px solid ${T.hairline}`,
          borderRadius: 3,
          padding: '6px 8px',
          fontSize: 10,
          fontFamily: 'var(--font-mono, ui-monospace)',
          color: T.ink,
          boxShadow: 'none',
        }}
      >
        <div style={{ marginBottom: 4, color: T.secondary }}>{label}</div>
        {payload.map((p) => (
          <div key={p.name} style={{ color: p.color }}>
            {p.name}: {fmtUsd(p.value)}
          </div>
        ))}
      </div>
    );
  };

  return (
    <section
      aria-label="Analytics dashboard"
      style={{
        position: 'absolute',
        top: 56,
        left: 12,
        bottom: 12,
        width: 720,
        maxWidth: 'calc(100vw - 24px)',
        zIndex: 1055,
        background: T.paper,
        border: `1px solid ${T.hairline}`,
        borderRadius: 4,
        color: T.ink,
        display: 'flex',
        flexDirection: 'column',
        overflow: 'hidden',
        boxShadow: 'none',
      }}
    >
      {/* ── Header ───────────────────────────────────────────────────────── */}
      <header
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          padding: '0 12px',
          height: 44,
          borderBottom: `1px solid ${T.hairline}`,
          background: T.surface,
          flexShrink: 0,
        }}
      >
        {/* Title + provenance */}
        <span
          style={{
            fontSize: 11,
            fontWeight: 600,
            fontFamily: 'var(--font-ui, sans-serif)',
            letterSpacing: '0.12em',
            textTransform: 'uppercase',
            color: T.ink,
          }}
        >
          OPERATIONAL ANALYTICS
        </span>
        <ProvenanceBadge provenance="DERIVED" size="xs" title="Server-computed rollup" />

        {/* Tab strip */}
        <div style={{ display: 'flex', gap: 2, marginLeft: 12 }}>
          {TABS.map((t) => {
            const active = tab === t;
            return (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  background: 'transparent',
                  border: 'none',
                  borderBottom: active ? `2px solid ${T.cobalt}` : '2px solid transparent',
                  borderRadius: 0,
                  padding: '0 10px',
                  height: 44,
                  fontSize: 10,
                  fontFamily: 'var(--font-mono, ui-monospace)',
                  fontWeight: 600,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  color: active ? T.cobalt : T.secondary,
                  cursor: 'pointer',
                  transition: 'color 0.15s, border-color 0.15s',
                }}
              >
                {t}
              </button>
            );
          })}
        </div>

        {/* Right — provenance + close */}
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize: 9,
              fontFamily: 'var(--font-mono, ui-monospace)',
              color: T.secondary,
              letterSpacing: '0.06em',
            }}
          >
            ● REPLAY &nbsp;● CALIBRATED
          </span>
          {onClose && (
            <button
              onClick={onClose}
              aria-label="Close analytics"
              style={{
                background: 'transparent',
                border: `1px solid ${T.hairline}`,
                borderRadius: 2,
                color: T.secondary,
                fontSize: 14,
                width: 22,
                height: 22,
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                lineHeight: 1,
              }}
            >
              ✕
            </button>
          )}
        </div>
      </header>

      {/* ── Body ─────────────────────────────────────────────────────────── */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '14px 12px',
          display: 'flex',
          flexDirection: 'column',
          gap: 14,
        }}
      >
        {error && (
          <div
            role="alert"
            style={{
              fontSize: 11,
              fontFamily: 'var(--font-mono, ui-monospace)',
              color: T.oxide,
              background: T.oxideLight,
              border: `1px solid ${T.oxide}`,
              borderRadius: 2,
              padding: '6px 10px',
            }}
          >
            Analytics backend offline: {error}
          </div>
        )}

        {!error && scorecard == null && (
          <div
            style={{
              fontSize: 11,
              fontFamily: 'var(--font-mono, ui-monospace)',
              color: T.secondary,
            }}
          >
            Loading analytics…
          </div>
        )}

        {/* ════════════════════════════════════════════════════════════════
            TAB: SCORECARD — P&L Financial Dashboard
        ════════════════════════════════════════════════════════════════ */}
        {tab === 'Scorecard' && scorecard && (
          <>
            {/* A: Projection horizon cards */}
            <div>
              <SectionLabel>P&amp;L Projection Horizons</SectionLabel>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: 8,
                }}
              >
                {windows.map((w) => (
                  <Card key={w.period}>
                    <div
                      style={{
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        fontWeight: 600,
                        letterSpacing: '0.10em',
                        textTransform: 'uppercase',
                        color: T.secondary,
                        marginBottom: 8,
                        borderBottom: `1px solid ${T.hairline}`,
                        paddingBottom: 4,
                      }}
                    >
                      Next {w.period === 'day' ? '24 h' : w.period === 'week' ? '7 d' : '30 d'} ·{' '}
                      {w.shipments} shipments
                    </div>
                    <dl
                      style={{
                        display: 'grid',
                        gridTemplateColumns: '1fr auto',
                        rowGap: 3,
                        fontSize: 10,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        margin: 0,
                      }}
                    >
                      <dt style={{ color: T.secondary }}>Revenue</dt>
                      <dd style={{ margin: 0, textAlign: 'right', color: T.ink }}>
                        {fmtUsd(w.total_revenue)}
                      </dd>
                      <dt style={{ color: T.secondary }}>Shipping cost</dt>
                      <dd style={{ margin: 0, textAlign: 'right', color: T.ink }}>
                        {fmtUsd(w.total_shipping_cost)}
                      </dd>
                      <dt style={{ color: T.secondary }}>Decided margin</dt>
                      <dd style={{ margin: 0, textAlign: 'right', color: T.moss, fontWeight: 600 }}>
                        {fmtUsd(w.decided_margin)}
                      </dd>
                      <dt style={{ color: T.secondary }}>Undecided rev</dt>
                      <dd style={{ margin: 0, textAlign: 'right', color: T.ink }}>
                        {fmtUsd(w.undecided_revenue)}
                      </dd>
                      <dt style={{ color: T.secondary }}>Pending SLA est</dt>
                      <dd style={{ margin: 0, textAlign: 'right', color: T.oxide }}>
                        {fmtUsd(w.undecided_pending_sla_est)}
                      </dd>
                      <dt style={{ color: T.secondary }}>Pending demurrage</dt>
                      <dd style={{ margin: 0, textAlign: 'right', color: T.oxide }}>
                        {fmtUsd(w.undecided_pending_demurrage_est)}
                      </dd>
                      <dt style={{ color: T.secondary, borderTop: `1px solid ${T.hairline}`, paddingTop: 3, marginTop: 2 }}>
                        Total pending
                      </dt>
                      <dd
                        style={{
                          margin: 0,
                          textAlign: 'right',
                          color: T.oxide,
                          fontWeight: 600,
                          borderTop: `1px solid ${T.hairline}`,
                          paddingTop: 3,
                          marginTop: 2,
                        }}
                      >
                        {fmtUsd(w.undecided_total_pending_est)}
                      </dd>
                    </dl>
                  </Card>
                ))}
              </div>
            </div>

            {/* B: Revenue vs Costs bar chart */}
            <div>
              <SectionLabel>Revenue vs Total Costs — per Shipment</SectionLabel>
              <Card style={{ padding: '10px 8px 6px' }}>
                <div style={{ width: '100%', height: 200 }}>
                  <ResponsiveContainer>
                    <BarChart
                      data={scorecard.rows.slice(0, 15)}
                      margin={{ top: 8, right: 10, left: 10, bottom: 4 }}
                      barCategoryGap="30%"
                    >
                      <CartesianGrid
                        strokeDasharray="none"
                        stroke={T.hairline}
                        vertical={false}
                      />
                      <XAxis
                        dataKey="shipment_id"
                        tick={{ fill: T.secondary, fontSize: 9, fontFamily: 'ui-monospace' }}
                        tickFormatter={(val) => val.slice(0, 6)}
                        axisLine={{ stroke: T.hairline }}
                        tickLine={false}
                      />
                      <YAxis
                        tick={{ fill: T.secondary, fontSize: 9, fontFamily: 'ui-monospace' }}
                        tickFormatter={(val) => `$${(val / 1000).toFixed(0)}k`}
                        axisLine={false}
                        tickLine={false}
                      />
                      <RechartsTooltip content={<CustomTooltip />} />
                      <Legend
                        wrapperStyle={{
                          fontSize: 9,
                          fontFamily: 'ui-monospace',
                          paddingTop: 6,
                          color: T.secondary,
                          letterSpacing: '0.06em',
                        }}
                      />
                      <Bar
                        dataKey="revenue_usd"
                        name="Revenue"
                        fill={T.cobalt}
                        radius={[2, 2, 0, 0]}
                      />
                      <Bar
                        dataKey="total_costs_usd"
                        name="Total Costs"
                        fill={T.oxide}
                        radius={[2, 2, 0, 0]}
                      />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </Card>
            </div>

            {/* C: P&L Margin Ledger Table */}
            <div>
              <SectionLabel>Shipment P&amp;L Margin Ledger</SectionLabel>
              <Card style={{ padding: 0 }}>
                <table
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: 10,
                    fontFamily: 'var(--font-mono, ui-monospace)',
                  }}
                >
                  <thead>
                    <tr style={{ background: T.subtle }}>
                      {[
                        'Shipment',
                        'Mode',
                        'Status',
                        'Revenue',
                        'Cost',
                        'Freight',
                        'SLA pen',
                        'Demurrage',
                        'Margin',
                        'Margin %',
                      ].map((h) => (
                        <th
                          key={h}
                          style={{
                            padding: '5px 7px',
                            borderBottom: `1px solid ${T.hairline}`,
                            fontWeight: 600,
                            letterSpacing: '0.06em',
                            textTransform: 'uppercase',
                            fontSize: 9,
                            color: T.secondary,
                            textAlign: 'left',
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {scorecard.rows.map((row, idx) => (
                      <tr
                        key={row.shipment_id}
                        onClick={() => onOpenInspector?.(row.shipment_id)}
                        style={{
                          cursor: 'pointer',
                          background: idx % 2 === 0 ? T.surface : T.subtle,
                          borderBottom: `1px solid ${T.hairline}`,
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.background =
                            'rgba(37,71,200,0.04)';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.background =
                            idx % 2 === 0 ? T.surface : T.subtle;
                        }}
                      >
                        <td style={{ padding: '4px 7px', color: T.cobalt }}>
                          {row.shipment_id.slice(0, 8)}…
                        </td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>{row.mode}</td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>{row.status}</td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>
                          {fmtUsd(row.revenue_usd)}
                        </td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>
                          {fmtUsd(row.total_costs_usd)}
                        </td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>
                          {fmtUsd(row.freight_cost_usd)}
                        </td>
                        <td
                          style={{
                            padding: '4px 7px',
                            color: row.sla_penalty_usd > 0 ? T.oxide : T.ink,
                          }}
                        >
                          {fmtUsd(row.sla_penalty_usd)}
                        </td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>
                          {fmtUsd(row.demurrage_usd)}
                        </td>
                        <td
                          style={{
                            padding: '4px 7px',
                            color: row.margin_usd >= 0 ? T.moss : T.oxide,
                            fontWeight: 600,
                          }}
                        >
                          {fmtUsd(row.margin_usd)}
                        </td>
                        <td style={{ padding: '4px 7px', color: T.secondary }}>
                          {fmtPct(row.margin_pct)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          </>
        )}

        {/* ════════════════════════════════════════════════════════════════
            TAB: FLEET — Operations & Demand Forecast
        ════════════════════════════════════════════════════════════════ */}
        {tab === 'Fleet' && summary && (
          <>
            {/* A: KPI stat grid */}
            <div>
              <SectionLabel>Fleet Operations KPIs</SectionLabel>
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(3, 1fr)',
                  gap: 8,
                }}
              >
                {(
                  [
                    { label: 'Total Fleet', value: summary.total_shipments, color: T.ink },
                    { label: 'In Transit', value: summary.in_transit, color: T.cobalt },
                    { label: 'Delivered', value: summary.delivered, color: T.moss },
                    { label: 'Delayed', value: summary.delayed, color: T.oxide },
                    { label: 'SLA Breaches', value: summary.sla_breach_count, color: T.oxide },
                    { label: 'Open Alerts', value: summary.open_alerts, color: T.oxide },
                  ] as const
                ).map(({ label, value, color }) => (
                  <Card key={label}>
                    <div
                      style={{
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        fontWeight: 600,
                        letterSpacing: '0.10em',
                        textTransform: 'uppercase',
                        color: T.secondary,
                        marginBottom: 6,
                      }}
                    >
                      {label}
                    </div>
                    <div
                      style={{
                        fontSize: 22,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        fontWeight: 700,
                        fontVariantNumeric: 'tabular-nums',
                        color,
                        lineHeight: 1.1,
                      }}
                    >
                      {value?.toLocaleString() ?? '—'}
                    </div>
                  </Card>
                ))}
              </div>
            </div>

            {/* B: Status distribution bar */}
            <div>
              <SectionLabel>Status Distribution</SectionLabel>
              <Card>
                {fleetTotal > 0 && (
                  <>
                    <div
                      style={{
                        display: 'flex',
                        height: 8,
                        borderRadius: 2,
                        overflow: 'hidden',
                        border: `1px solid ${T.hairline}`,
                        marginBottom: 8,
                      }}
                    >
                      {[
                        {
                          pct: ((summary.in_transit ?? 0) / fleetTotal) * 100,
                          color: T.cobalt,
                          label: 'In Transit',
                        },
                        {
                          pct: ((summary.delivered ?? 0) / fleetTotal) * 100,
                          color: T.moss,
                          label: 'Delivered',
                        },
                        {
                          pct: ((summary.delayed ?? 0) / fleetTotal) * 100,
                          color: T.oxide,
                          label: 'Delayed',
                        },
                      ].map(({ pct, color, label }) => (
                        <div
                          key={label}
                          title={`${label}: ${pct.toFixed(1)}%`}
                          style={{ width: `${pct}%`, background: color, flexShrink: 0 }}
                        />
                      ))}
                    </div>
                    <div
                      style={{
                        display: 'flex',
                        gap: 14,
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        color: T.secondary,
                      }}
                    >
                      {[
                        {
                          label: 'IN TRANSIT',
                          value: summary.in_transit,
                          color: T.cobalt,
                        },
                        {
                          label: 'DELIVERED',
                          value: summary.delivered,
                          color: T.moss,
                        },
                        { label: 'DELAYED', value: summary.delayed, color: T.oxide },
                      ].map(({ label, value, color }) => (
                        <span key={label} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                          <span
                            style={{
                              display: 'inline-block',
                              width: 8,
                              height: 8,
                              borderRadius: 1,
                              background: color,
                            }}
                          />
                          <span style={{ color }}>
                            {label}{' '}
                            <strong style={{ color: T.ink }}>
                              {((( value ?? 0) / fleetTotal) * 100).toFixed(1)}%
                            </strong>
                          </span>
                        </span>
                      ))}
                    </div>
                    {/* Status by key */}
                    <div
                      style={{
                        marginTop: 8,
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        color: T.secondary,
                        borderTop: `1px solid ${T.hairline}`,
                        paddingTop: 6,
                      }}
                    >
                      {Object.entries(summary.summary_by_status)
                        .map(([k, v]) => `${k} ${v}`)
                        .join(' · ')}
                    </div>
                  </>
                )}
              </Card>
            </div>

            {/* C: 90-Day Demand Forecast Sparklines */}
            <div>
              <SectionLabel>
                StatsForecast AutoETS Demand Forecast · 90-Day Horizon &nbsp;
                <span
                  style={{
                    display: 'inline-block',
                    padding: '0 4px',
                    border: `1px solid ${T.hairline}`,
                    borderRadius: 2,
                    fontSize: 8,
                    letterSpacing: '0.06em',
                    color: T.secondary,
                    fontWeight: 500,
                  }}
                >
                  ● CALIBRATED
                </span>
              </SectionLabel>
              <Card style={{ padding: 0, overflow: 'hidden' }}>
                {SPARKLINE_LANES.map((lane, idx) => (
                  <div
                    key={lane.label}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      padding: '10px 12px',
                      borderBottom:
                        idx < SPARKLINE_LANES.length - 1 ? `1px solid ${T.hairline}` : undefined,
                    }}
                  >
                    <div style={{ flex: 1 }}>
                      <div
                        style={{
                          fontSize: 9,
                          fontFamily: 'var(--font-mono, ui-monospace)',
                          fontWeight: 600,
                          letterSpacing: '0.08em',
                          textTransform: 'uppercase',
                          color: T.secondary,
                          marginBottom: 4,
                        }}
                      >
                        {lane.label}
                      </div>
                      {sparklines[lane.label] ? (
                        <Sparkline series={sparklines[lane.label]} />
                      ) : (
                        <div
                          style={{
                            height: 44,
                            fontSize: 10,
                            fontFamily: 'var(--font-mono, ui-monospace)',
                            color: T.secondary,
                            display: 'flex',
                            alignItems: 'center',
                          }}
                        >
                          {sparkError ? '— forecast unavailable' : 'loading…'}
                        </div>
                      )}
                    </div>
                    <div
                      style={{
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        color: T.secondary,
                        textAlign: 'right',
                      }}
                    >
                      <div style={{ color: T.secondary, marginBottom: 2 }}>TREND</div>
                      <div style={{ color: T.cobalt, fontWeight: 600 }}>
                        {sparklines[lane.label]
                          ? `90 d forecast`
                          : '—'}
                      </div>
                    </div>
                  </div>
                ))}
                <div
                  style={{
                    padding: '6px 12px',
                    fontSize: 9,
                    fontFamily: 'var(--font-mono, ui-monospace)',
                    color: T.secondary,
                    letterSpacing: '0.06em',
                    background: T.subtle,
                    borderTop: `1px solid ${T.hairline}`,
                  }}
                >
                  ─ HISTORICAL &nbsp; ╌ FORECAST EXTRAPOLATION · [● CALIBRATED]
                </div>
              </Card>
            </div>
          </>
        )}

        {/* ════════════════════════════════════════════════════════════════
            TAB: SLA RISK — Penalty Ledger
        ════════════════════════════════════════════════════════════════ */}
        {tab === 'SLA risk' && sla && (
          <>
            {/* A: Summary strip */}
            <div>
              <SectionLabel>SLA Risk Summary</SectionLabel>
              <Card>
                <div style={{ display: 'flex', gap: 24 }}>
                  {[
                    {
                      label: 'AT RISK',
                      value: sla.rows.filter((r) => r.sla_status === 'AT_RISK').length,
                      color: T.oxide,
                    },
                    {
                      label: 'LATE',
                      value: sla.rows.filter((r) => r.sla_status === 'LATE').length,
                      color: T.oxide,
                    },
                    {
                      label: 'ON TIME',
                      value: sla.rows.filter((r) => r.sla_status === 'ON_TIME').length,
                      color: T.moss,
                    },
                  ].map(({ label, value, color }) => (
                    <div key={label}>
                      <div
                        style={{
                          fontSize: 9,
                          fontFamily: 'var(--font-mono, ui-monospace)',
                          fontWeight: 600,
                          letterSpacing: '0.10em',
                          color: T.secondary,
                          marginBottom: 2,
                        }}
                      >
                        {label}
                      </div>
                      <div
                        style={{
                          fontSize: 20,
                          fontFamily: 'var(--font-mono, ui-monospace)',
                          fontWeight: 700,
                          fontVariantNumeric: 'tabular-nums',
                          color,
                        }}
                      >
                        {value}
                      </div>
                    </div>
                  ))}
                </div>
              </Card>
            </div>

            {/* B: SLA Risk Ledger Table */}
            <div>
              <SectionLabel>SLA Risk Ledger</SectionLabel>
              <Card style={{ padding: 0 }}>
                <table
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: 10,
                    fontFamily: 'var(--font-mono, ui-monospace)',
                  }}
                >
                  <thead>
                    <tr style={{ background: T.subtle }}>
                      {[
                        'Shipment',
                        'Status',
                        'Days to deadline',
                        'Delay (d)',
                        'Disruption',
                      ].map((h) => (
                        <th
                          key={h}
                          style={{
                            padding: '5px 7px',
                            borderBottom: `1px solid ${T.hairline}`,
                            fontWeight: 600,
                            letterSpacing: '0.06em',
                            textTransform: 'uppercase',
                            fontSize: 9,
                            color: T.secondary,
                            textAlign: 'left',
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {sla.rows.map((row, idx) => (
                      <tr
                        key={row.shipment_id}
                        onClick={() => onOpenInspector?.(row.shipment_id)}
                        style={{
                          cursor: 'pointer',
                          background: idx % 2 === 0 ? T.surface : T.subtle,
                          borderBottom: `1px solid ${T.hairline}`,
                        }}
                        onMouseEnter={(e) => {
                          (e.currentTarget as HTMLElement).style.background =
                            'rgba(37,71,200,0.04)';
                        }}
                        onMouseLeave={(e) => {
                          (e.currentTarget as HTMLElement).style.background =
                            idx % 2 === 0 ? T.surface : T.subtle;
                        }}
                      >
                        <td style={{ padding: '4px 7px', color: T.cobalt }}>
                          {row.shipment_id.slice(0, 8)}…
                        </td>
                        <td style={{ padding: '4px 7px' }}>
                          <StatusPill status={row.sla_status} />
                        </td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>
                          {row.days_to_deadline == null ? '—' : row.days_to_deadline.toFixed(1)}
                        </td>
                        <td
                          style={{
                            padding: '4px 7px',
                            color: (row.delay_days ?? 0) > 0 ? T.oxide : T.moss,
                            fontWeight: (row.delay_days ?? 0) > 0 ? 600 : 400,
                          }}
                        >
                          {row.delay_days ?? 0}
                        </td>
                        <td style={{ padding: '4px 7px', color: T.secondary, fontStyle: 'italic' }}>
                          {row.disruption_description ?? (row.disrupted ? 'disrupted' : '—')}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </Card>
            </div>
          </>
        )}

        {/* ════════════════════════════════════════════════════════════════
            TAB: ESG — Carbon Accounting Ledger
        ════════════════════════════════════════════════════════════════ */}
        {tab === 'ESG' && esg && (
          <>
            {/* A: ESG Summary header */}
            <div>
              <SectionLabel>Carbon Accounting Summary</SectionLabel>
              <Card>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                  }}
                >
                  <div>
                    <div
                      style={{
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        letterSpacing: '0.10em',
                        textTransform: 'uppercase',
                        color: T.secondary,
                        marginBottom: 4,
                      }}
                    >
                      Total CO₂e · Active Fleet
                    </div>
                    <div
                      style={{
                        fontSize: 22,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        fontWeight: 700,
                        fontVariantNumeric: 'tabular-nums',
                        color: T.ink,
                      }}
                    >
                      {esg.rows
                        .reduce((sum, r) => sum + r.kg_co2, 0)
                        .toLocaleString(undefined, { maximumFractionDigits: 0 })}{' '}
                      kg CO₂e
                    </div>
                  </div>
                  <div style={{ textAlign: 'right' }}>
                    <div
                      style={{
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        letterSpacing: '0.10em',
                        textTransform: 'uppercase',
                        color: T.secondary,
                        marginBottom: 4,
                      }}
                    >
                      vs Air Baseline
                    </div>
                    <div
                      style={{
                        fontSize: 18,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        fontWeight: 700,
                        color: T.moss,
                      }}
                    >
                      {(() => {
                        const valid = esg.rows
                          .map((r) => r.vs_air_co2_saving_pct)
                          .filter((v): v is number => v != null);
                        if (!valid.length) return '—';
                        const avg = valid.reduce((s, v) => s + v, 0) / valid.length;
                        return Math.abs(avg).toFixed(1);
                      })()}
                      %
                    </div>
                    <div
                      style={{
                        fontSize: 9,
                        fontFamily: 'var(--font-mono, ui-monospace)',
                        color: T.secondary,
                        marginTop: 2,
                      }}
                    >
                      IMO 2024 Marine Fuel Spec · [● CALIBRATED]
                    </div>
                  </div>
                </div>

                {/* Route breakdown pills */}
                <div
                  style={{
                    marginTop: 10,
                    paddingTop: 8,
                    borderTop: `1px solid ${T.hairline}`,
                    fontSize: 9,
                    fontFamily: 'var(--font-mono, ui-monospace)',
                    color: T.secondary,
                  }}
                >
                  <span
                    style={{
                      fontWeight: 600,
                      letterSpacing: '0.08em',
                      textTransform: 'uppercase',
                      marginRight: 6,
                    }}
                  >
                    Route breakdown:
                  </span>
                  {Object.entries(esg.route_breakdown)
                    .map(([k, v]) => `${k} ${v}`)
                    .join(' · ')}
                </div>
              </Card>
            </div>

            {/* B: Route CO2 Breakdown Table */}
            <div>
              <SectionLabel>Route CO₂ Accounting Ledger</SectionLabel>
              <Card style={{ padding: 0 }}>
                <table
                  style={{
                    width: '100%',
                    borderCollapse: 'collapse',
                    fontSize: 10,
                    fontFamily: 'var(--font-mono, ui-monospace)',
                  }}
                >
                  <thead>
                    <tr style={{ background: T.subtle }}>
                      {[
                        'Shipment',
                        'Mode',
                        'CO₂ (kg)',
                        'CO₂/ctr',
                        'vs Air CO₂ saving',
                        'vs Air freight Δ',
                      ].map((h) => (
                        <th
                          key={h}
                          style={{
                            padding: '5px 7px',
                            borderBottom: `1px solid ${T.hairline}`,
                            fontWeight: 600,
                            letterSpacing: '0.06em',
                            textTransform: 'uppercase',
                            fontSize: 9,
                            color: T.secondary,
                            textAlign: 'left',
                          }}
                        >
                          {h}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {esg.rows.map((row, idx) => (
                      <tr
                        key={row.shipment_id}
                        style={{
                          background: idx % 2 === 0 ? T.surface : T.subtle,
                          borderBottom: `1px solid ${T.hairline}`,
                        }}
                      >
                        <td style={{ padding: '4px 7px', color: T.cobalt }}>
                          {row.shipment_id.slice(0, 8)}…
                        </td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>{row.mode}</td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>
                          {row.kg_co2.toLocaleString(undefined, { maximumFractionDigits: 1 })}
                        </td>
                        <td style={{ padding: '4px 7px', color: T.ink }}>
                          {row.kg_co2e_per_container.toLocaleString(undefined, {
                            maximumFractionDigits: 1,
                          })}
                        </td>
                        <td
                          style={{
                            padding: '4px 7px',
                            color: (row.vs_air_co2_saving_pct ?? 0) > 0 ? T.moss : T.oxide,
                            fontWeight: 600,
                          }}
                        >
                          {row.vs_air_co2_saving_pct == null
                            ? '—'
                            : `${row.vs_air_co2_saving_pct.toFixed(1)}%`}
                        </td>
                        <td
                          style={{
                            padding: '4px 7px',
                            color:
                              row.vs_air_freight_delta_pct == null
                                ? T.secondary
                                : row.vs_air_freight_delta_pct < 0
                                  ? T.moss
                                  : T.oxide,
                          }}
                        >
                          {row.vs_air_freight_delta_pct == null
                            ? '—'
                            : `${row.vs_air_freight_delta_pct.toFixed(1)}%`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>

                {/* Baseline footnote */}
                <div
                  style={{
                    padding: '6px 10px',
                    fontSize: 9,
                    fontFamily: 'var(--font-mono, ui-monospace)',
                    color: T.secondary,
                    letterSpacing: '0.05em',
                    background: T.subtle,
                    borderTop: `1px solid ${T.hairline}`,
                  }}
                >
                  AIR FREIGHT BASELINE: ~48 kg CO₂/ctr/1,000 km · SEA FREIGHT: ~8–25 kg
                  CO₂/ctr/1,000 km
                </div>
              </Card>
            </div>
          </>
        )}
      </div>
    </section>
  );
}
