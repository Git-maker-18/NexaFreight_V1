'use client';

/**
 * CHARTROOM InsightsCharts — the real-data body of /insights.
 * Fetches the four analytics endpoints via apiFetch (token attached),
 * renders KPI tiles + bar + line charts (recharts), and DEGRADES HONESTLY:
 * LoadingGlobe while fetching · per-section NO DATA · error + RETRY.
 * Law: flat paper, hairlines, mono numerals, ₹ via format helpers.
 */
import { useCallback, useEffect, useState } from 'react';
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Line, LineChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';
import { apiFetch, getDemandForecast } from '@/lib/nexafreight/client';
import type {
  AnalyticsEsgResponse,
  AnalyticsFinancialResponse,
  AnalyticsSlaResponse,
  DemandForecastResponse,
} from '@/lib/nexafreight/types';
import { formatInr, formatInrCompact, usdToInr } from '@/lib/format/inr';
import LoadingGlobe from '@/components/art/LoadingGlobe';
import { ProvenanceChip } from '@/components/ProvenanceBadge';


/** Never hang forever on a stalled/cold backend — 12s honest timeout. */
function withTimeout<T>(p: Promise<T>, ms = 12000): Promise<T> {
  return Promise.race([
    p,
    new Promise<T>((_, rej) => setTimeout(() => rej(new Error('TIMEOUT — backend unreachable')), ms)),
  ]);
}

type Bundle = {
  scorecard: AnalyticsFinancialResponse | null;
  sla: AnalyticsSlaResponse | null;
  esg: AnalyticsEsgResponse | null;
};

const INK = '#16181D';
const COBALT = '#2547C8';
const HAIR = '#D4D5D0';
const HAIR2 = '#E2E3DF';
const MUTED = '#4B515D';
const GHOST = '#797E8B';

/** One hairline ledger row: label · proportional bar · ₹ value (tabular). */
function LedgerRow({ label, inr, frac, color }: { label: string; inr: number; frac: number; color: string }) {
  return (
    <div className="flex items-center" style={{ gap: 10 }}>
      <span style={{ width: 128, flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 9.5, letterSpacing: '0.1em', color: MUTED }}>{label}</span>
      <span style={{ flex: 1, height: 8, background: 'var(--bg-subtle, #ECEEE9)', position: 'relative' }}>
        <span style={{ position: 'absolute', inset: 0, right: 'auto', width: `${Math.max(1.5, Math.min(100, frac * 100))}%`, background: color, opacity: 0.85 }} />
      </span>
      <span style={{ width: 86, textAlign: 'right', flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 11.5, fontWeight: 700, color, fontVariantNumeric: 'tabular-nums' }}>
        {formatInrCompact(inr)}
      </span>
    </div>
  );
}

function Tile({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div
      className="flex flex-col justify-between"
      style={{
        flex: 1, minWidth: 180, background: 'var(--paper)',
        border: `1px solid ${HAIR}`, borderRadius: 4, padding: '14px 16px',
      }}
    >
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.12em', color: 'var(--text-secondary)' }}>
        {label}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 30, fontWeight: 600, color: accent ? COBALT : INK, fontVariantNumeric: 'tabular-nums', lineHeight: 1.15 }}>
        {value}
      </div>
      {sub && (
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-secondary)', letterSpacing: '0.08em' }}>
          {sub}
        </div>
      )}
    </div>
  );
}

function ChartFrame({ title, mod, provenance, style, children }: { title: string; mod?: string; provenance?: string; style?: React.CSSProperties; children: React.ReactNode }) {
  return (
    <div style={{ flex: 1, minWidth: 380, background: 'var(--paper)', border: `1px solid ${HAIR}`, borderRadius: 4, padding: '12px 14px', ...style }}>
      <div className="flex items-center justify-between" style={{ marginBottom: 10, gap: 8 }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.14em', color: INK }}>{title}</span>
        <span className="flex items-center" style={{ gap: 8, flexShrink: 0 }}>
          {mod && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.12em', color: GHOST }}>
              MOD-{mod}
            </span>
          )}
          {provenance && (
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.1em', color: 'var(--text-secondary)', border: `1px solid ${HAIR}`, borderRadius: 2, padding: '2px 6px' }}>
              {provenance}
            </span>
          )}
        </span>
      </div>
      {children}
    </div>
  );
}

const tooltipStyle = {
  background: 'var(--paper)', border: `1px solid ${HAIR}`, borderRadius: 2,
  fontFamily: 'var(--font-mono)', fontSize: 11, color: INK,
  boxShadow: 'none', padding: '6px 8px',
};
const tooltipLabelStyle = { color: MUTED, fontSize: 9.5, letterSpacing: '0.1em', marginBottom: 2 };
const tooltipItemStyle = { color: INK, fontSize: 11, fontVariantNumeric: 'tabular-nums' as const };

/* ── MOD-407 // DEMAND_FCST — StatsForecast AutoETS order-intake forecast ──
   Surfaces the trained demand model (models/demand_forecast/model.joblib) via
   GET /api/demand/forecast. Three real trained lanes; 30/60/90-day horizons.
   Fan chart: ink line = observed history, cobalt dashed = ŷ forecast, shaded
   band = yhat_lower…yhat_upper interval. Degrades honestly per state. */

const DEMAND_LANES: Array<{ category: string; region: string; label: string }> = [
  { category: 'Electronics', region: 'South Asia', label: 'ELECTRONICS · S. ASIA' },
  { category: 'Camping & Hiking', region: 'Western Europe', label: 'CAMPING & HIKING · W. EUROPE' },
  { category: 'Water Sports', region: 'Caribbean', label: 'WATER SPORTS · CARIBBEAN' },
];

type FcstPoint = {
  ds: string;
  hist: number | null;
  fcst: number | null;
  band: [number, number] | null;
  yhat: number;
  lo: number | null;
  hi: number | null;
  isFcst: boolean;
};

function DemandForecastPanel() {
  const [laneIdx, setLaneIdx] = useState(0);
  const [horizon, setHorizon] = useState<30 | 60 | 90>(90);
  const [state, setState] = useState<'loading' | 'empty' | 'error' | 'done'>('loading');
  const [resp, setResp] = useState<DemandForecastResponse | null>(null);

  const lane = DEMAND_LANES[laneIdx];

  const load = useCallback(async (category: string, region: string, h: 30 | 60 | 90) => {
    setState('loading');
    try {
      const r = await withTimeout(getDemandForecast(category, region, h));
      setResp(r);
      setState(r ? 'done' : 'empty');
    } catch {
      setState('error');
    }
  }, []);

  useEffect(() => { void load(lane.category, lane.region, horizon); }, [load, lane.category, lane.region, horizon]);

  const points: FcstPoint[] = [];
  if (resp) {
    resp.series.forEach((p, i) => {
      const firstFcst = p.is_forecast && (i === 0 || !resp.series[i - 1].is_forecast);
      points.push({
        ds: p.ds,
        hist: p.is_forecast ? null : p.yhat,
        fcst: p.is_forecast || firstFcst ? p.yhat : null,
        band: p.is_forecast && p.yhat_lower != null && p.yhat_upper != null ? [p.yhat_lower, p.yhat_upper] : null,
        yhat: p.yhat,
        lo: p.yhat_lower,
        hi: p.yhat_upper,
        isFcst: p.is_forecast,
      });
    });
  }
  const last = points.length ? points[points.length - 1] : null;
  const spread = last && last.lo != null && last.hi != null && last.yhat !== 0
    ? Math.round(((last.hi - last.lo) / 2 / Math.abs(last.yhat)) * 100)
    : null;

  const dayLabel = (iso: string) => {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? iso.slice(5) : `${d.toLocaleString('en-US', { month: 'short' })} ${d.getDate()}`;
  };

  const mono = { fontFamily: 'var(--font-mono)' } as const;

  return (
    <ChartFrame
      title={`DEMAND FORECAST — STATSFORECAST AUTOETS ORDER INTAKE · ${lane.label}`}
      mod="407 // DEMAND_FCST"
      provenance={resp ? `ML · ${resp.model_version}` : 'ML'}
      style={{ minWidth: '100%' }}
    >
      {/* Controls: lane picker + horizon toggle */}
      <div className="flex items-center justify-between flex-wrap" style={{ gap: 10, marginBottom: 10 }}>
        <div className="flex items-center" style={{ gap: 6 }}>
          {DEMAND_LANES.map((l, i) => (
            <button
              key={l.label}
              onClick={() => setLaneIdx(i)}
              style={{
                ...mono, fontSize: 9.5, letterSpacing: '0.1em', cursor: 'pointer',
                padding: '4px 9px', borderRadius: 2,
                border: `1px solid ${i === laneIdx ? COBALT : HAIR}`,
                background: i === laneIdx ? COBALT : 'transparent',
                color: i === laneIdx ? '#fff' : MUTED,
              }}
            >
              {l.label}
            </button>
          ))}
        </div>
        <div className="flex items-center" style={{ gap: 6 }}>
          <span style={{ ...mono, fontSize: 9, letterSpacing: '0.12em', color: GHOST }}>HORIZON</span>
          {([30, 60, 90] as const).map((h) => (
            <button
              key={h}
              onClick={() => setHorizon(h)}
              style={{
                ...mono, fontSize: 9.5, letterSpacing: '0.08em', cursor: 'pointer',
                padding: '4px 8px', borderRadius: 2,
                border: `1px solid ${h === horizon ? COBALT : HAIR}`,
                background: h === horizon ? COBALT : 'transparent',
                color: h === horizon ? '#fff' : MUTED,
              }}
            >
              {h}D
            </button>
          ))}
        </div>
      </div>

      {state === 'loading' && (
        <div style={{ ...mono, fontSize: 10.5, letterSpacing: '0.1em', color: GHOST, padding: '96px 0', textAlign: 'center' }}>
          QUERYING STATSFORECAST AUTOETS ARTIFACT…
        </div>
      )}
      {state === 'error' && (
        <div style={{ ...mono, fontSize: 10.5, letterSpacing: '0.1em', color: '#B42318', padding: '96px 0', textAlign: 'center' }}>
          MODEL FEED UNREACHABLE — RETRY FROM THE LEDGER
        </div>
      )}
      {state === 'empty' && (
        <div style={{ ...mono, fontSize: 10.5, letterSpacing: '0.1em', color: GHOST, padding: '96px 0', textAlign: 'center' }}>
          NO TRAINED LANE FOR THIS CATEGORY × REGION
        </div>
      )}
      {state === 'done' && points.length > 0 && (
        <>
          <ResponsiveContainer width="100%" height={216}>
            <AreaChart data={points} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="fcstBand" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={COBALT} stopOpacity={0.16} />
                  <stop offset="100%" stopColor={COBALT} stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={HAIR} strokeDasharray="3 4" vertical={false} />
              <XAxis
                dataKey="ds"
                tickFormatter={dayLabel}
                minTickGap={42}
                tick={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, fill: MUTED }}
                axisLine={{ stroke: HAIR }} tickLine={false}
              />
              <YAxis
                width={34}
                tick={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, fill: MUTED }}
                axisLine={false} tickLine={false}
              />
              <Tooltip
                contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle}
                labelFormatter={(l: unknown) => `DAY · ${dayLabel(String(l))}`}
                formatter={(v: unknown, n: unknown) => {
                  if (n === 'band') return [] as unknown as [string, string];
                  const unit = `${Number(v).toFixed(1)} ORD/DAY`;
                  return [unit, n === 'hist' ? 'OBSERVED' : 'FORECAST ŷ'];
                }}
              />
              <Area dataKey="band" stroke="none" fill="url(#fcstBand)" connectNulls={false} isAnimationActive={false} />
              <Line dataKey="hist" stroke={INK} strokeWidth={1.6} dot={false} connectNulls={false} isAnimationActive={false} />
              <Line dataKey="fcst" stroke={COBALT} strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls={false} isAnimationActive={false} />
            </AreaChart>
          </ResponsiveContainer>
          <div className="flex items-center justify-between flex-wrap" style={{ gap: 8, marginTop: 6, ...mono, fontSize: 10, color: 'var(--text-secondary)', letterSpacing: '0.08em' }}>
            <span className="flex items-center" style={{ gap: 14 }}>
              <span className="flex items-center" style={{ gap: 5 }}>
                <span style={{ width: 14, height: 0, borderTop: `2px solid ${INK}`, display: 'inline-block' }} /> OBSERVED
              </span>
              <span className="flex items-center" style={{ gap: 5 }}>
                <span style={{ width: 14, height: 0, borderTop: `2px dashed ${COBALT}`, display: 'inline-block' }} /> FORECAST ŷ
              </span>
              <span className="flex items-center" style={{ gap: 5 }}>
                <span style={{ width: 10, height: 8, background: 'rgba(37,71,200,0.14)', display: 'inline-block' }} /> {horizon}-DAY INTERVAL
              </span>
            </span>
            {last && (
              <span style={{ fontVariantNumeric: 'tabular-nums' }}>
                DAY-{horizon} ŷ {last.yhat.toFixed(1)} ORD/DAY{spread != null ? ` · CI ±${spread}%` : ''} · {resp?.horizon_snapshot.toUpperCase()}
              </span>
            )}
          </div>
        </>
      )}
    </ChartFrame>
  );
}


export default function InsightsCharts() {
  const [state, setState] = useState<'loading' | 'error' | 'done'>('loading');
  const [bundle, setBundle] = useState<Bundle>({ scorecard: null, sla: null, esg: null });

  const load = useCallback(async () => {
    setState('loading');
    const [scorecard, sla, esg] = await Promise.allSettled([
      withTimeout(apiFetch<AnalyticsFinancialResponse>('/api/analytics/scorecard', { method: 'GET' })),
      withTimeout(apiFetch<AnalyticsSlaResponse>('/api/analytics/sla', { method: 'GET' })),
      withTimeout(apiFetch<AnalyticsEsgResponse>('/api/analytics/esg', { method: 'GET' })),
    ]);
    const pick = <T,>(r: PromiseSettledResult<T>): T | null => (r.status === 'fulfilled' ? r.value : null);
    const next: Bundle = {
      scorecard: pick(scorecard), sla: pick(sla), esg: pick(esg),
    };
    setBundle(next);
    setState(next.scorecard || next.sla || next.esg ? 'done' : 'error');
  }, []);

  useEffect(() => { void load(); }, [load]);

  // Listen for auth_success so charts load when credentials hydrate
  useEffect(() => {
    const handler = () => { void load(); };
    if (typeof globalThis.window !== 'undefined') {
      globalThis.window.addEventListener('nexafreight:auth_success', handler);
      return () => globalThis.window.removeEventListener('nexafreight:auth_success', handler);
    }
  }, [load]);

  if (state === 'loading') {
    return (
      <div className="flex items-center justify-center" style={{ minHeight: 420 }}>
        <LoadingGlobe caption="QUERYING CARRIER ANALYTICS LEDGER..." progress="TELEMETRY SYNC" size={300} />
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div className="flex flex-col items-center justify-center" style={{ minHeight: 380, gap: 14 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.1em', color: 'var(--oxide-risk)', border: `1px solid var(--oxide-risk)`, borderRadius: 3, padding: '12px 18px' }}>
          ANALYTICS LEDGER UNREACHABLE — CHECK THE BACKEND FEED
        </div>
        <button
          onClick={() => { void load(); }}
          style={{
            fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.14em',
            background: COBALT, color: '#fff', border: 'none', borderRadius: 2,
            padding: '9px 22px', cursor: 'pointer',
          }}
        >
          RETRY SYNC
        </button>
      </div>
    );
  }

  const sc = bundle.scorecard;
  const sla = bundle.sla;
  const esg = bundle.esg;

  const month = sc?.month ?? null;
  const barData = sc
    ? (['day', 'week', 'month'] as const).map((p) => ({
        name: p.toUpperCase(),
        shipments: sc[p]?.shipments ?? 0,
        revenue: Math.round(usdToInr(sc[p]?.total_revenue ?? 0)),
      }))
    : [];

  const slaRows = sla?.rows ?? [];
  const total = slaRows.length;
  const onTime = slaRows.filter((r) => r.sla_status === 'ON_TIME').length;
  const atRisk = slaRows.filter((r) => r.sla_status !== 'ON_TIME').length;
  const onTimePct = total ? Math.round((onTime / total) * 1000) / 10 : null;
  const trend = slaRows.slice(0, 40).map((r, i) => ({
    name: String(i + 1),
    days: r.days_to_deadline ?? 0,
  }));

  const co2 = (esg?.rows ?? []).reduce((s, r) => s + (r.kg_co2 || 0), 0);
  const byMode = new Map<string, { t: number; n: number; savings: number[] }>();
  for (const r of esg?.rows ?? []) {
    const m = byMode.get(r.mode) ?? { t: 0, n: 0, savings: [] };
    m.t += (r.kg_co2 || 0) / 1000;
    m.n += 1;
    if (r.vs_air_co2_saving_pct != null) m.savings.push(r.vs_air_co2_saving_pct);
    byMode.set(r.mode, m);
  }
  const modeRows = [...byMode.entries()]
    .map(([name, m]) => ({
      name,
      tonnes: Math.round(m.t),
      saving: m.savings.length ? Math.round(m.savings.reduce((a, b) => a + b, 0) / m.savings.length) : null,
    }))
    .sort((a, b) => b.tonnes - a.tonnes);

  // ── FINANCIAL ANALYSIS aggregates (all from scorecard rows — real P&L) ──
  const fRows = sc?.rows ?? [];
  const fin = fRows.reduce(
    (acc, r) => {
      acc.revenue += r.revenue_usd || 0;
      acc.shipping += r.shipping_cost_usd || 0;
      acc.freight += r.freight_cost_usd || 0;
      acc.sla += r.sla_penalty_usd || 0;
      acc.demurrage += r.demurrage_usd || 0;
      acc.carbon += r.carbon_cost_usd || 0;
      acc.costs += r.total_costs_usd || 0;
      acc.margin += r.margin_usd || 0;
      return acc;
    },
    { revenue: 0, shipping: 0, freight: 0, sla: 0, demurrage: 0, carbon: 0, costs: 0, margin: 0 },
  );
  const costLines: Array<[string, number, string]> = [
    ['FREIGHT', fin.freight, INK],
    ['BASE SHIPPING', fin.shipping, INK],
    ['SLA PENALTY', fin.sla, fin.sla > 0 ? '#B42318' : INK],
    ['DEMURRAGE', fin.demurrage, fin.demurrage > 0 ? '#B42318' : INK],
    ['CARBON', fin.carbon, INK],
  ];
  const byFinMode = new Map<string, { n: number; rev: number; cost: number; margin: number }>();
  for (const r of fRows) {
    const m = byFinMode.get(r.mode) ?? { n: 0, rev: 0, cost: 0, margin: 0 };
    m.n += 1; m.rev += r.revenue_usd || 0; m.cost += r.total_costs_usd || 0; m.margin += r.margin_usd || 0;
    byFinMode.set(r.mode, m);
  }
  const modeFin = [...byFinMode.entries()]
    .map(([mode, m]) => ({ mode, ...m, pct: m.rev ? Math.round((m.margin / m.rev) * 1000) / 10 : null }))
    .sort((a, b) => b.margin - a.margin);
  const watchlist = fRows
    .filter((r) => r.margin_pct != null)
    .sort((a, b) => (a.margin_pct ?? 0) - (b.margin_pct ?? 0))
    .slice(0, 5);

  return (
    <div className="flex flex-col" style={{ gap: 16, padding: '0 24px 24px' }}>
      {/* KPI tiles */}
      <div className="flex flex-wrap" style={{ gap: 16 }}>
        <Tile label="SHIPMENTS · 30D" value={month ? String(month.shipments) : 'NO DATA'} sub={sc ? 'PROVENANCE: DERIVED' : undefined} />
        <Tile label="REVENUE · 30D" value={month ? formatInrCompact(usdToInr(month.total_revenue)) : 'NO DATA'} sub={month ? `COST ${formatInrCompact(usdToInr(month.total_shipping_cost))}` : undefined} />
        <Tile
          label="SLA AT RISK"
          value={sla ? String(atRisk) : 'NO DATA'}
          sub={onTimePct !== null ? `ON-TIME ${onTimePct}%` : undefined}
          accent={atRisk > 0}
        />
        <Tile label="FLEET CO₂" value={esg ? `${(co2 / 1000).toFixed(1)} t` : 'NO DATA'} sub={esg ? 'SCOPE-3, GLEC FACTORS' : undefined} />
        <Tile
          label="PENDING EXPOSURE · 30D"
          value={month ? formatInrCompact(usdToInr(month.undecided_total_pending_est)) : 'NO DATA'}
          sub={month ? 'SLA + DEMURRAGE EST.' : undefined}
        />
      </div>

      {/* Charts row */}
      <div className="flex flex-wrap" style={{ gap: 16 }}>
        <ChartFrame title="SHIPMENTS & REVENUE BY WINDOW" mod="401 // WINDOW_PNL" provenance="DERIVED">
          {sc ? (
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={barData} margin={{ top: 6, right: 8, left: -14, bottom: 0 }}>
                <CartesianGrid stroke={HAIR} strokeDasharray="3 4" vertical={false} />
                <XAxis dataKey="name" tick={{ fontFamily: 'var(--font-mono)', fontSize: 10, fill: INK }} axisLine={{ stroke: HAIR }} tickLine={false} />
                <YAxis
                  width={58}
                  tickFormatter={(v: number) => (v >= 1e7 ? `${(v / 1e7).toFixed(v >= 1e8 ? 0 : 1)}Cr` : v >= 1e5 ? `${Math.round(v / 1e5)}L` : String(v))}
                  tick={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, fill: MUTED }} axisLine={false} tickLine={false}
                />
                <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} cursor={{ fill: 'rgba(37,71,200,0.06)' }} />
                <Bar dataKey="shipments" fill={COBALT} radius={[2, 2, 0, 0]} maxBarSize={46} />
                <Bar dataKey="revenue" fill={INK} opacity={0.82} radius={[2, 2, 0, 0]} maxBarSize={46} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', padding: '96px 0', textAlign: 'center' }}>NO DATA — scorecard feed absent</div>
          )}
        </ChartFrame>

        <ChartFrame title="DAYS-TO-DEADLINE ACROSS WATCHLIST" mod="402 // SLA_WATCH" provenance="DERIVED">
          {slaRows.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trend} margin={{ top: 6, right: 8, left: -18, bottom: 0 }}>
                <CartesianGrid stroke={HAIR} strokeDasharray="3 4" vertical={false} />
                <XAxis dataKey="name" tick={{ fontFamily: 'var(--font-mono)', fontSize: 10, fill: INK }} axisLine={{ stroke: HAIR }} tickLine={false} />
                <YAxis tick={{ fontFamily: 'var(--font-mono)', fontSize: 10, fill: INK }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} />
                <Line type="monotone" dataKey="days" stroke={COBALT} strokeWidth={1.8} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', padding: '96px 0', textAlign: 'center' }}>NO DATA — SLA feed absent</div>
          )}
        </ChartFrame>
      </div>

      {/* FINANCIAL ANALYSIS — P&L structure · margin by mode · watchlist (all real) */}
      {fRows.length > 0 && (
        <>
          <div className="flex items-center justify-between" style={{ marginTop: 4 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, letterSpacing: '0.16em', color: INK }}>
              FINANCIAL ANALYSIS // P&amp;L STRUCTURE — 30D WINDOW
            </span>
            <ProvenanceChip provenance={(sc?.provenance as 'REAL' | 'DERIVED' | 'SIMULATED' | 'CALIBRATED' | 'HISTORICAL') ?? 'DERIVED'} size="sm" />
          </div>
          <div className="flex flex-wrap" style={{ gap: 16 }}>
            {/* A — cost structure ledger */}
            <div style={{ flex: 4, minWidth: 330, border: `1px solid ${HAIR}`, background: 'var(--surface-bright, #fff)', padding: '12px 14px' }}>
              <div className="flex items-center justify-between" style={{ marginBottom: 10 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.14em', color: 'var(--text-secondary)' }}>REVENUE → COST STRUCTURE (₹)</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.12em', color: GHOST }}>MOD-404 // COST_STRUCT</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 7 }}>
                <LedgerRow label="REVENUE" inr={usdToInr(fin.revenue)} frac={1} color={COBALT} />
                {costLines.map(([label, usd, color]) => (
                  <LedgerRow key={label} label={label} inr={usdToInr(usd)} frac={fin.revenue ? usd / fin.revenue : 0} color={color} />
                ))}
                <div style={{ borderTop: `1px solid ${HAIR}`, paddingTop: 7 }}>
                  <LedgerRow
                    label={fin.margin >= 0 ? 'MARGIN (DECIDED+EST)' : 'MARGIN DEFICIT'}
                    inr={usdToInr(fin.margin)}
                    frac={fin.revenue ? Math.abs(fin.margin) / fin.revenue : 0}
                    color={fin.margin >= 0 ? '#027A48' : '#B42318'}
                  />
                </div>
              </div>
            </div>

            {/* B — margin by mode */}
            <div style={{ flex: 4, minWidth: 380, border: `1px solid ${HAIR}`, background: 'var(--surface-bright, #fff)', padding: '12px 14px' }}>
              <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.14em', color: 'var(--text-secondary)' }}>MARGIN BY MODE</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.12em', color: GHOST }}>MOD-405 // MODE_PNL</span>
              </div>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-subtle, #ECEEE9)' }}>
                    {['MODE', 'N', 'REVENUE', 'MARGIN', 'PCT'].map((h) => (
                      <th key={h} style={{ textAlign: 'left', fontWeight: 500, fontSize: 9.5, letterSpacing: '0.1em', color: MUTED, padding: '4px 6px', borderBottom: `1px solid ${HAIR}` }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {modeFin.map((m) => (
                    <tr key={m.mode} style={{ borderBottom: `1px solid ${HAIR2}` }}>
                      <td style={{ padding: '5px 6px', fontWeight: 700, color: INK }}>{m.mode}</td>
                      <td style={{ padding: '5px 6px', color: MUTED, fontVariantNumeric: 'tabular-nums' }}>{m.n}</td>
                      <td style={{ padding: '5px 6px', color: INK, fontVariantNumeric: 'tabular-nums' }}>{formatInrCompact(usdToInr(m.rev))}</td>
                      <td style={{ padding: '5px 6px', fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: m.margin >= 0 ? '#027A48' : '#B42318' }}>
                        {formatInrCompact(usdToInr(m.margin))}
                      </td>
                      <td style={{ padding: '5px 6px', fontVariantNumeric: 'tabular-nums', color: (m.pct ?? 0) >= 0 ? MUTED : '#B42318' }}>
                        {m.pct == null ? '—' : `${m.pct}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            {/* C — margin watchlist */}
            <div style={{ flex: 3, minWidth: 300, border: `1px solid ${HAIR}`, background: 'var(--surface-bright, #fff)', padding: '12px 14px' }}>
              <div className="flex items-center justify-between" style={{ marginBottom: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, letterSpacing: '0.14em', color: 'var(--text-secondary)' }}>MARGIN WATCHLIST — WORST 5</span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.12em', color: GHOST }}>MOD-406 // MARGIN_WATCH</span>
              </div>
              <div style={{ display: 'flex', flexDirection: 'column' }}>
                {watchlist.map((r) => (
                  <div key={r.shipment_id} className="flex items-center justify-between" style={{ padding: '5px 0', borderBottom: `1px solid ${HAIR2}`, gap: 8 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, color: INK }}>
                      {r.shipment_id.slice(0, 8).toUpperCase()}
                      <span style={{ color: GHOST, fontWeight: 400 }}> · {String(r.mode).toUpperCase()}</span>
                    </span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: (r.margin_usd || 0) >= 0 ? MUTED : '#B42318', fontVariantNumeric: 'tabular-nums' }}>
                      {formatInrCompact(usdToInr(r.margin_usd || 0))} · {r.margin_pct == null ? '—' : Math.abs(r.margin_pct) < 0.05 ? '0.0%' : `${r.margin_pct.toFixed(1)}%`}
                    </span>
                  </div>
                ))}
                {!watchlist.length && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10.5, color: GHOST, padding: '12px 0' }}>NO CALIBRATED MARGINS YET</div>
                )}
              </div>
            </div>
          </div>
        </>
      )}

      {/* Emissions by mode + window ledger */}
      <div className="flex flex-wrap" style={{ gap: 16 }}>
        <ChartFrame title="EMISSIONS BY MODE — SCOPE-3 (t CO₂e)" mod="403 // SCOPE3" provenance="DERIVED" style={{ flex: 7, minWidth: 380 }}>
          {modeRows.length ? (
            <ResponsiveContainer width="100%" height={190}>
              <BarChart data={modeRows} layout="vertical" margin={{ top: 4, right: 26, left: 4, bottom: 0 }}>
                <CartesianGrid stroke={HAIR} strokeDasharray="3 4" horizontal={false} />
                <XAxis type="number" tick={{ fontFamily: 'var(--font-mono)', fontSize: 10, fill: INK }} axisLine={{ stroke: HAIR }} tickLine={false} />
                <YAxis type="category" dataKey="name" width={52} tick={{ fontFamily: 'var(--font-mono)', fontSize: 10, fill: INK }} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={tooltipStyle} labelStyle={tooltipLabelStyle} itemStyle={tooltipItemStyle} cursor={{ fill: 'rgba(37,71,200,0.06)' }} />
                <Bar dataKey="tonnes" fill={COBALT} radius={[0, 2, 2, 0]} maxBarSize={30} label={{ position: 'right', formatter: (v: unknown) => `${String(v)} t`, fontFamily: 'var(--font-mono)', fontSize: 10, fill: INK }} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', padding: '68px 0', textAlign: 'center' }}>NO DATA — ESG feed absent</div>
          )}
          {modeRows.length > 0 && (
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-secondary)', letterSpacing: '0.08em', marginTop: 4 }}>
              VS-AIR SAVING · {' '}
              {modeRows.map((m) => `${m.name} ${m.saving ?? '—'}%`).join('  ·  ')}
            </div>
          )}
        </ChartFrame>

        {sc && (
          <div
            className="flex flex-col justify-between"
            style={{ flex: 5, minWidth: 320, border: `1px dashed ${HAIR}`, borderRadius: 4, padding: '14px 16px', gap: 10 }}
          >
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.12em', color: 'var(--text-secondary)' }}>
              WINDOW LEDGER — PENDING SLA / DEMURRAGE EST. (₹)
            </div>
            {([['DAY', 'day'], ['WEEK', 'week'], ['MONTH', 'month']] as const).map(([label, p]) => (
              <div key={p} className="flex items-center justify-between" style={{ fontFamily: 'var(--font-mono)', fontSize: 12.5, color: INK, fontVariantNumeric: 'tabular-nums' }}>
                <span style={{ color: 'var(--text-secondary)', fontSize: 10.5, letterSpacing: '0.1em' }}>{label} · UNDECIDED</span>
                <span>{formatInr(usdToInr(sc[p]?.undecided_total_pending_est ?? 0))}</span>
              </div>
            ))}
            <div className="flex items-center justify-between" style={{ borderTop: `1px solid ${HAIR}`, paddingTop: 10, fontFamily: 'var(--font-mono)', fontSize: 12.5, color: INK, fontVariantNumeric: 'tabular-nums' }}>
              <span style={{ color: 'var(--text-secondary)', fontSize: 10.5, letterSpacing: '0.1em' }}>DECIDED MARGIN · 30D</span>
              <span>{formatInrCompact(usdToInr(sc.month?.decided_margin ?? 0))}</span>
            </div>
          </div>
        )}
      </div>

      {/* MOD-407 // DEMAND_FCST — StatsForecast AutoETS order-intake forecast */}
      <DemandForecastPanel />
    </div>
  );
}
